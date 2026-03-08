---
name: feishu-pdf-downloader
description: Download PDF and other files from Feishu/Lark cloud drive using file token. Use when user needs to download files from Feishu cloud drive, extract content from Feishu PDFs, or process documents stored in Feishu. Supports automatic credential loading from ~/.nanobot/.env.
---

# Feishu PDF Downloader

Download files from Feishu (Lark) cloud drive using the Open API.

## Quick Start

```bash
# Download using file token
python3 skills/feishu-pdf-downloader/scripts/download_feishu_pdf.py <file_token> [output_path]

# Example
python3 skills/feishu-pdf-downloader/scripts/download_feishu_pdf.py I5YrbUXUjoruioxtmPWcZSkpnJc document.pdf
```

## Prerequisites

1. **Feishu App Credentials** in `~/.nanobot/.env`:
   ```
   FEISHU_APP_ID = "your_app_id"
   FEISHU_APP_SECRET = "your_app_secret"
   ```

2. **File Token**: Get from Feishu cloud drive file URL or API

## How to Get File Token

### From Web URL
Feishu file URLs contain the token:
- `https://xxx.feishu.cn/file/<file_token>`
- `https://xxx.feishu.cn/drive/folder/<folder_token>`

### From API
Use Feishu drive API to list files and get tokens.

## Download Process

1. **Get Tenant Access Token** using app credentials
2. **Call Download API** with file token
3. **Save binary content** to local file

## API Details

### Authentication
```bash
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
Content-Type: application/json

{
  "app_id": "cli_xxx",
  "app_secret": "xxx"
}
```

### Download File
```bash
GET https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/download
Authorization: Bearer {tenant_access_token}
```

**Note**: This API returns the file content directly (not a JSON response with download URL).

## Python Usage

```python
from skills.feishu_pdf_downloader.scripts.download_feishu_pdf import download_file

# Download file
download_file(
    file_token="I5YrbUXUjoruioxtmPWcZSkpnJc",
    output_path="document.pdf"
)
```

## Processing Downloaded PDFs

After downloading, use the `pdf` skill to:
- Extract text: `pdftotext input.pdf output.txt`
- OCR scanned PDFs: Convert to images → pytesseract
- Extract tables: Use pdfplumber

### OCR Example
```python
from pdf2image import convert_from_path
import pytesseract

images = convert_from_path('document.pdf', dpi=150)
for i, image in enumerate(images):
    text = pytesseract.image_to_string(image, lang='chi_sim')
    print(f'Page {i+1}: {text}')
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "FEISHU_APP_ID not set" | Check ~/.nanobot/.env file format |
| "Failed to get token" | Verify app_id and app_secret are correct |
| "Download failed" | Check file_token is valid and file exists |
| Permission denied | Ensure app has drive:file:read permission |

## References

- [Feishu Drive API Docs](https://open.feishu.cn/document/server-docs/docs/drive-v1/download)
- See `pdf` skill for PDF processing after download
