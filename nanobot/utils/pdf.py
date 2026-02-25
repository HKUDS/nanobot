"""PDF text extraction utility."""

from pathlib import Path

from loguru import logger

try:
    from pypdf import PdfReader

    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False
    PdfReader = None


def extract_pdf_text(file_path: str | Path, max_chars: int = 50000) -> str | None:
    """Extract text content from a PDF file.

    Args:
        file_path: Path to the PDF file.
        max_chars: Maximum characters to extract (default 50k to avoid huge payloads).

    Returns:
        Extracted text or None if extraction failed or pypdf is not installed.
    """
    if not PYPDF_AVAILABLE:
        logger.debug("pypdf not installed, skipping PDF text extraction")
        return None

    try:
        reader = PdfReader(str(file_path))
        pages = []
        total = 0
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                text = text.strip()
                if total + len(text) > max_chars:
                    text = text[: max_chars - total]
                    pages.append(f"[Page {i + 1}]\n{text}\n...(truncated)")
                    break
                pages.append(f"[Page {i + 1}]\n{text}")
                total += len(text)
        if not pages:
            return None
        return "\n\n".join(pages)
    except Exception as e:
        logger.warning("Failed to extract text from PDF {}: {}", file_path, e)
        return None
