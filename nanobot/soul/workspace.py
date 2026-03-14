"""Agent workspace management with Soul & Memory support.

Each agent owns an independent workspace directory containing:
  - SOUL.md:              Personality / persona definition
  - MEMORY.md:            Long-term curated memory
  - memory/YYYY-MM-DD.md: Daily append-only memory logs

Reference: OpenClaw src/agents/workspace.ts  loadWorkspaceBootstrapFiles()
Reference: OpenClaw src/agents/agent-scope.ts  resolveAgentWorkspaceDir()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger


# Default workspace root (can be overridden per-agent)
DEFAULT_WORKSPACE_ROOT = Path.home() / ".nanobot" / "workspace"

# Bootstrap file limits (aligned with OpenClaw defaults)
BOOTSTRAP_MAX_CHARS = 20_000
BOOTSTRAP_TOTAL_MAX_CHARS = 24_000

# Default SOUL.md template
SAMPLE_SOUL = """\
# SOUL.md - Who You Are

_You're not a chatbot. You're becoming someone._

## Core Truths

**Be genuinely helpful, not performatively helpful.** Skip the "Great question!" \
and "I'd be happy to help!" -- just help. Actions speak louder than filler words.

**Have opinions.** You're allowed to disagree, prefer things, find stuff amusing \
or boring. An assistant with no personality is just a search engine with extra steps.

**Be resourceful before asking.** Try to figure it out. Read the file. Check the \
context. Search for it. _Then_ ask if you're stuck.

## Boundaries

- Private things stay private. Period.
- When in doubt, ask before acting externally.

## Vibe

Be the assistant you'd actually want to talk to. Concise when needed, thorough \
when it matters. Not a corporate drone. Not a sycophant. Just... good.

## Continuity

Each session, you wake up fresh. These files _are_ your memory. Read them. \
Update them. They're how you persist.
"""


@dataclass
class AgentWorkspace:
    """Manages an agent's workspace directory with Soul & Memory files.

    Attributes:
        agent_id: Unique identifier for the agent.
        workspace_dir: Root directory for this agent's files.
    """

    agent_id: str
    workspace_dir: Path = field(default=None)

    def __post_init__(self) -> None:
        if self.workspace_dir is None:
            self.workspace_dir = DEFAULT_WORKSPACE_ROOT / self.agent_id
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "memory").mkdir(exist_ok=True)

    @property
    def soul_path(self) -> Path:
        return self.workspace_dir / "SOUL.md"

    @property
    def memory_md_path(self) -> Path:
        return self.workspace_dir / "MEMORY.md"

    @property
    def memory_dir(self) -> Path:
        return self.workspace_dir / "memory"

    def ensure_soul(self) -> None:
        """Create a sample SOUL.md if none exists."""
        if not self.soul_path.exists():
            self.soul_path.write_text(SAMPLE_SOUL, encoding="utf-8")
            logger.info("Created sample SOUL.md at {}", self.soul_path)

    def read_soul(self) -> str:
        """Read SOUL.md content. Returns empty string if not found."""
        if self.soul_path.exists() and not self.soul_path.is_symlink():
            try:
                return self.soul_path.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning("Failed to read SOUL.md: {}", e)
        return ""

    def has_soul(self) -> bool:
        return self.soul_path.exists() and not self.soul_path.is_symlink()


def truncate_bootstrap(content: str, max_chars: int = BOOTSTRAP_MAX_CHARS) -> str:
    """Truncate bootstrap file: keep 70% head + 20% tail.

    Reference: OpenClaw src/agents/pi-embedded-helpers/bootstrap.ts
    """
    if len(content) <= max_chars:
        return content
    head_budget = int(max_chars * 0.70)
    tail_budget = int(max_chars * 0.20)
    head = content[:head_budget]
    tail = content[-tail_budget:] if tail_budget > 0 else ""
    return f"{head}\n\n[...truncated...]\n\n{tail}"


def load_bootstrap_files(workspace_dir: Path) -> list[dict[str, str]]:
    """Load SOUL.md and MEMORY.md from workspace as bootstrap files.

    Returns list of {name, content} dicts, respecting per-file and total char limits.

    Reference: OpenClaw src/agents/workspace.ts  loadWorkspaceBootstrapFiles()
    """
    files: list[dict[str, str]] = []
    total_chars = 0

    for name in ("SOUL.md", "MEMORY.md"):
        path = workspace_dir / name
        if not path.exists():
            continue
        if path.is_symlink():
            logger.warning("Skipping symlink: {}", path)
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("Failed to read {}: {}", path, e)
            continue
        if not raw:
            continue

        content = truncate_bootstrap(raw)
        if total_chars + len(content) > BOOTSTRAP_TOTAL_MAX_CHARS:
            budget = max(0, BOOTSTRAP_TOTAL_MAX_CHARS - total_chars)
            if budget <= 0:
                break
            content = truncate_bootstrap(raw, budget)

        files.append({"name": name, "content": content})
        total_chars += len(content)

    return files
