"""Lightweight project retrieval for prompt grounding."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


@dataclass(slots=True)
class RetrievalChunk:
    path: str
    text: str
    tokens: set[str]


class ProjectRetriever:
    """Simple lexical retriever over project docs (RAG-light)."""

    DEFAULT_PATTERNS = (
        "README*",
        "NOTES*",
        "HISTORY*",
        "memory/MEMORY.md",
        "memory/HISTORY.md",
        "docs/**/*.md",
    )

    def __init__(
        self,
        workspace: Path,
        *,
        patterns: tuple[str, ...] | None = None,
        chunk_size: int = 900,
        refresh_interval_s: int = 30,
    ) -> None:
        self.workspace = workspace
        self.patterns = patterns or self.DEFAULT_PATTERNS
        self.chunk_size = max(chunk_size, 256)
        self.refresh_interval_s = max(refresh_interval_s, 5)
        self._last_refresh = 0.0
        self._chunks: list[RetrievalChunk] = []

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}

    def _iter_files(self) -> list[Path]:
        seen: set[Path] = set()
        files: list[Path] = []
        for pattern in self.patterns:
            for p in self.workspace.glob(pattern):
                if p.is_file() and p not in seen:
                    seen.add(p)
                    files.append(p)
        return files

    def _chunk_text(self, text: str) -> list[str]:
        parts = re.split(r"\n\s*\n", text)
        chunks: list[str] = []
        buf = ""
        for part in parts:
            part = part.strip()
            if not part:
                continue
            candidate = f"{buf}\n\n{part}".strip() if buf else part
            if len(candidate) <= self.chunk_size:
                buf = candidate
                continue
            if buf:
                chunks.append(buf)
            if len(part) <= self.chunk_size:
                buf = part
            else:
                for i in range(0, len(part), self.chunk_size):
                    chunks.append(part[i: i + self.chunk_size])
                buf = ""
        if buf:
            chunks.append(buf)
        return chunks

    def refresh(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_refresh) < self.refresh_interval_s:
            return

        new_chunks: list[RetrievalChunk] = []
        for file_path in self._iter_files():
            try:
                raw = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for chunk in self._chunk_text(raw):
                tokens = self._tokenize(chunk)
                if not tokens:
                    continue
                try:
                    rel = str(file_path.relative_to(self.workspace))
                except Exception:
                    rel = str(file_path)
                new_chunks.append(RetrievalChunk(path=rel, text=chunk, tokens=tokens))
        self._chunks = new_chunks
        self._last_refresh = now

    def search(self, query: str, *, max_chunks: int = 3, max_chars: int = 1800) -> list[tuple[str, str]]:
        self.refresh()
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []

        scored: list[tuple[int, RetrievalChunk]] = []
        for chunk in self._chunks:
            overlap = len(q_tokens & chunk.tokens)
            if overlap <= 0:
                continue
            scored.append((overlap, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)

        out: list[tuple[str, str]] = []
        used = 0
        for _, chunk in scored[: max(max_chunks * 3, max_chunks)]:
            if len(out) >= max_chunks:
                break
            snippet = chunk.text.strip()
            if not snippet:
                continue
            room = max_chars - used
            if room <= 80:
                break
            if len(snippet) > room:
                snippet = snippet[:room].rstrip() + " ..."
            out.append((chunk.path, snippet))
            used += len(snippet)
        return out

