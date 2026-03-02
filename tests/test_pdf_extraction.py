"""Tests for PDF text extraction utility."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestExtractPdfText:
    """Tests for extract_pdf_text function."""

    def test_returns_none_when_pypdf_not_available(self):
        with patch("nanobot.utils.pdf.PYPDF_AVAILABLE", False):
            from nanobot.utils.pdf import extract_pdf_text

            result = extract_pdf_text("/fake/path.pdf")
            assert result is None

    def test_returns_none_for_nonexistent_file(self):
        from nanobot.utils.pdf import extract_pdf_text

        result = extract_pdf_text("/nonexistent/file.pdf")
        assert result is None

    def test_extracts_text_from_pdf(self):
        from nanobot.utils.pdf import extract_pdf_text

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Hello World"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("nanobot.utils.pdf.PdfReader", return_value=mock_reader):
            with patch("nanobot.utils.pdf.PYPDF_AVAILABLE", True):
                result = extract_pdf_text("/fake/path.pdf")
                assert result is not None
                assert "Hello World" in result
                assert "[Page 1]" in result

    def test_extracts_multiple_pages(self):
        from nanobot.utils.pdf import extract_pdf_text

        pages = []
        for i in range(3):
            p = MagicMock()
            p.extract_text.return_value = f"Page {i + 1} content"
            pages.append(p)
        mock_reader = MagicMock()
        mock_reader.pages = pages

        with patch("nanobot.utils.pdf.PdfReader", return_value=mock_reader):
            with patch("nanobot.utils.pdf.PYPDF_AVAILABLE", True):
                result = extract_pdf_text("/fake/path.pdf")
                assert "[Page 1]" in result
                assert "[Page 2]" in result
                assert "[Page 3]" in result

    def test_truncates_at_max_chars(self):
        from nanobot.utils.pdf import extract_pdf_text

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 1000
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page, mock_page]

        with patch("nanobot.utils.pdf.PdfReader", return_value=mock_reader):
            with patch("nanobot.utils.pdf.PYPDF_AVAILABLE", True):
                result = extract_pdf_text("/fake/path.pdf", max_chars=500)
                assert "truncated" in result

    def test_skips_empty_pages(self):
        from nanobot.utils.pdf import extract_pdf_text

        empty_page = MagicMock()
        empty_page.extract_text.return_value = ""
        text_page = MagicMock()
        text_page.extract_text.return_value = "Real content"
        mock_reader = MagicMock()
        mock_reader.pages = [empty_page, text_page]

        with patch("nanobot.utils.pdf.PdfReader", return_value=mock_reader):
            with patch("nanobot.utils.pdf.PYPDF_AVAILABLE", True):
                result = extract_pdf_text("/fake/path.pdf")
                assert "Real content" in result
                assert "[Page 2]" in result

    def test_returns_none_for_all_empty_pages(self):
        from nanobot.utils.pdf import extract_pdf_text

        empty_page = MagicMock()
        empty_page.extract_text.return_value = ""
        mock_reader = MagicMock()
        mock_reader.pages = [empty_page]

        with patch("nanobot.utils.pdf.PdfReader", return_value=mock_reader):
            with patch("nanobot.utils.pdf.PYPDF_AVAILABLE", True):
                result = extract_pdf_text("/fake/path.pdf")
                assert result is None

    def test_handles_extract_text_returning_none(self):
        from nanobot.utils.pdf import extract_pdf_text

        mock_page = MagicMock()
        mock_page.extract_text.return_value = None
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("nanobot.utils.pdf.PdfReader", return_value=mock_reader):
            with patch("nanobot.utils.pdf.PYPDF_AVAILABLE", True):
                result = extract_pdf_text("/fake/path.pdf")
                assert result is None
