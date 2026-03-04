"""Feishu document tool (feishu_doc)."""
import json
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.feishu.client import get_feishu_client
from nanobot.config.schema import FeishuConfig


class FeishuDocTool(Tool):
    """Read and write Feishu documents (docx)."""

    def __init__(self, cfg: FeishuConfig):
        self._cfg = cfg

    @property
    def name(self) -> str:
        return "feishu_doc"

    @property
    def description(self) -> str:
        return (
            "Feishu document operations. "
            "Actions: read (get full text), create (create blank doc), "
            "create_and_write (create + write markdown content). "
            "doc_id is the document token from the URL."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "create", "create_and_write"],
                    "description": "Operation to perform",
                },
                "doc_id": {
                    "type": "string",
                    "description": "Document token (required for read)",
                },
                "title": {
                    "type": "string",
                    "description": "Document title (for create/create_and_write)",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content to write (for create_and_write)",
                },
                "folder_token": {
                    "type": "string",
                    "description": "Parent folder token (optional, for create)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, doc_id: str = "", title: str = "",
                      content: str = "", folder_token: str = "", **kwargs: Any) -> str:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run, action, doc_id, title, content, folder_token)

    def _run(self, action: str, doc_id: str, title: str, content: str, folder_token: str) -> str:
        client = get_feishu_client(self._cfg)
        try:
            if action == "read":
                if not doc_id:
                    return "Error: doc_id required for read"
                resp = client.docx.v1.document.raw_content(
                    document_id=doc_id,
                    lang=0,
                )
                if not resp.success():
                    return f"Error: {resp.code} {resp.msg}"
                return resp.data.content or "(empty document)"

            elif action == "create":
                body = {"title": title or "Untitled"}
                if folder_token:
                    body["folder_token"] = folder_token
                resp = client.docx.v1.document.create(request_body=body)
                if not resp.success():
                    return f"Error: {resp.code} {resp.msg}"
                new_id = resp.data.document.document_id
                return json.dumps({"doc_id": new_id})

            elif action == "create_and_write":
                body = {"title": title or "Untitled"}
                if folder_token:
                    body["folder_token"] = folder_token
                resp = client.docx.v1.document.create(request_body=body)
                if not resp.success():
                    return f"Error creating doc: {resp.code} {resp.msg}"
                new_id = resp.data.document.document_id
                return json.dumps({"doc_id": new_id, "note": "content writing not yet supported via API"})

            else:
                return f"Error: unknown action '{action}'"
        except Exception as e:
            return f"Error: {e}"
