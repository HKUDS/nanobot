"""Memory system with search for persistent agent memory."""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir, today_date

# Section header to category mapping
CATEGORY_SECTIONS: dict[str, str] = {
    "preference": "## Preferences",
    "fact": "## User",
    "project": "## Projects",
    "decision": "## Decisions",
}

# Patterns that look like prompt injection attempts
_INJECTION_PATTERNS = re.compile(
    r"(?i)(?:##\s*system|<\|im_start\|>|\[INST\]|\[/INST\]|<\|endoftext\|>|<\|assistant\|>)",
)


@dataclass
class Chunk:
    """A searchable unit of memory content."""
    text: str
    path: str
    start_line: int
    end_line: int
    section: str = ""
    hash: str = ""


@dataclass
class SearchResult:
    """A memory search result."""
    text: str
    path: str
    start_line: int
    end_line: int
    score: float
    section: str = ""


@dataclass
class DedupResult:
    """Result of a deduplication check."""
    action: str  # "add", "update", or "noop"
    text: str  # The (possibly revised) text to write
    update_target: str = ""  # Existing entry to replace (for "update")
    reason: str = ""  # Why this action was chosen


class MemoryStore:
    """
    Memory system with keyword and embedding search.

    Supports daily notes (memory/YYYY-MM-DD.md) and long-term memory (MEMORY.md).
    Search uses keyword matching for small stores and embedding for large ones.
    """

    def __init__(self, workspace: Path, memory_config: Any = None):
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self._config = memory_config
        self._cache_dir = ensure_dir(Path.home() / ".nanobot" / "memory")
        self._cache_path = self._cache_dir / "embedding_cache.json"

    # -- Config helpers --

    @property
    def keyword_threshold(self) -> int:
        return self._config.keyword_threshold if self._config else 100

    @property
    def embedding_model(self) -> str:
        return self._config.embedding_model if self._config else ""

    @property
    def embedding_cache_max(self) -> int:
        return self._config.embedding_cache_max if self._config else 2000

    # -- Security validation --

    def _validate_path(self, path: Path) -> None:
        """Ensure path resolves within the memory directory."""
        resolved = path.resolve()
        if not resolved.is_relative_to(self.memory_dir.resolve()):
            raise ValueError(f"Path escapes memory directory: {path}")

    def _validate_content(self, text: str) -> None:
        """Validate a single memory entry's content."""
        max_bytes = self._config.max_entry_bytes if self._config else 1024
        if len(text.encode("utf-8")) > max_bytes:
            raise ValueError(f"Entry exceeds {max_bytes} byte limit")
        if _INJECTION_PATTERNS.search(text):
            raise ValueError("Entry contains disallowed pattern")

    def _validate_file_size(self, additional_bytes: int = 0) -> None:
        """Ensure MEMORY.md won't exceed total size limit after write."""
        max_total = self._config.max_memory_file_bytes if self._config else 102400
        current = len(self.memory_file.read_bytes()) if self.memory_file.exists() else 0
        if current + additional_bytes > max_total:
            raise ValueError(
                f"MEMORY.md would exceed {max_total} byte limit "
                f"(current {current} + {additional_bytes})"
            )

    @staticmethod
    def _sanitize(text: str) -> str:
        """Strip control characters (keep newlines and tabs)."""
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # -- Basic read/write (preserved from original) --

    def get_today_file(self) -> Path:
        return self.memory_dir / f"{today_date()}.md"

    def read_today(self) -> str:
        today_file = self.get_today_file()
        return today_file.read_text(encoding="utf-8") if today_file.exists() else ""

    def append_today(self, content: str) -> None:
        content = self._sanitize(content)
        self._validate_content(content)
        today_file = self.get_today_file()
        self._validate_path(today_file)
        if today_file.exists():
            content = today_file.read_text(encoding="utf-8") + "\n" + content
        else:
            content = f"# {today_date()}\n\n" + content
        today_file.write_text(content, encoding="utf-8")

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        content = self._sanitize(content)
        self._validate_file_size(len(content.encode("utf-8")) - (
            len(self.memory_file.read_bytes()) if self.memory_file.exists() else 0
        ))
        self.memory_file.write_text(content, encoding="utf-8")

    # -- Summary for progressive disclosure --

    def get_memory_summary(self, max_lines: int = 20) -> str:
        """Get a truncated summary of MEMORY.md for prompt injection."""
        content = self.read_long_term()
        if not content:
            return ""
        lines = content.splitlines()
        if len(lines) <= max_lines:
            return content
        truncated = "\n".join(lines[:max_lines])
        remaining = len(lines) - max_lines
        return f"{truncated}\n... ({remaining} more lines, use memory_search to find specific memories)"

    def get_memory_context(self) -> str:
        """Get memory context for prompt (summary + today's notes)."""
        parts = []
        summary = self.get_memory_summary(
            self._config.summary_max_lines if self._config else 20
        )
        if summary:
            parts.append(f"## Long-term Memory (summary)\n{summary}")
        today = self.read_today()
        if today:
            parts.append(f"## Today's Notes\n{today}")
        if parts:
            parts.append("For older or detailed memories, use the memory_search tool.")
        return "\n\n".join(parts) if parts else ""

    # -- Chunking --

    def _build_chunks(self) -> list[Chunk]:
        """Build searchable chunks from all memory files."""
        chunks: list[Chunk] = []
        # MEMORY.md — per-line chunks (structured entries)
        if self.memory_file.exists():
            self._chunk_memory_file(chunks)
        # Daily notes — paragraph chunks
        for md_file in sorted(self.memory_dir.glob("????-??-??.md")):
            self._chunk_daily_file(md_file, chunks)
        return chunks

    def _chunk_memory_file(self, chunks: list[Chunk]) -> None:
        """Chunk MEMORY.md by individual lines under section headers."""
        section = ""
        for i, line in enumerate(self.memory_file.read_text(encoding="utf-8").splitlines()):
            stripped = line.strip()
            if stripped.startswith("## "):
                section = stripped
            elif stripped.startswith("- "):
                chunks.append(Chunk(
                    text=stripped, path=str(self.memory_file),
                    start_line=i + 1, end_line=i + 1, section=section,
                ))

    def _chunk_daily_file(self, path: Path, chunks: list[Chunk]) -> None:
        """Chunk a daily note file by paragraphs (blank-line separated)."""
        lines = path.read_text(encoding="utf-8").splitlines()
        para_lines: list[str] = []
        start = 0
        for i, line in enumerate(lines):
            if line.strip() == "" and para_lines:
                chunks.append(Chunk(
                    text="\n".join(para_lines), path=str(path),
                    start_line=start + 1, end_line=i,
                ))
                para_lines = []
            elif line.strip():
                if not para_lines:
                    start = i
                para_lines.append(line)
        if para_lines:
            chunks.append(Chunk(
                text="\n".join(para_lines), path=str(path),
                start_line=start + 1, end_line=len(lines),
            ))

    # -- Search entry point --

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search memory files. Uses keyword or embedding based on chunk count."""
        chunks = self._build_chunks()
        if not chunks:
            return []

        use_embedding = (
            len(chunks) > self.keyword_threshold
            and self.embedding_model
        )

        if use_embedding:
            try:
                return await self._embedding_search(query, chunks, max_results)
            except Exception as e:
                logger.warning(f"Embedding search failed, falling back to keyword: {e}")

        return self._keyword_search(query, chunks, max_results)

    # -- Keyword search --

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple tokenizer: split on whitespace + split CJK characters individually."""
        tokens: list[str] = []
        for word in text.lower().split():
            # Split CJK characters as individual tokens
            cjk_split = re.findall(r'[\u4e00-\u9fff]|[^\u4e00-\u9fff]+', word)
            tokens.extend(t.strip() for t in cjk_split if t.strip())
        return tokens

    def _keyword_search(
        self, query: str, chunks: list[Chunk], max_results: int
    ) -> list[SearchResult]:
        """Score chunks by keyword hit count."""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[Chunk, float]] = []
        for chunk in chunks:
            chunk_lower = chunk.text.lower()
            hits = sum(1 for t in query_tokens if t in chunk_lower)
            if hits > 0:
                scored.append((chunk, hits / len(query_tokens)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            SearchResult(
                text=c.text, path=c.path, start_line=c.start_line,
                end_line=c.end_line, score=round(s, 3), section=c.section,
            )
            for c, s in scored[:max_results]
        ]

    # -- Embedding search --

    async def _embedding_search(
        self, query: str, chunks: list[Chunk], max_results: int
    ) -> list[SearchResult]:
        """Score chunks by cosine similarity with embeddings."""
        cache = self._load_embedding_cache()

        # Hash all chunks, find which need embedding
        for chunk in chunks:
            chunk.hash = hashlib.sha256(chunk.text.encode()).hexdigest()

        to_embed = [c for c in chunks if c.hash not in cache]
        if to_embed:
            vectors = await self._call_embedding([c.text for c in to_embed])
            for chunk, vec in zip(to_embed, vectors):
                cache[chunk.hash] = vec
            self._save_embedding_cache(cache)

        # Embed query (never cached)
        query_vec = (await self._call_embedding([query]))[0]

        # Score by cosine similarity
        scored: list[tuple[Chunk, float]] = []
        for chunk in chunks:
            vec = cache.get(chunk.hash)
            if vec:
                score = self._cosine_similarity(query_vec, vec)
                scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            SearchResult(
                text=c.text, path=c.path, start_line=c.start_line,
                end_line=c.end_line, score=round(s, 3), section=c.section,
            )
            for c, s in scored[:max_results]
        ]

    async def _call_embedding(self, texts: list[str]) -> list[list[float]]:
        """Call LiteLLM embedding API."""
        from litellm import aembedding
        response = await aembedding(model=self.embedding_model, input=texts)
        return [item["embedding"] for item in response.data]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # -- Embedding cache --

    def _load_embedding_cache(self) -> dict[str, list[float]]:
        """Load embedding cache from disk."""
        if not self._cache_path.exists():
            return {}
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            # Invalidate if model changed
            if data.get("model") != self.embedding_model:
                return {}
            return data.get("entries", {})
        except Exception:
            return {}

    def _save_embedding_cache(self, entries: dict[str, list[float]]) -> None:
        """Save embedding cache to disk with LRU eviction."""
        # Evict oldest 20% if over limit
        if len(entries) > self.embedding_cache_max:
            keep = int(self.embedding_cache_max * 0.8)
            # Keep the most recent entries (dict preserves insertion order in 3.7+)
            keys = list(entries.keys())
            entries = {k: entries[k] for k in keys[-keep:]}

        data = {"model": self.embedding_model, "entries": entries}
        self._cache_path.write_text(json.dumps(data), encoding="utf-8")

    # -- Structured write helpers --

    def add_entry(self, text: str, category: str) -> None:
        """Append a memory entry under the appropriate section in MEMORY.md."""
        text = self._sanitize(text)
        entry = f"- [{category}] {text}"
        self._validate_content(entry)
        self._validate_file_size(len(entry.encode("utf-8")) + 1)  # +1 for newline

        section = CATEGORY_SECTIONS.get(category, "## Notes")
        content = self.read_long_term()

        if not content:
            # Bootstrap MEMORY.md with the section
            content = f"# Long-term Memory\n\n{section}\n{entry}\n"
        elif section in content:
            # Insert after the section header using line-by-line matching
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if line.strip() == section:
                    lines.insert(i + 1, entry)
                    break
            content = "\n".join(lines)
            if not content.endswith("\n"):
                content += "\n"
        else:
            # Append a new section at the end
            content = content.rstrip("\n") + f"\n\n{section}\n{entry}\n"

        self.memory_file.write_text(content, encoding="utf-8")

    def update_entry(self, old_text: str, new_text: str, category: str) -> bool:
        """Replace an existing memory entry. Returns True if found and replaced."""
        new_text = self._sanitize(new_text)
        new_entry = f"- [{category}] {new_text}"
        self._validate_content(new_entry)

        content = self.read_long_term()
        if not content:
            return False

        # Find and replace the old entry line.
        # Match by: exact line, or content part after "- [category] " prefix.
        # Avoids loose substring matching that could hit the wrong entry.
        lines = content.splitlines()
        found = False
        old_stripped = old_text.strip()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == old_stripped:
                # Exact full-line match (e.g. "- [fact] User is in Shanghai")
                lines[i] = new_entry
                found = True
                break
            # Also match against the content portion after "- [tag] "
            bracket_end = stripped.find("] ")
            if bracket_end != -1 and stripped.startswith("- ["):
                content_part = stripped[bracket_end + 2:]
                if content_part == old_stripped:
                    lines[i] = new_entry
                    found = True
                    break

        if found:
            updated = "\n".join(lines)
            if not updated.endswith("\n"):
                updated += "\n"
            self.memory_file.write_text(updated, encoding="utf-8")
        return found

    async def deduplicate(
        self, new_text: str, category: str, provider: Any, model: str,
    ) -> DedupResult:
        """
        Check for similar entries; if found, ask LLM to judge action.

        Returns a DedupResult with action "add", "update", or "noop".
        """
        max_candidates = self._config.dedup_search_results if self._config else 3
        candidates = await self.search(new_text, max_results=max_candidates)

        if not candidates:
            return DedupResult(action="add", text=new_text)

        # Build prompt for LLM judgment
        entries_text = "\n".join(
            f"  {i + 1}. {r.text}" for i, r in enumerate(candidates)
        )
        prompt = (
            "You are a memory deduplication judge. Given existing memory entries "
            "and a new entry, decide the correct action.\n\n"
            f"Existing entries:\n{entries_text}\n\n"
            f"New entry: - [{category}] {new_text}\n\n"
            "Rules:\n"
            '- "noop" if the new entry is already captured by an existing entry\n'
            '- "update" if the new entry contradicts or supersedes an existing entry '
            "(e.g. moved cities, changed preference)\n"
            '- "add" if the new entry is genuinely new information\n\n'
            "Respond with ONLY a JSON object (no markdown):\n"
            '{"action": "add"|"update"|"noop", '
            '"reason": "brief explanation", '
            '"update_target": "exact text of the existing entry to replace (only for update)"}'
        )

        try:
            response = await provider.chat(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                max_tokens=256,
            )
            raw = response.content.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            action = data.get("action", "add")
            if action not in ("add", "update", "noop"):
                action = "add"
            return DedupResult(
                action=action,
                text=new_text,
                update_target=data.get("update_target", ""),
                reason=data.get("reason", ""),
            )
        except Exception as e:
            logger.warning(f"Dedup LLM judgment failed, defaulting to add: {e}")
            return DedupResult(action="add", text=new_text, reason=f"LLM error: {e}")

    # -- Legacy helpers --

    def get_recent_memories(self, days: int = 7) -> str:
        memories = []
        today = datetime.now().date()
        for i in range(days):
            date = today - timedelta(days=i)
            file_path = self.memory_dir / f"{date.strftime('%Y-%m-%d')}.md"
            if file_path.exists():
                memories.append(file_path.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(memories)

    def list_memory_files(self) -> list[Path]:
        if not self.memory_dir.exists():
            return []
        return sorted(self.memory_dir.glob("????-??-??.md"), reverse=True)
