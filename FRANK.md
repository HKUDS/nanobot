# FRANK.md — Patch Registry

This file tracks every modification made to nanobot for the Frank deployment.
**After every upstream merge, re-apply any patch that was overwritten and update the status here.**

---

## How to use after an upstream merge

1. Read this file in full.
2. For each patch, check if the target file still contains the change (grep for the key symbol or function name).
3. Re-apply any patch that was lost. Mark it `re-applied` with the date.
4. Run `ruff check nanobot/` and restart Frank.

---

## Patches

### P01 — REVERTED (non necessario)
**Status**: reverted `2026-06-15`
**Problema originale**: notifiche spam da cron job.
**Causa vera**: i job senza notifica erano configurati come cron Telegram invece di stare nell'heartbeat. Frank ha già l'architettura giusta — cron Telegram per notifiche, heartbeat per job silenti. Non serve patch al codice.
**Azione**: nessuna modifica a `loop.py`. Se un job spamma, dirlo a Frank e farglielo spostare nell'heartbeat.

---

### P02 — Env vars override config JSON api_key
**Status**: applied `2026-06-15`
**Commit**: `ebf8c391`
**Problem**: Railway env vars (e.g. `MINIMAX_API_KEY`) were ignored when a stale key was embedded in `NANOBOT_CONFIG_JSON`. Env vars must win.
**Files changed**:
- `nanobot/config/schema.py` — `get_api_key()`: before returning `p.api_key`, check `os.environ.get(spec.env_key)` via provider registry

**Key invariant to verify after merge**:
```python
# In schema.py get_api_key(), env var lookup must exist before return:
if model:
    from nanobot.providers.registry import find_by_name
    ...
    env_val = os.environ.get(spec.env_key, "").strip()
    if env_val:
        return env_val
```

---

### P03 — VisionAugmentedProvider + vision chain
**Status**: applied `2026-06-15`
**Commit**: `448ca84b` (partial), `67f30584`
**Problem**: Text-only models (DeepSeek) couldn't handle image inputs. Need automatic image→text fallback.
**Files added**:
- `nanobot/providers/vision_augmented_provider.py`
- `nanobot/providers/vision_chain.py`

**Key invariant to verify after merge**: both files exist and `factory.py` wraps providers with `VisionAugmentedProvider`.

---

### P04 — Custom tools
**Status**: applied `2026-06-15`
**Commit**: `448ca84b`
**Files added** (Frank-specific tools, not upstream):
- `nanobot/agent/tools/playwright_render.py` — HTML/CSS → PNG/PDF
- `nanobot/agent/tools/subconscious.py` — Obsidian vault FTS + memory sync
- `nanobot/agent/tools/packlink.py` — Packlink Pro shipping

These files are Frank-specific and will never be in upstream. Verify they exist after merge.

---

### P05 — Subconscious subsystem
**Status**: applied `2026-06-15`
**Commit**: `448ca84b`
**Files added**:
- `nanobot/subconscious/__init__.py`
- `nanobot/subconscious/store.py`
- `nanobot/subconscious/vault.py`
- `nanobot/subconscious/sync.py`

Verify after merge: directory `nanobot/subconscious/` exists with all 4 files.

---

### P06 — Skills (Frank-specific)
**Status**: applied `2026-06-15`
**Commit**: `448ca84b`, `942226f3`
**Files added** (not upstream):
- `nanobot/skills/packlink/SKILL.md`
- `nanobot/skills/spark/SKILL.md`
- `nanobot/skills/subconscious/SKILL.md`
- `nanobot/skills/apps/SKILL.md`

Verify after merge: all 4 skill directories exist.

---

## Jobs config (`~/.nanobot/cron/jobs.json`)

After any Frank restart or config wipe, verify these job-level settings:

| job name | deliver | notes |
|---|---|---|
| `railway-log-health-check` | `false` | silent check, uses `message` tool on real errors only |
| `email-polling-foolish` | `false` | silent check, uses `message` tool on new emails only |
| `umami-daily-analytics` | `false` | silent |
| `obsidian-nightly-check` | `false` | silent |
| `nanobot-upstream-check` | `false` | silent |
| `foolish-weekly-research` | `true` | delivers digest |
| `scribacchino-digest` | `true` | delivers daily summary |
| `cms-packlink-check` | `true` | delivers tracking status |
| `sebo-concept-8am` | `true` | delivers concepts |
| `sebo-concept-4pm` | `true` | delivers concepts |
| `📸 promemoria foto prodotti` | `true` | delivers reminder |
