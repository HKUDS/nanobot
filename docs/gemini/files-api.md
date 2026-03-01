# Files API

> **Status: Partial** — used for video download only
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/files

## What It Is

Upload, manage, and reference media files for use in Gemini API requests. Free of charge. Files auto-delete after 48 hours.

## Gemini API Capabilities

### Operations

| Operation | Method | Description |
|-----------|--------|-------------|
| Upload | `client.files.upload()` | Upload media file |
| List | `client.files.list()` | List all uploaded files |
| Get | `client.files.get(name)` | Get file metadata |
| Delete | `client.files.delete(name)` | Delete a file |
| Download | `client.files.download(file)` | Download generated file |

### Limits

- Max per file: 2GB
- Max per project: 20GB
- Retention: 48 hours (auto-delete)
- Resumable uploads supported (REST)

### Size thresholds

- General requests >100MB → should use Files API
- PDFs >50MB → should use Files API

### Supported content

Audio, images, video, documents, and all other media types.

### Pricing

Free in all regions where Gemini API is available.

## Nanobot Implementation

**Partial:** Video generation downloads use `client.files.download()`:

```python
# scorpion/agent/tools/creative.py line 244
dl = await client.files.download(file=video.video, download_config=...)
```

**Not implemented:**
- `client.files.upload()` — no file uploads
- `client.files.list()` / `client.files.get()` — no file management
- `client.files.delete()` — no cleanup
- File references in chat messages (no `file_data` parts)

**What full Files API would enable:**
- Upload PDFs, audio, video for analysis in chat
- Reference uploaded files across multiple requests
- Large file support (up to 2GB)
- Clean file lifecycle management
