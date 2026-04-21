"""Recall and ingest tools backed by the RAG semantic store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

_SUPPORTED_SUFFIXES = {
    ".md", ".txt", ".py", ".json",
    ".pdf", ".docx", ".doc",
    ".csv", ".html", ".htm", ".xml",
    ".yaml", ".yml", ".rst", ".log",
}


class RecallTool(Tool):
    """Semantic search across RAG collections (conversations, documents, knowledge)."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._rag: Any = None  # lazy: nanobot.agent.rag.RAGStore

    def _get_rag(self):
        if self._rag is None:
            from nanobot.agent.rag import RAGStore
            self._rag = RAGStore(self._workspace)
        return self._rag

    @property
    def name(self) -> str:
        return "recall"

    @property
    def description(self) -> str:
        return (
            "Semantic search over long-term memory: past conversations, ingested documents, "
            "and extracted knowledge facts. Use this to find things like 'what did we discuss "
            "about GPUs last week?' or 'find notes about deployment'. "
            "Scope can be 'all', 'conversations', 'documents', or 'knowledge'."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["all", "conversations", "documents", "knowledge"],
                    "description": (
                        "Which collection to search. "
                        "'all' searches everywhere (default). "
                        "'conversations' finds past chat segments. "
                        "'documents' searches ingested files. "
                        "'knowledge' searches extracted facts."
                    ),
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 20).",
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        scope: str = "all",
        n_results: int = 5,
        **kwargs: Any,
    ) -> str:
        try:
            rag = self._get_rag()
        except RuntimeError as exc:
            return f"Error: {exc}"

        valid_scopes = {"all", "conversations", "documents", "knowledge"}
        if scope not in valid_scopes:
            return f"Error: invalid scope '{scope}'. Must be one of: {', '.join(sorted(valid_scopes))}"

        collection = None if scope == "all" else scope
        n = min(max(n_results, 1), 20)

        try:
            results = rag.search(query=query, n_results=n, collection=collection)
        except Exception as exc:
            logger.exception("recall tool: search failed")
            return f"Error performing semantic search: {exc}"

        if not results:
            return f"No results found for: {query!r} (scope={scope})"

        lines = [f"Semantic recall: {len(results)} result(s) for {query!r} (scope={scope})\n"]
        for i, r in enumerate(results, 1):
            meta = r.get("metadata", {})
            coll = r.get("collection", "?")
            dist = r.get("distance", 0.0)
            content = r.get("content", "")

            # Build a compact metadata summary for the agent.
            meta_parts: list[str] = [f"collection={coll}"]
            if ts := meta.get("timestamp", "")[:16]:
                meta_parts.append(f"time={ts}")
            if src := meta.get("source") or meta.get("path") or meta.get("session_id"):
                meta_parts.append(f"source={src}")
            meta_parts.append(f"similarity={1 - dist:.2f}")

            lines.append(f"[{i}] {' | '.join(meta_parts)}")
            # Indent content for readability.
            for content_line in content.splitlines():
                lines.append(f"    {content_line}")
            lines.append("")

        return "\n".join(lines).rstrip()


class IngestTool(Tool):
    """Ingest a file or directory into the RAG semantic store."""

    def __init__(self, workspace: Path, allowed_dir: Path | None = None) -> None:
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        self._rag: Any = None  # lazy: nanobot.agent.rag.RAGStore

    def _get_rag(self):
        if self._rag is None:
            from nanobot.agent.rag import RAGStore
            self._rag = RAGStore(self._workspace)
        return self._rag

    @property
    def name(self) -> str:
        return "ingest"

    @property
    def description(self) -> str:
        return (
            "Ingest a file or directory into the RAG semantic store so its contents "
            "can be found later via the recall tool. "
            f"Supported file types: {', '.join(sorted(_SUPPORTED_SUFFIXES))}. "
            "For directories, all matching files are ingested recursively."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path to a file or directory.",
                },
                "glob": {
                    "type": "string",
                    "description": (
                        "Glob pattern for directory ingestion (default '**/*.md'). "
                        "Only used when path is a directory."
                    ),
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, glob: str = "**/*.md", **kwargs: Any) -> str:
        try:
            rag = self._get_rag()
        except RuntimeError as exc:
            return f"Error: {exc}"

        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self._workspace / target
        target = target.resolve()

        if self._allowed_dir is not None:
            allowed = self._allowed_dir.resolve()
            try:
                target.relative_to(allowed)
            except ValueError:
                return f"Error: path {path} is outside the allowed directory ({allowed})"

        if not target.exists():
            return f"Error: path does not exist: {path}"

        try:
            if target.is_dir():
                count = rag.ingest_directory(target, glob=glob)
                return (
                    f"Ingested {count} file(s) from {target} into the RAG store. "
                    "Use recall to search the content."
                )

            # Single file.
            if target.suffix not in _SUPPORTED_SUFFIXES:
                return (
                    f"Error: unsupported file type '{target.suffix}'. "
                    f"Supported: {', '.join(sorted(_SUPPORTED_SUFFIXES))}"
                )

            # --- Extract text based on file type ---
            suffix = target.suffix.lower()

            if suffix == ".pdf":
                try:
                    import pdfplumber
                except ImportError:
                    return (
                        "Error: pdfplumber is not installed. "
                        "Run: pip install pdfplumber"
                    )
                pages_text: list[str] = []
                with pdfplumber.open(target) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            pages_text.append(page_text)
                content = "\n\n".join(pages_text)

            elif suffix in (".docx", ".doc"):
                try:
                    import docx as python_docx
                except ImportError:
                    return (
                        "Error: python-docx is not installed. "
                        "Run: pip install python-docx"
                    )
                doc = python_docx.Document(str(target))
                content = "\n\n".join(
                    para.text for para in doc.paragraphs if para.text.strip()
                )

            elif suffix == ".csv":
                content = target.read_text(encoding="utf-8", errors="replace")

            else:
                # All other text-based formats (.md, .txt, .py, .json,
                # .html, .htm, .xml, .yaml, .yml, .rst, .log)
                content = target.read_text(encoding="utf-8", errors="replace")

            if not content.strip():
                return f"Warning: file {path} is empty, nothing ingested."

            rag.add_document(
                path=str(target),
                content=content,
                metadata={"source": "manual_ingest", "filename": target.name},
            )
            return (
                f"Ingested {target.name} ({len(content)} chars, "
                f"{len(content.split())} words) into the RAG store. "
                "Use recall to search the content."
            )
        except Exception as exc:
            logger.exception("ingest tool: failed for {}", path)
            return f"Error ingesting {path}: {exc}"
