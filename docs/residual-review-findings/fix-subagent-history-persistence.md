# Residual Review Findings

Run: code review of branch `fix/subagent-history-persistence` (ce-code-review run 20260807-220107-61986d85, base bd8d3ad).

## Residual Review Findings

- [P2] `nanobot/agent/subagent_transcript.py:150` — Atomic JSONL write duplicated from `MemoryStore._write_entries` — filed as [HKUDS/nanobot#5290](https://github.com/HKUDS/nanobot/issues/5290)
- [P1] `nanobot/agent/subagent.py:436` — Process death mid-run loses the transcript (no incremental persistence) — deferred by design (human-owned)
- [P2] `nanobot/agent/subagent_transcript.py:24` — Transcripts with tool-output secrets readable by subagents; no TTL/scrub — deferred by design (human-owned)
- [P2] announce `transcript_path` metadata dropped before reaching the main agent model context (agent-native gap) — acceptable per plan R4; noted for future tooling
- [P2] Transcript re-read can replay prompt-injection payloads with no runtime untrusted marker — documented as untrusted; runtime marker is follow-up
- [P3] `tests/agent/test_subagent.py:251` — Test lines exceed the 100-char standard (advisory)

Coverage: cross-model adversarial pass not run (host serving family un-attestable); in-process adversarial fallback used. All 4 P0/P1 findings independently validated.
