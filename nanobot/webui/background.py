"""Instance-wide, sanitized WebUI background image."""
from __future__ import annotations

import io
import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import TypeGuard, cast

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PIXELS = 32_000_000
MAX_BYTES = 6 * 1024 * 1024
FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def save_background(directory: Path, source: Path | bytes, mime: str) -> None:
    """Decode and re-encode a bounded static raster before atomic replacement."""
    if mime not in FORMATS or (source.stat().st_size if isinstance(source, Path) else len(source)) > MAX_BYTES:
        raise ValueError("Unsupported or oversized background")
    image_source = source if isinstance(source, Path) else io.BytesIO(source)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(image_source) as image:
                if (image.format != FORMATS[mime] or image.width * image.height > MAX_PIXELS
                        or getattr(image, "n_frames", 1) != 1):
                    raise ValueError("Invalid background image")
                image.load()
                image = ImageOps.exif_transpose(image)
                clean = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
                out = io.BytesIO()
                clean.save(out, format="PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid background image") from exc
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".background-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(out.getvalue())
        os.replace(name, directory / "background.png")
    finally:
        Path(name).unlink(missing_ok=True)


def _valid_blur(blur: object) -> TypeGuard[int]:
    return type(blur) is int and 0 <= blur <= 20


def _valid_veil(veil: object) -> TypeGuard[int]:
    return type(veil) is int and 0 <= veil <= 100


def load_background_style(directory: Path) -> dict[str, int]:
    """Read current or legacy instance style, defaulting invalid fields."""
    default = {"blur": 5, "veil": 88}
    try:
        value = json.loads((directory / "background-style").read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, ValueError):
        return default
    if not isinstance(value, dict):
        return default
    style = cast(dict[str, object], value)
    blur, veil = style.get("blur"), style.get("veil")
    return {
        "blur": blur if _valid_blur(blur) else default["blur"],
        "veil": veil if _valid_veil(veil) else default["veil"],
    }


def save_background_style(directory: Path, blur: object, veil: object) -> None:
    """Validate both values before atomically replacing the instance setting."""
    if not _valid_blur(blur) or not _valid_veil(veil):
        raise ValueError("Invalid background style")
    data = json.dumps({"blur": blur, "veil": veil}, separators=(",", ":")).encode("ascii")
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".background-style-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        os.replace(name, directory / "background-style")
    finally:
        Path(name).unlink(missing_ok=True)
