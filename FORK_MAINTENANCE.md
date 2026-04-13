# Fork Maintenance Guide

This repository is maintained as a desktop-focused fork of the upstream project:

- Upstream: `git@github.com:HKUDS/nanobot.git`
- Personal fork: `git@github.com:clawuv/nanobot-agent.git`
- Recommended working branch: `codex/desktop-fork-upstream`

## Branch Strategy

- `main`
  Tracks upstream `main` as closely as possible.
- `codex/desktop-fork-upstream`
  Primary branch for desktop app work and fork-specific features.
- `codex/desktop-fork`
  Legacy preservation branch from the earlier local history. Keep as backup only.

## Normal Upgrade Flow

Use this flow whenever upstream publishes new changes:

```bash
cd /Users/hht/workspace/nanobot
git fetch upstream
git switch main
git merge upstream/main
git push origin main
git switch codex/desktop-fork-upstream
git merge main
git push origin codex/desktop-fork-upstream
```

## Conflict Priority

When merges conflict, resolve files in this order.

### High Risk

These files carry fork-specific runtime behavior and are most likely to require manual merging:

- `nanobot/gateway/api.py`
- `nanobot/agent/loop.py`
- `nanobot/agent/memory.py`
- `nanobot/agent/context.py`
- `nanobot/agent/subagent.py`
- `nanobot/session/manager.py`
- `nanobot/runtime/modeling.py`
- `nanobot/providers/registry.py`
- `nanobot/config/schema.py`

Why:

- Desktop API endpoints live here.
- Session-bound model selection lives here.
- Request-scoped runtime logic lives here.
- OAuth and multimodal compatibility touches these files.

### Medium Risk

These files are important integration points, but usually easier to reconcile:

- `nanobot/providers/gemini_oauth_provider.py`
- `nanobot/providers/openai_codex_provider.py`
- `nanobot/config/loader.py`
- `nanobot/channels/telegram.py`
- `nanobot/cli/commands.py`
- `bridge/src/server.ts`

Why:

- They depend on surrounding APIs and config contracts.
- Upstream refactors can break assumptions without directly touching desktop UI.

### Low Risk

These files are mostly fork-owned product/UI code:

- `desktop/src/App.tsx`
- `desktop/src/components/ChatMain.tsx`
- `desktop/src/components/SettingsPage.tsx`
- `desktop/src/components/CronPage.tsx`
- `desktop/src/components/Sidebar.tsx`
- `desktop/src/hooks/useChat.ts`
- `desktop/src/hooks/useWebSocket.ts`
- `desktop/src/index.css`
- `desktop/src-tauri/src/lib.rs`

Why:

- They are largely independent from upstream UI work.
- Most breakages here come from backend API contract changes, not upstream merge conflicts.

## Core Fork Features To Protect

When resolving merges, make sure these behaviors still work after integration:

- Desktop app UI and Tauri shell
- Session-bound model selection
- Request-scoped runtime model switching
- Model management UI and backend APIs
- OpenAI OAuth model flow
- Gemini OAuth import/status/revoke flow
- Image upload, preview, and multimodal routing
- Screenshot/file return flow in desktop chat
- Cron page and settings page integration
- Session title derived from first user message

## Practical Merge Checklist

After merging upstream into `codex/desktop-fork-upstream`, check:

1. `git status`
2. `git diff --name-only main..codex/desktop-fork-upstream`
3. Desktop build:

```bash
cd /Users/hht/workspace/nanobot/desktop
npm run build
```

4. Python syntax sanity check for touched backend files:

```bash
cd /Users/hht/workspace/nanobot
python -m py_compile nanobot/gateway/api.py
python -m py_compile nanobot/runtime/modeling.py
python -m py_compile nanobot/session/manager.py
```

5. Manually verify:

- chat loads
- session switching works
- model switching works
- settings page works
- cron page works
- image upload works
- OAuth status checks still work

## Rule Of Thumb

If an upstream update breaks the fork, inspect these first:

1. `nanobot/gateway/api.py`
2. `nanobot/agent/loop.py`
3. `nanobot/runtime/modeling.py`
4. `nanobot/providers/registry.py`
5. `nanobot/session/manager.py`

These files define whether the desktop fork still functions end-to-end.
