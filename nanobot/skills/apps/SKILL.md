---
name: apps
description: Discover, install, and manage CLI Apps and MCP preset integrations available in nanobot.
---

# Apps

nanobot ha due tipi di integrazioni installabili dalla sezione "Apps" della WebUI:

1. **CLI Apps** — tool CLI installabili (npm/pip/bundled) dal registro CLI-Anything e dalle estensioni nanobot. Una volta installate, si usano via `run_cli_app`.
2. **MCP Presets** — server MCP preconfigurati (Browserbase, GitHub, Supabase, Firecrawl, ecc.) che espongono tool aggiuntivi all'agente.

---

## Scoprire le app disponibili

### Registro CLI Apps

```python
import httpx, json

# Registro harness ufficiale
harness = httpx.get("https://hkuds.github.io/CLI-Anything/registry.json", follow_redirects=True).json()
# Registro pubblico (più app)
public = httpx.get("https://hkuds.github.io/CLI-Anything/public_registry.json", follow_redirects=True).json()
# Estensioni nanobot
ext = httpx.get("https://raw.githubusercontent.com/Re-bin/nanobot-extension/main/registry.json").json()

for app in public.get("clis", []):
    print(app["name"], "-", app.get("description", "")[:80])
```

### MCP Presets disponibili (built-in)

| name | Cosa fa |
|------|---------|
| `browserbase` | Browser cloud automation (API key richiesta) |
| `playwright` | Browser automation locale (npx, no key) |
| `context7` | Docs aggiornate di librerie in tempo reale (no key) |
| `firecrawl` | Scrape/crawl/extract web (API key) |
| `exa` | Web search avanzato + fetch (API key) |
| `brave-search` | Web/news/image search (API key) |
| `github` | Repo, issue, PR (Personal Access Token) |
| `supabase` | DB/project management (Access Token) |
| `postman` | API collections (API key) |
| `figma` | Design context read (no key, Dev Mode locale) |
| `microsoft-learn` | Docs Microsoft (no key) |
| `aws-docs` | Docs AWS (no key) |

### App CLI pubbliche attualmente nel registro

| name | categoria | note |
|------|-----------|------|
| `shopify` | web | e-commerce store/theme/app management |
| `elevenlabs` | audio | voice agents, TTS, cloning |
| `suno` | music | generazione musica da testo/stile |
| `generate-veo-video` | ai | video generation Google Veo 3.1 |
| `jimeng` | ai | ByteDance image+video generation |
| `obsidian-agent-cli` | productivity | Obsidian: note, canvas, Excalidraw, Kanban |
| `obsidian-cli` | knowledge | Obsidian vault automation e developer tools |
| `firecrawl` | web | scraping CLI |
| `sentry` | devops | release, sourcemaps, monitors |
| `1password-cli` | devops | vault, secrets, items |
| `contentful` | web | CMS headless |
| `sanity` | web | CMS headless |
| `cloakbrowser` | web | Chromium stealth anti-bot |
| `deployhq` | devops | deploy automatico |
| `android-cli` | mobile | SDK Android, emulatori |
| `hyperframes` | video | HTML-to-MP4 motion graphics |

---

## Installare una CLI App

```python
import sys
sys.path.insert(0, '/home/ab/nanobot')
from nanobot.apps.cli.service import CliAppManager

manager = CliAppManager(workspace='/home/ab/.nanobot')
result = manager.install('elevenlabs')  # sostituire col nome app
print(result.get('last_action', {}).get('message'))
```

Dopo l'installazione la app è disponibile via `run_cli_app(name="elevenlabs", args=["--help"])`.

Per verificare le app già installate:

```python
manager = CliAppManager(workspace='/home/ab/.nanobot')
print(manager.installed_names())
```

---

## Attivare un MCP Preset

I preset MCP richiedono configurazione nella sezione `tools.mcpServers` di `~/.nanobot/config.json`.
Alcuni non richiedono API key (context7, playwright, microsoft-learn, aws-docs).

### Esempio: context7 (no key)

```json
{
  "tools": {
    "mcpServers": {
      "context7": {
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp@latest"]
      }
    }
  }
}
```

### Esempio: GitHub MCP (con token)

```json
{
  "tools": {
    "mcpServers": {
      "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
          "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
        }
      }
    }
  }
}
```

Per i preset con API key, chiedere ad Alessandro la chiave prima di configurare.
Dopo aver modificato la config, usare `/restart` per ricaricare.

---

## Flusso consigliato

1. **Identifica l'esigenza** — quale task vuoi automatizzare o migliorare?
2. **Cerca nel registro** — `web_fetch` sui registry URL sopra, filtra per categoria/descrizione.
3. **Valuta** — la app richiede API key? Esiste già qualcosa di equivalente installato?
4. **Proponi ad Alessandro** — prima di installare, descrivi cosa fa e perché serve.
5. **Installa** — usa il codice Python sopra o chiedi conferma e procedi.
6. **Documenta** — aggiorna la skill o la memoria se è un'integrazione stabile.
