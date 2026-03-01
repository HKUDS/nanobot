# Document Processing

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/document-processing

## What It Is

Native PDF vision: Gemini reads entire documents including text, images, diagrams, charts, and tables. Extracts structured data, answers questions, and transcribes to HTML preserving layout.

## Gemini API Capabilities

- **Format:** PDF (native vision); non-PDF treated as plain text
- **Max:** 1,000 pages per document, 50MB per file
- **Token cost:** 258 tokens per page
- **Resolution:** large pages scaled to max 3072x3072; small pages scaled up to 768x768
- **Multi-document:** multiple PDFs in a single request (within context window)
- **Gemini 3 updates:**
  - Native text extraction from PDFs (free — not charged for extracted text tokens)
  - PDF page tokens count under IMAGE modality
- **Input methods:** inline bytes or Files API (recommended for larger files)
- **Capabilities:**
  - Text + image + chart + table analysis
  - Structured data extraction into JSON
  - Document summarization and Q&A
  - HTML transcription preserving layouts

## Nanobot Implementation

Not implemented. No PDF or document handling exists in the provider or tools.

**What's needed:**
- Accept PDF file inputs (upload via Files API or inline)
- Construct `types.Part` with PDF content
- Could be an agent tool (`read_document`) or direct chat capability
