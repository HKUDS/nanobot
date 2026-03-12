"""Stateful Python execution tool using IPython kernel."""

import asyncio
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Callable, Awaitable

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage

# Import thread-based IPython support
try:
    from nanobot.agent.tools.ipython_thread import ThreadIPythonManager
    THREAD_IPYTHON_AVAILABLE = True
except ImportError:
    THREAD_IPYTHON_AVAILABLE = False
    ThreadIPythonManager = None

# Optional jupyter_client import (for subprocess mode)
try:
    from jupyter_client import AsyncKernelClient  # type: ignore

    JUPYTER_CLIENT_AVAILABLE = True
except ImportError:
    JUPYTER_CLIENT_AVAILABLE = False
    AsyncKernelClient = None  # type: ignore

# Optional IPython import (for embedded mode)
try:
    from IPython.core.interactiveshell import InteractiveShell
    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False
    InteractiveShell = None  # type: ignore


class IPythonTool(Tool):
    """
    Tool to execute Python code statefully using IPython kernel.

    This maintains state (variables, imports, functions) across multiple executions,
    similar to a Jupyter notebook. Each chat session gets its own kernel instance.
    
    Modes:
    - "embedded": Runs IPython in the same process (can access gateway context)
    - "subprocess": Runs IPython in a separate kernel process (isolated)
    - "thread": Runs IPython in a separate thread with blocking send_message support
    """

    def __init__(
        self,
        working_dir: str | None = None,
        timeout: int = 60,
        max_output_length: int = 10000,
        restrict_to_workspace: bool = False,
        mode: str = "subprocess",  # "embedded", "subprocess", or "thread"
        namespace: dict[str, Any] | None = None,  # Initial namespace for embedded mode
        message_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        tool_registry=None,  # Tool registry for making tools available in IPython
    ):
        self.working_dir = working_dir or str(Path.cwd())
        self.timeout = timeout
        self.max_output_length = max_output_length
        self.restrict_to_workspace = restrict_to_workspace
        self.mode = mode
        self._initial_namespace = namespace or {}
        self._message_callback = message_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._kernels: dict[str, Any] = {}  # session_id -> kernel (IPythonKernel or EmbeddedIPythonKernel)
        self._tool_registry = tool_registry  # Store tool registry for subprocess access
        
        # Initialize thread-based manager if using thread mode
        self._thread_manager: Any = None
        if mode == "thread" and THREAD_IPYTHON_AVAILABLE and ThreadIPythonManager is not None:
            self._thread_manager = ThreadIPythonManager(
                working_dir=self.working_dir,
                max_output_length=self.max_output_length,
            )
            logger.info("Initialized ThreadIPythonManager for thread-based execution")

    @property
    def name(self) -> str:
        return "ipython"

    @property
    def description(self) -> str:
        return (
            "Execute Python code with full IPython support. "
            "Maintains state across executions (variables, imports, functions). "
            "Supports matplotlib plots, magic commands, and rich output. "
            "Use 'restart': true to reset the kernel state."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Can be multi-line.",
                },
                "restart": {
                    "type": "boolean",
                    "description": "If true, restart the kernel before execution (clears all state).",
                    "default": False,
                },
            },
            "required": ["code"],
        }

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate the parameters."""
        errors = []
        if "code" not in params:
            errors.append("missing required 'code' parameter")
        elif not isinstance(params.get("code"), str):
            errors.append("'code' must be a string")
        return errors

    async def execute(self, **kwargs) -> str:
        """
        Execute Python code in an IPython kernel.

        Args:
            code: Python code to execute
            restart: Whether to restart the kernel first
            session_id: Unique identifier for the kernel session

        Returns:
            Execution result including stdout, stderr, and any display output
        """
        # Extract parameters
        code = kwargs.get("code", "")
        restart = kwargs.get("restart", False)
        session_id = kwargs.get("session_id", "default")

        try:
            # Handle thread-based execution
            if self.mode == "thread" and self._thread_manager is not None:
                return await self._execute_thread_mode(code, session_id)

            # Get or create kernel for this session
            if restart or session_id not in self._kernels:
                if session_id in self._kernels:
                    await self._kernels[session_id].shutdown()
                    del self._kernels[session_id]

                if self.mode == "embedded":
                    kernel = EmbeddedIPythonKernel(
                        working_dir=self.working_dir,
                        namespace=self._initial_namespace.copy(),
                        message_callback=self._message_callback,
                        default_channel=self._default_channel,
                        default_chat_id=self._default_chat_id,
                    )
                    await kernel.start()
                    self._kernels[session_id] = kernel
                    logger.info(f"Started embedded IPython kernel for session {session_id}")
                else:
                    self._kernels[session_id] = IPythonKernel(
                        working_dir=self.working_dir,
                        timeout=self.timeout,
                        tool_registry=self._tool_registry,
                    )
                    await self._kernels[session_id].start()
                    logger.info(f"Started subprocess IPython kernel for session {session_id}")

            kernel = self._kernels[session_id]

            # Save current sniffio async library context to prevent corruption
            import sniffio
            original_async_lib = None
            try:
                original_async_lib = sniffio.current_async_library()
            except sniffio.AsyncLibraryNotFoundError:
                pass

            try:
                # Execute the code
                # Pass message_callback for subprocess kernels that need IPC
                if isinstance(kernel, IPythonKernel):
                    result = await kernel.execute(
                        code,
                        message_callback=self._message_callback,
                        default_channel=self._default_channel,
                        default_chat_id=self._default_chat_id
                    )
                else:
                    result = await kernel.execute(code)
            finally:
                # Restore sniffio context to prevent AsyncLibraryNotFoundError
                if original_async_lib:
                    try:
                        sniffio._impl.current_async_library_cvar.set(original_async_lib)
                    except Exception:
                        pass

            # Format output
            output_parts = []

            if result.get("stdout"):
                stdout = result["stdout"]
                if len(stdout) > self.max_output_length:
                    stdout = stdout[: self.max_output_length] + "\n... [truncated]"
                output_parts.append(f"📤 stdout:\n```\n{stdout}\n```")

            if result.get("stderr"):
                stderr = result["stderr"]
                if len(stderr) > self.max_output_length:
                    stderr = stderr[: self.max_output_length] + "\n... [truncated]"
                output_parts.append(f"⚠️ stderr:\n```\n{stderr}\n```")

            if result.get("display"):
                for display in result["display"]:
                    if display.get("type") == "image":
                        output_parts.append(f"🖼️ Image: {display.get('format', 'png')}")
                    elif display.get("type") == "html":
                        html = display.get("data", "")[:500]
                        output_parts.append(f"🌐 HTML output:\n```html\n{html}\n...\n```")
                    elif display.get("type") == "json":
                        json_str = json.dumps(display.get("data", {}), indent=2)[:500]
                        output_parts.append(f"📊 JSON output:\n```json\n{json_str}\n...\n```")

            if result.get("error"):
                error = result["error"]
                output_parts.append(f"❌ Error:\n```\n{error}\n```")

            if result.get("result") is not None and not output_parts:
                # Show the result value if no other output
                result_str = repr(result["result"])
                if len(result_str) > self.max_output_length:
                    result_str = result_str[: self.max_output_length] + "\n... [truncated]"
                output_parts.append(f"📤 Result:\n```\n{result_str}\n```")

            if not output_parts:
                return "✅ Code executed successfully (no output)"

            return "\n\n".join(output_parts)

        except Exception as e:
            logger.exception("IPython execution error")
            return f"❌ Error executing Python code: {str(e)}"

    async def _execute_thread_mode(self, code: str, session_id: str) -> str:
        """
        Execute code using thread-based IPython with message polling.
        
        This runs IPython in a separate thread to avoid async context corruption,
        while allowing blocking send_message() calls.
        """
        import asyncio
        import sniffio
        
        # Save current sniffio async library context to prevent corruption
        original_async_lib = None
        try:
            original_async_lib = sniffio.current_async_library()
        except sniffio.AsyncLibraryNotFoundError:
            pass
        
        try:
            # Start execution in a thread
            execution_thread = self._thread_manager.execute_in_thread(
                session_id=session_id,
                code=code,
                timeout=self.timeout,
            )
            
            # Poll for messages and results while thread is running
            result = None
            while execution_thread.is_alive() or result is None:
                # Check for pending messages from IPython
                messages = self._thread_manager.get_messages(session_id)
                for msg in messages:
                    if msg["type"] == "message" and self._message_callback:
                        # Send message to chat
                        try:
                            await self._message_callback(OutboundMessage(
                                channel=self._default_channel or "telegram",
                                chat_id=self._default_chat_id or "",
                                content=msg["content"],
                            ))
                            # Acknowledge successful delivery
                            self._thread_manager.acknowledge_message(session_id, success=True)
                        except Exception as e:
                            logger.error(f"Failed to send message from IPython: {e}")
                            self._thread_manager.acknowledge_message(session_id, success=False)
                
                # Check if result is available (non-blocking)
                if result is None:
                    try:
                        result_data = self._thread_manager.get_result(session_id, timeout=0.1)
                        result = result_data
                    except Exception:
                        pass
                
                # Small delay to prevent busy waiting
                await asyncio.sleep(0.05)
                
                # Restore sniffio context after each iteration to prevent AsyncLibraryNotFoundError
                if original_async_lib:
                    try:
                        sniffio._impl.current_async_library_cvar.set(original_async_lib)
                    except Exception:
                        pass
        finally:
            # Restore sniffio context to prevent AsyncLibraryNotFoundError
            if original_async_lib:
                try:
                    sniffio._impl.current_async_library_cvar.set(original_async_lib)
                except Exception:
                    pass
            
            # CRITICAL: Also restore asyncio's internal current task
            # This prevents "cannot create weak reference to 'NoneType' object" errors
            try:
                import asyncio
                current_task = asyncio.current_task()
                if current_task is None:
                    # Create a dummy task to prevent None from propagating
                    loop = asyncio.get_event_loop()
                    dummy_coro = asyncio.sleep(0)
                    dummy_task = loop.create_task(dummy_coro)
                    # Set it as current task temporarily then cancel it
                    # This is a hack but it works around the anyio issue
                    try:
                        dummy_task.cancel()
                    except:
                        pass
            except Exception:
                pass
        
        # Get final result if not already retrieved
        if result is None:
            result = self._thread_manager.get_result(session_id, timeout=5)
        
        # Format output
        if result.get("status") == "error":
            error_msg = result.get("error", "Unknown error")
            return f"❌ Error executing Python code: {error_msg}"
        
        exec_result = result.get("result", {})
        
        # Format output similar to regular mode
        output_parts = []
        
        if exec_result.get("stdout"):
            stdout = exec_result["stdout"]
            if len(stdout) > self.max_output_length:
                stdout = stdout[: self.max_output_length] + "\n... [truncated]"
            output_parts.append(f"📤 stdout:\n```\n{stdout}\n```")
        
        if exec_result.get("stderr"):
            stderr = exec_result["stderr"]
            if len(stderr) > self.max_output_length:
                stderr = stderr[: self.max_output_length] + "\n... [truncated]"
            output_parts.append(f"⚠️ stderr:\n```\n{stderr}\n```")
        
        if exec_result.get("error"):
            error = exec_result["error"]
            output_parts.append(f"❌ Error:\n```\n{error}\n```")
        
        if exec_result.get("result") is not None and not output_parts:
            result_str = repr(exec_result["result"])
            if len(result_str) > self.max_output_length:
                result_str = result_str[: self.max_output_length] + "\n... [truncated]"
            output_parts.append(f"📤 Result:\n```\n{result_str}\n```")
        
        if not output_parts:
            return "✅ Code executed successfully (no output)"
        
        return "\n\n".join(output_parts)

    async def cleanup_session(self, session_id: str) -> None:
        """Clean up a specific session's kernel."""
        if session_id in self._kernels:
            await self._kernels[session_id].shutdown()
            del self._kernels[session_id]
            logger.info(f"Cleaned up IPython kernel for session {session_id}")
    
    def update_namespace(self, session_id: str, namespace: dict[str, Any]) -> None:
        """
        Update the namespace for an embedded kernel.
        
        This allows injecting tools and callbacks into the kernel's namespace.
        Only works in embedded mode.
        """
        if session_id in self._kernels and isinstance(self._kernels[session_id], EmbeddedIPythonKernel):
            if self._kernels[session_id]._shell:
                self._kernels[session_id]._shell.user_global_ns.update(namespace)
            else:
                self._kernels[session_id]._namespace.update(namespace)
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """
        Set the default channel and chat_id for message sending.
        
        This is called by the agent loop when processing a message,
        so that IPython can send messages back to the correct destination.
        """
        self._default_channel = channel
        self._default_chat_id = chat_id
        
        # Update all existing embedded kernels
        for kernel in self._kernels.values():
            if isinstance(kernel, EmbeddedIPythonKernel):
                kernel._default_channel = channel
                kernel._default_chat_id = chat_id


