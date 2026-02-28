# Web Tools: Internet Search Flow

Dokumen ini menjelaskan bagaimana nanobot mengambil data dari internet, serta batas peran antara **tool** dan **skill**.

## Ringkasan

- Internet search dijalankan oleh **tool bawaan agent** (bukan skill langsung).
- Skill hanya mengarahkan **kapan** dan **bagaimana strategi** penggunaan tool.
- Eksekusi network call tetap melalui implementasi tool di kode inti nanobot.

## Komponen Utama

1. Registrasi tool di Agent Loop  
   `web_search` dan `web_fetch` diregistrasi di agent runtime.

2. Implementasi tool web  
   Tool berada di `nanobot/agent/tools/web.py`.

3. Konfigurasi API key  
   API key web search dibaca dari konfigurasi:
   - `tools.web.search.apiKey`
   - `tools.web.search.maxResults`
   - Jika `apiKey` kosong, `web_search` otomatis fallback ke DuckDuckGo (via package `ddgs`).

## Skill vs Tool

- **Tool (core project):**
  Menjalankan pencarian/fetch internet yang sebenarnya.
- **Skill (instruction layer):**
  Memberi pola instruksi penggunaan tool sesuai konteks task.

Dengan kata lain, skill tidak mengganti mesin search; skill memandu agent memanfaatkan tool yang sudah ada.

## Review & Saran

Masukan yang diharapkan dari reviewer:

1. Apakah naming tool (`web_search`, `web_fetch`) sudah jelas untuk contributor baru?
2. Apakah default config search sudah cukup aman dan efisien?
3. Perlu atau tidak menambah provider search alternatif selain Brave?
4. Perlu atau tidak menambah guardrail tambahan (domain allowlist/denylist)?

Jika ada usulan perubahan, silakan buka issue/PR dan referensikan dokumen ini.
