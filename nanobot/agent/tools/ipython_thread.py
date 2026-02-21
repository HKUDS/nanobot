"""Thread-based IPython kernel with blocking send_message support."""

import threading
import queue
import json
import sys
import traceback
import multiprocessing
import time
from typing import Any, Callable, Optional
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from loguru import logger

# Optional IPython import
try:
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.core.magic import register_line_magic
    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False
    InteractiveShell = None


class ThreadIPythonKernel:
    """
    IPython kernel that runs in a separate thread with blocking message support.
    
    This allows send_message() to block until the main thread confirms delivery,
    while keeping IPython isolated from the main async event loop.
    """
    
    def __init__(
        self,
        working_dir: str,
        session_id: str,
        max_output_length: int = 10000,
        message_queue: Optional[queue.Queue] = None,
        response_queue: Optional[queue.Queue] = None,
        namespace: Optional[dict] = None,
    ):
        self.working_dir = working_dir
        self.session_id = session_id
        self.max_output_length = max_output_length
        self.message_queue = message_queue or queue.Queue(maxsize=100)  # Drop when full
        self.response_queue = response_queue or queue.Queue()
        self.namespace = namespace or {}
        
        self.shell: Any = None
        self._initialized = False
        
    def initialize(self) -> None:
        """Initialize the IPython shell in the current thread."""
        if not IPYTHON_AVAILABLE or InteractiveShell is None:
            raise RuntimeError("IPython not available")
            
        # Create IPython shell
        self.shell = InteractiveShell.instance()
        
        # Change to working directory
        import os
        os.chdir(self.working_dir)
        
        # Inject namespace
        if self.shell is not None:
            for key, value in self.namespace.items():
                self.shell.user_ns[key] = value
                
            # Inject send_message function
            self.shell.user_ns['send_message'] = self._create_send_message()
        
        self._initialized = True
        logger.info(f"ThreadIPythonKernel initialized for session {self.session_id}")
        
    def _create_send_message(self) -> Callable[[str, int], bool]:
        """Create a send_message function that blocks until delivery confirmed."""
        def send_message(content: str, timeout: int = 30) -> bool:
            """
            Send a message to the chat. Blocks until delivery is confirmed.
            
            Args:
                content: Message content to send
                timeout: Maximum seconds to wait for delivery confirmation
                
            Returns:
                True if message was sent successfully, False if timed out or failed
            """
            try:
                # Try to put message in queue (drop oldest if full)
                msg = {
                    "type": "message",
                    "content": content,
                    "session_id": self.session_id,
                }
                
                # Non-blocking put with drop-on-full behavior
                try:
                    self.message_queue.put_nowait(msg)
                except queue.Full:
                    # Drop oldest message and try again
                    try:
                        self.message_queue.get_nowait()
                        self.message_queue.put_nowait(msg)
                    except queue.Empty:
                        pass  # Queue was emptied between get and put
                    
                # Block waiting for acknowledgment from main thread
                try:
                    ack = self.response_queue.get(timeout=timeout)
                    return ack.get("success", False)
                except queue.Empty:
                    logger.warning(f"send_message timeout for session {self.session_id}")
                    return False
                    
            except Exception as e:
                logger.error(f"send_message error: {e}")
                return False
                
        return send_message
        
    def execute(self, code: str, timeout: Optional[int] = None) -> dict[str, Any]:
        """
        Execute Python code and capture output.
        
        Args:
            code: Python code to execute
            timeout: Maximum execution time in seconds (None for no limit)
            
        Returns:
            Dict with stdout, stderr, error, result, display outputs
        """
        if not self._initialized:
            self.initialize()
            
        result = {
            "stdout": "",
            "stderr": "",
            "error": None,
            "result": None,
            "display": [],
        }
        
        # Capture stdout/stderr
        stdout_buffer = StringIO()
        stderr_buffer = StringIO()
        
        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                # Execute the code
                exec_result = self.shell.run_cell(code, silent=False)
                
            # Get captured output
            result["stdout"] = stdout_buffer.getvalue()
            result["stderr"] = stderr_buffer.getvalue()
            
            # Check for execution success
            if exec_result.success:
                # Get the result (last expression value)
                if exec_result.result is not None:
                    result["result"] = exec_result.result
            else:
                # Execution failed
                if exec_result.error_before_exec:
                    result["error"] = str(exec_result.error_before_exec)
                elif exec_result.error_in_exec:
                    result["error"] = str(exec_result.error_in_exec)
                else:
                    result["error"] = "Unknown execution error"
                    
        except Exception as e:
            result["error"] = f"Exception during execution: {str(e)}\n{traceback.format_exc()}"
            result["stderr"] = stderr_buffer.getvalue()
            
        finally:
            stdout_buffer.close()
            stderr_buffer.close()
            
        return result
        
    def shutdown(self) -> None:
        """Shutdown the kernel and cleanup."""
        if self.shell is not None:
            # Clear namespace
            if hasattr(self.shell, 'user_ns'):
                self.shell.user_ns.clear()
            # Get rid of the shell instance
            if InteractiveShell is not None and hasattr(InteractiveShell, 'clear_instance'):
                InteractiveShell.clear_instance()
            self.shell = None
            
        self._initialized = False
        logger.info(f"ThreadIPythonKernel shutdown for session {self.session_id}")


