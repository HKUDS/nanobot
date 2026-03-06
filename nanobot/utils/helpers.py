"""Utility functions for nanobot."""

import re
import subprocess
from datetime import datetime
from pathlib import Path


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, ignoring file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def detect_audio_mime(data: bytes) -> str | None:
    """Detect audio MIME type from magic bytes."""
    if len(data) < 12:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if data[:3] == b"ID3":
        return "audio/mpeg"
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[:4] == b"fLaC":
        return "audio/flac"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    return None


def detect_video_mime(data: bytes) -> str | None:
    """Detect video MIME type from magic bytes (excludes audio-only containers)."""
    if len(data) < 12:
        return None
    if data[4:8] == b"ftyp":
        subtype = data[8:12]
        if subtype in (b"M4A ", b"M4B "):
            return None  # Audio, not video
        return "video/mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    if data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "video/avi"
    return None


def _split_pngs(data: bytes) -> list[bytes]:
    """Split concatenated PNG data into individual PNG buffers."""
    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    frames: list[bytes] = []
    start = 0
    while True:
        pos = data.find(PNG_MAGIC, start + 1 if start > 0 else 1)
        if pos == -1:
            if start < len(data):
                frames.append(data[start:])
            break
        frames.append(data[start:pos])
        start = pos
    return [f for f in frames if f.startswith(PNG_MAGIC)]


def extract_video_frames(path: Path, max_frames: int = 4) -> list[bytes]:
    """Extract keyframes from a video using ffmpeg. Returns list of PNG bytes.

    Returns empty list if ffmpeg is unavailable or extraction fails.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", str(path),
                "-vf", "fps=1/2",  # ~1 frame every 2 seconds
                "-frames:v", str(max_frames),
                "-f", "image2pipe", "-vcodec", "png", "pipe:1",
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        return _split_pngs(result.stdout)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return []


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_path() -> Path:
    """~/.nanobot data directory."""
    return ensure_dir(Path.home() / ".nanobot")


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure workspace path. Defaults to ~/.nanobot/workspace."""
    path = Path(workspace).expanduser() if workspace else Path.home() / ".nanobot" / "workspace"
    return ensure_dir(path)


def timestamp() -> str:
    """Current ISO timestamp."""
    return datetime.now().isoformat()


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """
    Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind('\n')
        if pos <= 0:
            pos = cut.rfind(' ')
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Sync bundled templates to workspace. Only creates missing files."""
    from importlib.resources import files as pkg_files
    try:
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md"):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "HISTORY.md")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console
        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")
    return added