class EmbeddedIPythonKernel:
    """
    In-process IPython shell for code execution.
    
    This runs in the same process as the gateway, allowing access to
    the gateway's runtime context (message bus, tools, etc.).
    """
    
    def __init__(
        self,
        working_dir: str,
        namespace: dict[str, Any] | None = None,
        message_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
    ):
        self.working_dir = working_dir
        self._namespace = namespace or {}
        self._message_callback = message_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._shell = None
        
    async def start(self) -> None:
        """Initialize the embedded IPython shell."""
        import os
        os.chdir(self.working_dir)
        
        # Apply nest_asyncio to allow nested event loops
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except ImportError:
            pass  # nest_asyncio not available, async tools may not work
        
        # Create async message helper function
        async def send_message(content: str, channel: str = "", chat_id: str = "") -> str:
            """
            Send a message to a chat channel (Telegram, Discord, etc.).
            
            Args:
                content: The message content to send.
                channel: The channel to send to (e.g., "telegram"). Uses default if not specified.
                chat_id: The chat/user ID. Uses default if not specified.
            
            Returns:
                Status message.
            """
            if not self._message_callback:
                return "❌ Message callback not configured. Cannot send messages."
            
            ch = channel or self._default_channel
            cid = chat_id or self._default_chat_id
            
            if not ch or not cid:
                return "❌ No channel/chat_id configured. Please specify channel and chat_id."
            
            msg = OutboundMessage(
                channel=ch,
                chat_id=cid,
                content=content,
            )
            await self._message_callback(msg)
            return f"✅ Message sent to {ch}:{cid}"
        
        # Inject message helper into namespace
        self._namespace["send_message"] = send_message
        
        if IPYTHON_AVAILABLE and InteractiveShell is not None:
            # Use IPython for full features (magic commands, etc.)
            self._shell = InteractiveShell.instance()
            self._shell.user_global_ns.update(self._namespace)
            self._shell.user_global_ns["__name__"] = "__main__"
        else:
            # Fallback to basic exec
            self._shell = None
            self._namespace["__name__"] = "__main__"
    
    def _contains_await(self, code: str) -> bool:
        """Check if code contains await expressions."""
        try:
            import ast
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Await):
                    return True
            return False
        except SyntaxError:
            return False
    
    async def execute(self, code: str) -> dict[str, Any]:
        """
        Execute code in the embedded shell.
        
        Returns:
            Dictionary with stdout, stderr, display outputs, errors, and result
        """
        result = {
            "stdout": "",
            "stderr": "",
            "display": [],
            "error": None,
            "result": None,
        }
        
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        # Save the current sniffio async library to restore it after execution
        # This prevents IPython/nest_asyncio from corrupting the async context
        import sniffio
        original_async_lib = None
        try:
            original_async_lib = sniffio.current_async_library()
        except sniffio.AsyncLibraryNotFoundError:
            pass
        
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                if self._shell:
                    # Use IPython shell
                    # Check if code contains await and handle it specially
                    if self._contains_await(code):
                        # Async code - execute using nest_asyncio to avoid deadlocks
                        # Don't use run_cell_async as it can deadlock in nested event loops
                        import nest_asyncio
                        nest_asyncio.apply()
                        exec_result = self._shell.run_cell(code, silent=False)
                    else:
                        # Synchronous code - use regular run_cell
                        exec_result = self._shell.run_cell(code, silent=False)
                    
                    if exec_result.result is not None:
                        result["result"] = repr(exec_result.result)
                    if exec_result.error_in_exec:
                        result["error"] = str(exec_result.error_in_exec)
                else:
                    # Fallback to basic exec
                    exec(code, self._namespace)
            
            result["stdout"] = stdout_capture.getvalue()
            result["stderr"] = stderr_capture.getvalue()
            
        except SyntaxError as e:
            result["error"] = f"SyntaxError: {e.msg} at line {e.lineno}"
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)}"
        finally:
            stdout_capture.close()
            stderr_capture.close()
            
            # Restore the sniffio async library context to prevent corruption
            # of the main event loop's async context (fixes AsyncLibraryNotFoundError)
            if original_async_lib:
                try:
                    # Set the async library back to asyncio
                    sniffio._impl.current_async_library_cvar.set(original_async_lib)
                except Exception:
                    pass
        
        return result
    
    async def shutdown(self) -> None:
        """Shutdown the embedded shell."""
        if self._shell:
            try:
                if IPYTHON_AVAILABLE and InteractiveShell is not None:
                    InteractiveShell.clear_instance()
            except Exception:
                pass
            self._shell = None