class ThreadIPythonManager:
    """
    Manages multiple thread-based IPython kernels (one per session).
    """
    
    def __init__(
        self,
        working_dir: str,
        max_output_length: int = 10000,
        message_callback: Optional[Callable[[str, str, str], Any]] = None,
    ):
        self.working_dir = working_dir
        self.max_output_length = max_output_length
        self._message_callback = message_callback
        self._kernels: dict[str, ThreadIPythonKernel] = {}
        self._kernel_threads: dict[str, threading.Thread] = {}
        self._results_queues: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()
        
    def create_kernel(
        self,
        session_id: str,
        namespace: Optional[dict] = None,
    ) -> ThreadIPythonKernel:
        """Create a new kernel for a session."""
        with self._lock:
            if session_id in self._kernels:
                # Reuse existing kernel
                return self._kernels[session_id]
                
            kernel = ThreadIPythonKernel(
                working_dir=self.working_dir,
                session_id=session_id,
                max_output_length=self.max_output_length,
                namespace=namespace or {},
            )
            
            self._kernels[session_id] = kernel
            return kernel
            
    def execute_in_thread(
        self,
        session_id: str,
        code: str,
        timeout: int = 300,
    ) -> threading.Thread:
        """
        Start code execution in a thread and return the thread object.
        
        The result will be available via get_result().
        """
        kernel = self.create_kernel(session_id)
        result_queue = queue.Queue()
        self._results_queues[session_id] = result_queue
        
        def run_execution():
            try:
                result = kernel.execute(code, timeout=timeout)
                result_queue.put({"status": "success", "result": result})
            except Exception as e:
                result_queue.put({
                    "status": "error",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
                
        thread = threading.Thread(target=run_execution, daemon=True)
        thread.start()
        self._kernel_threads[session_id] = thread
        
        return thread
        
    def get_result(self, session_id: str, timeout: Optional[int] = None) -> dict:
        """Get the result of execution (blocks until available)."""
        result_queue = self._results_queues.get(session_id)
        if not result_queue:
            return {"status": "error", "error": "No execution pending for session"}
            
        try:
            return result_queue.get(timeout=timeout)
        except queue.Empty:
            return {"status": "timeout", "error": "Execution timed out"}
            
    def get_messages(self, session_id: str) -> list[dict]:
        """Get all pending messages from a kernel (non-blocking)."""
        kernel = self._kernels.get(session_id)
        if not kernel:
            return []
            
        messages = []
        while True:
            try:
                msg = kernel.message_queue.get_nowait()
                messages.append(msg)
            except queue.Empty:
                break
                
        return messages
        
    def acknowledge_message(self, session_id: str, success: bool = True) -> None:
        """Acknowledge a message delivery to unblock send_message()."""
        kernel = self._kernels.get(session_id)
        if kernel:
            try:
                kernel.response_queue.put_nowait({"success": success})
            except queue.Full:
                pass  # Response queue is full, message caller will timeout
                
    def cleanup_session(self, session_id: str) -> None:
        """Cleanup a session's kernel."""
        with self._lock:
            kernel = self._kernels.pop(session_id, None)
            if kernel:
                kernel.shutdown()
                
            self._kernel_threads.pop(session_id, None)
            self._results_queues.pop(session_id, None)
            
    def cleanup_all(self) -> None:
        """Cleanup all kernels."""
        with self._lock:
            session_ids = list(self._kernels.keys())
            for session_id in session_ids:
                self.cleanup_session(session_id)
