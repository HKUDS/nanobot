"""Best-effort document text extraction helpers."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from pathlib import Path


_TEXT_EXTS = {".txt", ".md", ".markdown", ".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".csv", ".log"}
_DOC_EXTS = {".pdf", *list(_TEXT_EXTS)}
_MAX_CHARS = 4000
_TEXT_READ_CHUNK_SIZE = 8192
_ENCODING_PROBE_BYTES = 4096


@dataclass
class DocumentExtractionResult:
    """Structured best-effort extraction result.

    Contract:
    - ``text`` is already truncated to a prompt-safe bound when present.
    - ``extractor`` labels provenance for the excerpt.
    - ``note`` explains graceful-degradation cases such as missing PDF support.
    """

    text: str | None = None
    extractor: str | None = None
    truncated: bool = False
    note: str | None = None


def is_supported_document(path: str | Path) -> bool:
    """Return True if the file extension is supported for text extraction."""
    return Path(path).suffix.lower() in _DOC_EXTS


def extract_document(path: str | Path, max_chars: int = _MAX_CHARS) -> DocumentExtractionResult | None:
    """Extract readable text plus provenance metadata for a local document."""
    p = Path(path)
    ext = p.suffix.lower()

    if ext in _TEXT_EXTS:
        return _extract_text_file(p, max_chars)
    if ext == ".pdf":
        return _extract_pdf_text(p, max_chars)
    return None


def extract_document_text(path: str | Path, max_chars: int = _MAX_CHARS) -> str | None:
    """Backward-compatible text-only wrapper around :func:`extract_document`."""
    result = extract_document(path, max_chars=max_chars)
    return result.text if result and result.text else None


def _extract_text_file(path: Path, max_chars: int) -> DocumentExtractionResult | None:
    probe = _read_encoding_probe(path)
    for encoding in _iter_text_encodings(path):
        try:
            result = _read_text_excerpt(path, max_chars, encoding)
        except Exception:
            continue
        if result and _should_retry_utf16_after_utf8(probe, result.text, encoding):
            continue
        return result
    return DocumentExtractionResult(note="Unable to decode this text document with supported fallbacks.")


def _iter_text_encodings(path: Path) -> tuple[str, ...]:
    probe = _read_encoding_probe(path)
    if probe.startswith(codecs.BOM_UTF16_LE):
        return ("utf-16", "utf-16-le", "utf-16-be", "utf-8-sig", "utf-8", "gb18030", "latin-1")
    if probe.startswith(codecs.BOM_UTF16_BE):
        return ("utf-16", "utf-16-be", "utf-16-le", "utf-8-sig", "utf-8", "gb18030", "latin-1")
    if _looks_like_utf16_bytes(probe):
        return ("utf-16-le", "utf-16-be", "utf-8-sig", "utf-8", "gb18030", "latin-1")
    return ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "gb18030", "latin-1")


def _read_encoding_probe(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(_ENCODING_PROBE_BYTES)


def _looks_like_utf16_bytes(data: bytes) -> bool:
    if len(data) < 4:
        return False

    even_nuls = sum(byte == 0 for byte in data[::2])
    odd_nuls = sum(byte == 0 for byte in data[1::2])
    even_ratio = even_nuls / max(1, len(data[::2]))
    odd_ratio = odd_nuls / max(1, len(data[1::2]))

    # UTF-16 text often presents as ASCII bytes alternating with NULs in one lane.
    return max(even_ratio, odd_ratio) > 0.3 and abs(even_ratio - odd_ratio) > 0.2


def _should_retry_utf16_after_utf8(probe: bytes, text: str | None, encoding: str) -> bool:
    if encoding not in {"utf-8-sig", "utf-8"} or not text or len(probe) < 4 or len(probe) % 2 != 0:
        return False
    if _looks_like_utf16_bytes(probe):
        return False
    return _has_suspicious_control_chars(text)


def _has_suspicious_control_chars(text: str) -> bool:
    for char in text:
        if ord(char) < 32 and char not in "\t\n\r":
            return True
    return False


def _read_text_excerpt(path: Path, max_chars: int, encoding: str) -> DocumentExtractionResult | None:
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    text = ""
    started = False

    with path.open("rb") as handle:
        while chunk := handle.read(_TEXT_READ_CHUNK_SIZE):
            piece = decoder.decode(chunk)
            if not started:
                piece = piece.lstrip()
                if not piece:
                    continue
                started = True
            text += piece
            stripped = text.rstrip()
            if len(stripped) > max_chars:
                return DocumentExtractionResult(
                    text=stripped[:max_chars],
                    extractor=f"text:{encoding}",
                    truncated=True,
                )

        tail = decoder.decode(b"", final=True)

    if not started:
        tail = tail.lstrip()
    text = f"{text}{tail}".strip()
    if not text:
        return None
    return DocumentExtractionResult(
        text=text[:max_chars],
        extractor=f"text:{encoding}",
        truncated=len(text) > max_chars,
    )


def _extract_pdf_text(path: Path, max_chars: int) -> DocumentExtractionResult | None:
    try:
        from pypdf import PdfReader
    except Exception:
        return DocumentExtractionResult(
            note="PDF text extraction unavailable because optional dependency 'pypdf' is not installed."
        )

    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            parts.append(text)
            total += len(text)
            if total >= max_chars:
                break
        merged = "\n\n".join(parts).strip()
        if not merged:
            return DocumentExtractionResult(note="No readable text could be extracted from this PDF.")
        return DocumentExtractionResult(
            text=merged[:max_chars],
            extractor="pdf:pypdf",
            truncated=len(merged) > max_chars,
        )
    except Exception as exc:
        return DocumentExtractionResult(note=f"PDF text extraction failed: {exc}")
