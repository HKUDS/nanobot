"""Trace capture for agent execution."""

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import re
from loguru import logger

from nanobot.config.schema import TraceConfig


class TraceWriter:
    """Writes structured execution traces to JSON files."""

    def __init__(
        self,
        workspace: Path,
        config: TraceConfig,
        session_id: str = "unknown",
        model: str = "unknown",
    ):
        self.workspace = workspace
        self.config = config
        self.session_id = str(session_id)
        self.model = str(model)
        self.start_time = time.time()
        self.iterations: list[dict[str, Any]] = []
        self.trace_file: Path | None = None
        
        # Redaction patterns
        self._redact_patterns = [
            (r'sk-[a-zA-Z0-9\-_]{20,}', '[REDACTED_SECRET]'),
            (r'Bearer\s+[a-zA-Z0-9\-_]+', 'Bearer [REDACTED_TOKEN]'),
            (r'Authorization:\s+\S+', 'Authorization: [REDACTED]'),
            (r'(?i)api[-_]?key\s*[:=]\s*[\"\']?\S+[\"\']?', 'api_key: [REDACTED]'),
        ]

    def _redact(self, text: str | None) -> str | None:
        """Redact sensitive keys from text."""
        if not text:
            return text
        
        redacted = text
        for pattern, replacement in self._redact_patterns:
            redacted = re.sub(pattern, replacement, redacted)
        return redacted

    def _digest(self, data: Any) -> str:
        """Compute stable SHA256 digest of data."""
        try:
            s = json.dumps(data, sort_keys=True, default=str)
            return "sha256:" + hashlib.sha256(s.encode()).hexdigest()[:16]
        except Exception:
            return "sha256:error"

    def _preview(self, text: str | None, limit: int | None = None) -> str | None:
        """Create a safe preview of text."""
        if text is None:
            return None
        
        text = self._redact(text) or ""
        limit = limit or self.config.llm_preview_chars
        
        if len(text) <= limit:
            return text
        
        head = limit // 2
        tail = limit - head
        # Ensure we don't overlap if text is somehow shorter than limit (guarded above, but safe)
        return f"{text[:head]}...[{len(text)} chars]...{text[-tail:]}"

    def log_iteration_start(self, i: int, messages: list[dict]) -> None:
        """Log the start of an iteration."""
        # Simple digest of message content
        # We don't want to digest the whole message object if it contains large non-content fields
        content_for_digest = [m.get("content", "") for m in messages]
        prompt_digest = self._digest(content_for_digest)
        
        entry = {
            "i": i,
            "prompt_digest": prompt_digest,
            "timestamp": time.time(),
        }
        
        if self.config.capture_prompt:
            entry["prompt"] = [
                {k: self._redact(str(v)) for k, v in m.items() if k in ("role", "content")}
                for m in messages
            ]
        
        self.iterations.append(entry)

    def log_llm_response(self, content: str | None, tool_calls: list[Any]) -> None:
        """Log the LLM response."""
        if not self.iterations:
            return

        current = self.iterations[-1]
        
        tcs = []
        for tc in tool_calls:
            try:
                args = tc.arguments
                # Redact args if needed? Ideally yes, but tricky structure.
                # Assuming args are generally safe or specific values.
                # For safety, let's dump and redact the JSON string of arguments
                args_str = json.dumps(args)
                redacted_args = json.loads(self._redact(args_str) or "{}")
                
                tcs.append({
                    "name": tc.name,
                    "args": redacted_args
                })
            except Exception:
                tcs.append({"name": tc.name, "error": "failed_to_parse_args"})

        current["llm"] = {
            "content_preview": self._preview(content),
            "tool_calls": tcs,
        }

    def log_tool_execution(self, name: str, args: dict, result: str) -> None:
        """Log a tool execution result."""
        if not self.iterations:
            return

        current = self.iterations[-1]
        if "tools" not in current:
            current["tools"] = []
        
        result_len = len(result) if result else 0
        result_digest = self._digest(result)
        
        # Redact args for the log entry
        args_str = json.dumps(args)
        redacted_args = json.loads(self._redact(args_str) or "{}")

        tool_entry = {
            "name": name,
            "args": redacted_args,
            "result_digest": result_digest,
        }

        # Artifact spooling logic
        if result_len > self.config.max_inline_chars:
            artifacts_dir = self.workspace / "artifacts"
            try:
                if not artifacts_dir.exists():
                     artifacts_dir.mkdir(parents=True, exist_ok=True)
                
                ts = int(time.time() * 1000)
                # sanitize tool name
                safe_name = "".join(c for c in name if c.isalnum() or c in "_-")
                filename = f"{ts}_{safe_name}.txt"
                
                path = artifacts_dir / filename
                path.write_text(result, encoding="utf-8")
                
                # Relative path
                tool_entry["artifact_path"] = f"artifacts/{filename}"
                tool_entry["result_preview"] = self._preview(result, limit=self.config.llm_preview_chars) # Use smaller preview for reference
            except Exception as e:
                logger.warning(f"Failed to spool artifact: {e}")
                tool_entry["error"] = f"Spool failed: {e}"
                tool_entry["result_preview"] = self._preview(result, limit=self.config.max_inline_chars)
        else:
            tool_entry["result_preview"] = self._preview(result)

        current["tools"].append(tool_entry)

    def close(self, end_type: str, final_content: str | None = None) -> None:
        """Finalize and write the trace file."""
        trace_dir = self.workspace / self.config.dir
        try:
            if not trace_dir.exists():
                trace_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create trace dir {trace_dir}: {e}")
            return

        duration = round(time.time() - self.start_time, 2)
        
        trace_data = {
            "meta": {
                "version": "1.0",
                "timestamp": datetime.now().isoformat(),
                "session_id": self.session_id,
                "model": self.model,
                "duration_s": duration,
            },
            "iterations": self.iterations,
            "termination": {
                "type": end_type,
            }
        }
        
        preview = self._preview(final_content)
        if end_type == "error":
            trace_data["termination"]["error"] = preview
        else:
            trace_data["termination"]["final_answer"] = preview

        # Filename: {timestamp}_{session_id}.json
        # Format timestamp safely
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_sess = "".join(c for c in self.session_id if c.isalnum() or c in "-")
        filename = f"{ts_str}_{safe_sess}.json"
        
        self.trace_file = trace_dir / filename
        
        try:
            with open(self.trace_file, "w", encoding="utf-8") as f:
                json.dump(trace_data, f, indent=2, sort_keys=False)
            logger.info(f"Trace captured: {self.trace_file}")
        except Exception as e:
            logger.error(f"Failed to write trace to {self.trace_file}: {e}")