class IPythonKernel:
    """
    Wrapper around IPython kernel for code execution.

    This manages a single kernel instance with its own state.
    Supports tool calls via IPC (inter-process communication) using sockets.
    """

    def __init__(self, working_dir: str, timeout: int = 60, tool_registry=None):
        self.working_dir = working_dir
        self.timeout = timeout
        self._kernel_process: subprocess.Popen | None = None
        self._connection_file: Path | None = None
        self._client = None
        
        # IPC for tool calls
        self._tool_socket_path: Path | None = None
        self._tool_server: asyncio.AbstractServer | None = None
        self._tool_requests: asyncio.Queue | None = None
        self._tool_responses: dict[str, asyncio.Future] = {}
        
        # Cache for tool instances to avoid re-creating them
        self._tool_cache: dict[str, Tool] = {}
        
        # Store reference to tool registry (passed from parent)
        self._tool_registry = tool_registry
        
        # Cache for tool instances to avoid re-creating them
        self._tool_cache: dict[str, Tool] = {}

    def _generate_setup_code(self) -> str:
        """Generate Python setup code that injects all tool wrappers into IPython namespace."""
        # Base code for IPC communication
        base_code = f'''
import os
import json
import socket
import uuid

os.chdir(r'{self.working_dir}')

# Set up tool IPC
_tool_socket_path = os.environ.get("NANOBOT_TOOL_SOCKET")

def _call_tool(tool_name: str, **kwargs) -> str:
    """Generic tool caller via IPC to parent process."""
    if not _tool_socket_path:
        return f"❌ Tool socket not available. Cannot call {{tool_name}}."
    
    try:
        # Create request
        request_id = str(uuid.uuid4())
        request = {{
            "id": request_id,
            "tool": tool_name,
            "args": kwargs
        }}
        
        # Send request via Unix socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(_tool_socket_path)
        
        # Send message with length prefix
        msg_bytes = json.dumps(request).encode()
        sock.sendall(len(msg_bytes).to_bytes(4, 'big'))
        sock.sendall(msg_bytes)
        
        # Receive response
        response_len = int.from_bytes(sock.recv(4), 'big')
        response_bytes = b""
        while len(response_bytes) < response_len:
            chunk = sock.recv(response_len - len(response_bytes))
            if not chunk:
                raise ConnectionError("Socket closed unexpectedly")
            response_bytes += chunk
        
        response = json.loads(response_bytes.decode())
        sock.close()
        
        if response.get("success"):
            return response.get("result", "✅ Success")
        else:
            return f"❌ Error: {{response.get('error', 'Unknown error')}}"
    except Exception as e:
        return f"❌ Error calling {{tool_name}}: {{str(e)}}"

# Tool wrapper functions will be injected below
'''
        
        # Generate wrapper functions for all registered tools
        tool_wrappers = []
        if self._tool_registry:
            for tool_name in self._tool_registry.tool_names:
                tool = self._tool_registry.get(tool_name)
                if tool and tool_name != "ipython":  # Don't inject ipython tool into itself
                    # Generate wrapper function
                    wrapper = f'''
def {tool_name}(**kwargs) -> str:
    """{tool.description}"""
    return _call_tool("{tool_name}", **kwargs)
'''
                    tool_wrappers.append(wrapper)
        
        # Combine all code
        full_code = base_code + "\n".join(tool_wrappers) + '''

print("IPython kernel ready with tool support")
'''
        return full_code

    async def start(self) -> None:
        """Start the IPython kernel with IPC for tool calls."""
        try:
            # Create a temporary directory for the kernel
            kernel_dir = Path(tempfile.mkdtemp(prefix="nanobot_ipython_"))
            self._connection_file = kernel_dir / "kernel.json"
            
            # Set up IPC socket for tool calls
            self._tool_socket_path = kernel_dir / "tool_socket"
            self._tool_requests = asyncio.Queue()
            
            # Start the tool server socket
            self._tool_server = await asyncio.start_unix_server(
                self._handle_tool_request,
                path=str(self._tool_socket_path)
            )
            logger.debug(f"Tool IPC server started at {self._tool_socket_path}")

            # Start the kernel
            cmd = [
                sys.executable,
                "-m",
                "ipykernel_launcher",
                "-f",
                str(self._connection_file),
            ]

            env = os.environ.copy()
            env["PYTHONPATH"] = self.working_dir
            env["NANOBOT_TOOL_SOCKET"] = str(self._tool_socket_path)

            self._kernel_process = subprocess.Popen(
                cmd,
                cwd=self.working_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for connection file to be created
            for _ in range(50):  # 5 seconds timeout
                if self._connection_file.exists():
                    break
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Kernel failed to start")

            # Check if jupyter_client is available
            if not JUPYTER_CLIENT_AVAILABLE:
                raise ImportError(
                    "jupyter_client is required for IPython tool. "
                    "Install with: pip install jupyter-client"
                )

            # Connect to the kernel
            assert AsyncKernelClient is not None, (
                "AsyncKernelClient should not be None when JUPYTER_CLIENT_AVAILABLE is True"
            )
            self._client = AsyncKernelClient()
            self._client.load_connection_file(str(self._connection_file))

            # Wait for kernel to be ready with timeout
            try:
                await asyncio.wait_for(self._client.wait_for_ready(), timeout=10)
            except asyncio.TimeoutError:
                raise TimeoutError("Kernel failed to become ready within 10 seconds")

            # Generate setup code with all tool wrappers
            setup_code = self._generate_setup_code()
            # Execute setup silently
            msg_id = self._client.execute(setup_code, silent=True)
            # Wait for setup to complete
            for _ in range(20):  # 2 second timeout for setup
                try:
                    msg = await asyncio.wait_for(self._client.get_iopub_msg(), timeout=0.1)
                    if msg["header"]["msg_type"] == "status":
                        if msg["content"].get("execution_state") == "idle":
                            break
                except asyncio.TimeoutError:
                    continue

        except Exception as e:
            await self.shutdown()
            raise
    
    async def _handle_tool_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle incoming tool requests from the subprocess via socket."""
        request_id = "unknown"
        try:
            # Read message length
            len_bytes = await reader.read(4)
            if len(len_bytes) != 4:
                logger.error("Failed to read message length from tool socket")
                return
            
            msg_len = int.from_bytes(len_bytes, 'big')
            
            # Read message
            msg_bytes = await reader.read(msg_len)
            if len(msg_bytes) != msg_len:
                logger.error(f"Incomplete message: got {len(msg_bytes)} bytes, expected {msg_len}")
                return
            
            request = json.loads(msg_bytes.decode())
            request_id = request.get("id", str(uuid.uuid4()))
            tool_name = request.get("tool")
            args = request.get("args", {})
            
            # Execute the tool and get result
            result = await self._execute_tool(tool_name, args)
            
            # Send response back to subprocess
            response = {
                "id": request_id,
                "success": result.get("success", False),
                "result": result.get("result"),
                "error": result.get("error")
            }
            response_bytes = json.dumps(response).encode()
            writer.write(len(response_bytes).to_bytes(4, 'big'))
            writer.write(response_bytes)
            await writer.drain()
            
        except Exception as e:
            logger.error(f"Error handling tool request: {e}")
            # Send error response
            try:
                response = {"id": request_id, "success": False, "error": str(e)}
                response_bytes = json.dumps(response).encode()
                writer.write(len(response_bytes).to_bytes(4, 'big'))
                writer.write(response_bytes)
                await writer.drain()
            except:
                pass
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def _execute_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return the result."""
        try:
            # Check if tool registry is available
            if not self._tool_registry:
                return {"success": False, "error": f"Tool registry not available"}
            
            # Check if we have the tool cached
            if tool_name not in self._tool_cache:
                tool = self._tool_registry.get(tool_name)
                if not tool:
                    return {"success": False, "error": f"Tool '{tool_name}' not found"}
                self._tool_cache[tool_name] = tool
            
            tool = self._tool_cache[tool_name]
            
            # Validate parameters
            errors = tool.validate_params(args)
            if errors:
                return {"success": False, "error": f"Invalid parameters: {'; '.join(errors)}"}
            
            # Execute the tool
            result = await tool.execute(**args)
            return {"success": True, "result": result}
            
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return {"success": False, "error": str(e)}

    async def execute(
        self, 
        code: str, 
        message_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = ""
    ) -> dict[str, Any]:
        """
        Execute code in the kernel.
        
        Args:
            code: Python code to execute
            message_callback: Callback for sending messages (for handling tool calls)
            default_channel: Default channel for messages
            default_chat_id: Default chat ID for messages

        Returns:
            Dictionary with stdout, stderr, display outputs, errors, and result
        """
        if not self._client:
            raise RuntimeError("Kernel not started")

        result = {
            "stdout": "",
            "stderr": "",
            "display": [],
            "error": None,
            "result": None,
        }

        try:
            # Execute the code
            msg_id = self._client.execute(code)
            execution_complete = False
            start_time = time.monotonic()
            
            # Collect output and handle tool requests
            while not execution_complete:
                # Check global timeout
                elapsed = time.monotonic() - start_time
                if elapsed > self.timeout:
                    logger.error(f"[IPYTHON-TIMEOUT] TIMEOUT REACHED: {elapsed:.1f}s > {self.timeout}s, aborting!")
                    result["error"] = f"Execution timeout after {self.timeout}s"
                    return result
                
                # Try to get IOPub message with timeout
                try:
                    msg = await asyncio.wait_for(
                        self._client.get_iopub_msg(), 
                        timeout=0.5
                    )
                    
                    msg_type = msg["header"]["msg_type"]
                    content = msg["content"]

                    if msg_type == "stream":
                        if content.get("name") == "stdout":
                            result["stdout"] += content.get("text", "")
                        elif content.get("name") == "stderr":
                            result["stderr"] += content.get("text", "")

                    elif msg_type in ("display_data", "execute_result"):
                        data = content.get("data", {})

                        # Handle images
                        if "image/png" in data:
                            import base64
                            img_data = base64.b64decode(data["image/png"])
                            result["display"].append({"type": "image", "format": "png", "data": img_data})
                        elif "image/jpeg" in data:
                            import base64
                            img_data = base64.b64decode(data["image/jpeg"])
                            result["display"].append({"type": "image", "format": "jpeg", "data": img_data})
                        # Handle HTML
                        elif "text/html" in data:
                            result["display"].append({"type": "html", "data": data["text/html"]})
                        # Handle JSON
                        elif "application/json" in data:
                            result["display"].append({"type": "json", "data": data["application/json"]})
                        # Handle plain text (result value)
                        elif "text/plain" in data:
                            result["result"] = data["text/plain"]

                    elif msg_type == "error":
                        result["error"] = "\n".join(content.get("traceback", []))

                    elif msg_type == "status":
                        if content.get("execution_state") == "idle":
                            # Check if this status is for our execution
                            parent_msg_id = msg.get("parent_header", {}).get("msg_id")
                            if parent_msg_id == msg_id:
                                execution_complete = True
                                
                except asyncio.TimeoutError:
                    # No message received, check for tool requests and continue
                    if self._tool_requests:
                        try:
                            request = self._tool_requests.get_nowait()
                            if request and message_callback:
                                await self._handle_tool_call(
                                    request, 
                                    message_callback, 
                                    default_channel, 
                                    default_chat_id
                                )
                        except asyncio.QueueEmpty:
                            pass
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    continue
            
            return result

        except Exception as e:
            result["error"] = str(e)
            return result
    
    async def _handle_tool_call(
        self, 
        request: dict, 
        message_callback: Callable[[OutboundMessage], Awaitable[None]],
        default_channel: str,
        default_chat_id: str
    ) -> None:
        """Handle a tool call request from the subprocess."""
        tool_name = request.get("tool")
        args = request.get("args", {})
        request_id = request.get("id", "unknown")
        
        try:
            if tool_name == "send_message":
                content = args.get("content", "")
                channel = args.get("channel") or default_channel
                chat_id = args.get("chat_id") or default_chat_id
                
                if not channel or not chat_id:
                    logger.error("Cannot send message: no channel or chat_id configured")
                    return
                
                msg = OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=content,
                )
                await message_callback(msg)
                logger.debug(f"Tool call send_message executed: {request_id}")
            else:
                logger.warning(f"Unknown tool call: {tool_name}")
        except Exception as e:
            logger.error(f"Error handling tool call {tool_name}: {e}")

    async def shutdown(self) -> None:
        """Shutdown the kernel."""
        # Close tool server
        if self._tool_server:
            try:
                self._tool_server.close()
                await self._tool_server.wait_closed()
            except Exception as e:
                logger.warning(f"Failed to close tool server: {e}")
            self._tool_server = None
        
        if self._client:
            try:
                self._client.shutdown()
            except Exception as e:
                logger.warning(f"Failed to shutdown kernel client: {e}")
            self._client = None

        if self._kernel_process:
            try:
                self._kernel_process.terminate()
                await asyncio.sleep(0.5)
                if self._kernel_process.poll() is None:
                    self._kernel_process.kill()
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.warning(f"Failed to terminate kernel process: {e}")
            self._kernel_process = None

        # Clean up connection file
        if self._connection_file and self._connection_file.exists():
            try:
                import shutil

                shutil.rmtree(self._connection_file.parent)
            except Exception as e:
                logger.warning(f"Failed to clean up connection file: {e}")