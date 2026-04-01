"""PDF tool for reading and inspecting PDF documents."""

import json
from typing import Any

from nanobot.agent.tools.base import Tool


class PdfTool(Tool):
    """Tool to read PDF files and extract text content."""

    @property
    def name(self) -> str:
        return "pdf"

    @property
    def description(self) -> str:
        return (
            "Read PDF files. Extract text content or get metadata/page count. "
            "Use this when you receive a PDF document and need to read its contents."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the PDF file",
                },
                "command": {
                    "type": "string",
                    "enum": ["read", "info"],
                    "description": "read: extract text; info: page count and metadata",
                    "default": "read",
                },
                "pages": {
                    "type": "string",
                    "description": "Page range to read, e.g. '1-3' or '2'. Default: all pages",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, command: str = "read", pages: str | None = None, **kwargs: Any) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            return "Error: pypdf not installed. Run: pip install pypdf"

        try:
            reader = PdfReader(path)
        except Exception as e:
            return f"Error reading PDF: {e}"

        total = len(reader.pages)

        if command == "info":
            meta = {}
            if reader.metadata:
                for key in ("/Title", "/Author", "/Subject", "/Creator", "/Producer"):
                    val = reader.metadata.get(key)
                    if val:
                        meta[key.lstrip("/")] = str(val)
            return json.dumps({"pages": total, "metadata": meta}, ensure_ascii=False)

        # Parse page range
        page_indices = self._parse_pages(pages, total)

        parts = []
        for i in page_indices:
            text = reader.pages[i].extract_text() or ""
            if text.strip():
                parts.append(f"--- Page {i + 1} ---\n{text.strip()}")

        if not parts:
            return f"PDF has {total} pages but no extractable text (may be scanned/image-based)."

        return "\n\n".join(parts)

    @staticmethod
    def _parse_pages(pages: str | None, total: int) -> list[int]:
        """Parse page range string into 0-based indices."""
        if not pages:
            return list(range(total))

        indices = []
        for part in pages.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                s = max(int(start) - 1, 0)
                e = min(int(end), total)
                indices.extend(range(s, e))
            else:
                idx = int(part) - 1
                if 0 <= idx < total:
                    indices.append(idx)
        return indices or list(range(total))
