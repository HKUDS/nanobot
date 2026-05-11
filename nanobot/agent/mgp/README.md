# MGP Sidecar for nanobot

Optional integration that connects nanobot to a [Memory Governance Protocol (MGP)](https://github.com/HKUDS/MGP) gateway. When enabled, the agent can explicitly recall cross-session, governed long-term memory via the `recall_memory` tool, and the LLM-extracted facts produced by nanobot's existing Consolidator and Dream pipelines are mirrored to MGP automatically.

> **TL;DR** — disabled by default; opt in with `agents.defaults.mgp.enabled: true`. Recall is **agent-driven** (a tool, not a system-prompt injection). Commit is **automatic** (rides on Consolidator + Dream output, zero added LLM cost).

> Gateway-side configuration (adapter selection, embedding models, authentication, troubleshooting) lives in the MGP repo: see [`integrations/nanobot/README.md`](https://github.com/HKUDS/MGP/blob/main/integrations/nanobot/README.md). This page only covers the runtime-side wiring.

---

## 1. Why MGP (vs nanobot's native bulk-injection memory)

nanobot's native memory pipeline already does excellent work for stable, single-instance deployments:

- `MEMORY.md` / `SOUL.md` / `USER.md` are **bulk-injected** into every system prompt — the agent never has to "ask" for them.
- `Dream` periodically condenses raw history into curated long-term knowledge.
- `Consolidator` summarizes evicted messages into `history.jsonl` so the agent can `grep` them on demand.

MGP is a **complementary** layer, not a replacement:

| Dimension | nanobot native                      | MGP sidecar (this package)       |
| --------- | ----------------------------------- | -------------------------------- |
| Trigger   | Every LLM request, automatic        | Only when the agent calls a tool |
| Method    | Bulk inject curated full files      | Query-based recall via tool call |
| Frequency | 100% of turns                       | Typically <20% of turns          |
| Best at   | "What the agent always should know" | "What is relevant to this turn"  |

Add MGP when you have at least one of: multi-device sync, multi-user sharing the same bot, large history, cross-language recall (vector backend), or compliance/audit needs. Skip MGP for a single-user, single-channel deployment — native memory is already enough.

---

## 2. How It Works

### Recall path (agent decides)

```mermaid
flowchart TD
  UserMsg["InboundMessage"] --> ProcessMessage["AgentLoop._process_message"]
  ProcessMessage --> BuildMsgs["context.build_messages"]
  BuildMsgs --> SystemPrompt["system prompt includes mgp-memory SKILL.md"]
  SystemPrompt --> LLMCall["LLM reasoning"]
  LLMCall --> Decide{"Need to recall?"}
  Decide -->|"no, ~80% of turns"| Answer["Direct answer"]
  Decide -->|"yes"| ToolCall["tool_call: recall_memory"]
  ToolCall --> Sidecar["sidecar.recall(runtime, intent)"]
  Sidecar --> Gateway["MGP /search"]
  Gateway --> Result["top-K results back to LLM"]
  Result --> LLMCall
```

### Commit path (automatic, agent does not participate)

```mermaid
flowchart TD
  AgentRun["AgentLoop._run_agent_loop"] --> SaveTurn["session.save"]
  SaveTurn --> Consol["Consolidator.archive (background, on token-budget trigger)"]
  Consol --> CommitB["asyncio.create_task: sidecar.commit_bullets"]

  CronTick["Cron 2h or /dream"] --> DreamRun["Dream.run"]
  DreamRun --> Phase1["Phase-1 LLM produces [USER]/[MEMORY]/[SOUL] tags"]
  Phase1 --> CommitC["asyncio.create_task: sidecar.commit_dream_tags"]
  Phase1 --> Phase2["Dream Phase 2 file edits (unchanged)"]
```

---

## 3. What Gets Written, Who Controls It

Two — and only two — channels write to MGP:

| Channel                  | Trigger                                       | Content written                                                                                     | Toggle                              |
| ------------------------ | --------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------- |
| Consolidator bullets     | Token budget exceeded / autocompact / `/new`  | LLM-extracted bullets from `consolidator_archive.md` — one `MemoryCandidate` per bullet             | `mgp.enable_consolidator_commit`    |
| Dream Phase-1 tags       | Cron every 2h / `/dream`                      | LLM-extracted `[USER]` / `[MEMORY]` / `[SOUL]` lines from `dream_phase1.md`                         | `mgp.enable_dream_commit`           |

**Tag → MGP `(scope, type)` mapping** for Dream Phase-1 commits:

| Dream tag  | MGP scope | MGP memory type | Note                                           |
| ---------- | --------- | --------------- | ---------------------------------------------- |
| `[USER]`   | `user`    | `preference`    | User-specific facts                            |
| `[MEMORY]` | `agent`   | `semantic_fact` | Stable shared knowledge surfaced by Dream      |
| `[SOUL]`   | `agent`   | `profile`       | Agent identity / persona — `identity` is not a valid MGP type |

Memory types align with the MGP spec's `supported_memory_types` set; the gateway rejects any other type with `MGP_INVALID_OBJECT`.

**Never written to MGP**: raw user messages, raw assistant replies, tool call results, LLM `<thinking>`, `history.jsonl` entries themselves, the contents of `MEMORY.md` / `SOUL.md` / `USER.md`, media attachments, API keys, secrets.

---

## 4. What Doesn't Change

When MGP is enabled, **all native memory behaviors stay exactly as-is**: `MEMORY.md` / `SOUL.md` / `USER.md` are still bulk-injected each turn, `history.jsonl` still serves `grep` lookups, Dream still edits local files and commits via git, autocompact still compresses idle sessions, and every existing slash command (`/dream`, `/dream-log`, `/dream-restore`, …) works unchanged.

If MGP is disabled (the default) or unreachable at runtime, the agent behaves **byte-identically** to a build without MGP.

---

## 5. Quickstart

```bash
# 1. Install nanobot's MGP client extra (~one extra dep)
pip install "nanobot[mgp]"

# 2. Install the MGP gateway with your chosen adapter
pip install "mgp-gateway[postgres]>=0.1.1"

# 3. Run a Postgres for the gateway
docker run -d --name mgp-pg \
  -e POSTGRES_USER=mgp -e POSTGRES_PASSWORD=mgp -e POSTGRES_DB=mgp \
  -p 5432:5432 postgres:16

# 4. Start the gateway
MGP_ADAPTER=postgres \
MGP_POSTGRES_DSN='postgresql://mgp:mgp@127.0.0.1:5432/mgp' \
mgp-gateway
```

Enable MGP in your nanobot config:

```yaml
agents:
  defaults:
    mgp:
      enabled: true
      gateway_url: "http://127.0.0.1:8080"
      # Recommended for SDK / CLI use: pin a stable subject id so Dream
      # `[USER]` facts land where CLI sessions can find them.
      default_user_id: "alice"
```

Restart nanobot and run `/mgp-status` to verify. Other adapters (`oceanbase`, `lancedb`, `mem0`, `zep`) and embedding configuration: see the [MGP nanobot integration guide](https://github.com/HKUDS/MGP/blob/main/integrations/nanobot/README.md#gateway-side-configuration-applies-to-both-paths).

---

## 6. Configuration Reference (nanobot side)

All fields live under `agents.defaults.mgp`.

| Field                          | Default                  | Purpose                                                                                                            |
| ------------------------------ | ------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `enabled`                      | `false`                  | Master switch. Off = no MGP code path runs at all.                                                                 |
| `gateway_url`                  | `http://127.0.0.1:8080`  | MGP gateway HTTP base URL.                                                                                         |
| `timeout`                      | `5.0`                    | Per-request timeout (seconds).                                                                                     |
| `fail_open`                    | `true`                   | Swallow MGP errors so a degraded gateway never breaks a turn.                                                      |
| `workspace_as_tenant`          | `true`                   | Use the workspace path as `tenant_id` when `tenant_id` is unset.                                                   |
| `tenant_id`                    | `null`                   | Explicit tenant id. Wins over `workspace_as_tenant`.                                                               |
| `actor_agent`                  | `nanobot/main`           | Identity recorded in MGP's audit log.                                                                              |
| `api_key`                      | `null`                   | Bearer token (for gateways with `auth_mode=api_key`).                                                              |
| `enable_consolidator_commit`   | `true`                   | Mirror Consolidator bullets to MGP.                                                                                |
| `enable_dream_commit`          | `true`                   | Mirror Dream Phase-1 tags to MGP.                                                                                  |
| `recall_default_scope`         | `"user"`                 | Default `scope` when the agent omits it in `recall_memory(...)`.                                                   |
| `recall_default_limit`         | `5`                      | Default `limit` when the agent omits it. Capped at 20.                                                             |
| `default_user_id`              | `null`                   | Stable subject id used by Dream commits and CLI direct sessions when no real per-user identifier exists. Falls back to `getpass.getuser()` when null. **Set this in SDK / multi-tenant deployments.** |

There is **no `mode` / `shadow` field** here — recall is agent-driven, so there is no auto-injection vs no-injection toggle. Granular control is through the two `enable_*_commit` flags.

### Subject (`user_id`) derivation

Per-call priority:

1. `sender_id` from the inbound message (e.g. group-chat member id from Telegram / Discord / Slack).
2. `chat_id` if it is not a synthetic placeholder (`direct`, `dream`, `user`).
3. `mgp.default_user_id` from your config.
4. `getpass.getuser()` (the OS login).

**Why this matters**: Dream runs at workspace scope and uses the synthetic `chat_id="dream"`. Without a configured `default_user_id`, every Dream `[USER]` fact would land under subject `"dream"` (or `getpass.getuser()`) — not under the subject your CLI/channel session uses for recall, making those facts effectively unreachable. Always set `default_user_id` for SDK deployments.

For group chats, the inbound `sender_id` is plumbed through `_set_tool_context` in `agent/loop.py`, so each member gets their own user-scoped memory island even though the `chat_id` is shared.

---

## 7. `recall_memory` Tool

The agent sees the [`mgp-memory` skill](../../skills/mgp-memory/SKILL.md) in every system prompt; that skill teaches it when to call the tool. From the agent's perspective:

```python
recall_memory(
    query="indentation preference",   # required: concise topic, NOT a full question
    scope="user",                     # optional: "user" / "agent" / "session"
    limit=5,                          # optional: 1..20
    types=["preference"],             # optional: filter by memory types
)
```

Returns formatted bullet lines, `(no memories found)`, or `[recall_memory degraded: <code>]` when the gateway failed (fail-open path).

Full guidance lives in [`nanobot/skills/mgp-memory/SKILL.md`](../../skills/mgp-memory/SKILL.md).

---

## 8. Slash Commands and Reliability

`/mgp-status` reports `enabled`, `gateway_url`, last recall (query, latency, hit count, error if any), and the last 32 commit outcomes. When MGP is disabled, it returns a one-liner pointing here.

**Fail-open by default.** Any MGP error (HTTP timeout, gateway 500, schema validation failure) is swallowed and surfaced to the agent as `[recall_memory degraded: <code>]`. The conversation never dies because of an MGP problem. Set `mgp.fail_open: false` only if you want hard failures.

**Privacy.** When `mgp.enabled: false` (default) nanobot does not import `mgp_client` and does not contact any gateway — full air-gap. When enabled, the **agent-constructed `query`** (a topic, not the user's raw message) is sent to the gateway during recall; only LLM-extracted bullets / tags are sent during commit. Raw conversation text is never sent.

For gateway-side adapter selection, embedding configuration, authentication, and troubleshooting (`MGP_INVALID_OBJECT`, `PolicyDeniedError`, `401`, …): see the [MGP nanobot integration guide](https://github.com/HKUDS/MGP/blob/main/integrations/nanobot/README.md).
