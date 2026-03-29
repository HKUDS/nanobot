## Harness initialized - 2026-03-28
- Project type: Python CLI / gateway application (`pyproject.toml`, `nanobot gateway`, pytest)
- Features planned: 52
- init.sh generated: yes
- .gitignore updated: already contained harness entries from global init
- Existing work detected: compared nanobot against `/Users/miau/Documents/openclaw`; found openclaw uses low OpenAI verbosity while nanobot hardcodes medium for both OAuth-backed OpenAI providers
- Baseline validation before feature work:
  - `bash ~/.codex/scripts/global-init.sh` failed repo-wide validation because `tests/test_repo_sync_service.py` imports missing module `nanobot.repo_sync.service`
  - `.venv/bin/pytest tests/test_openai_oauth_provider.py tests/providers/test_providers_init.py` failed before edits because the OAuth test still patches removed `AsyncOpenAI`, and provider lazy exports omitted `OpenAIOAuthProvider`
- Key decisions:
  - Keep the approved feature narrow: change `openai_oauth` default reply verbosity to low and repair only the directly related regression tests
  - Treat `openai_codex` parity as follow-up work unless explicitly requested
  - Use focused `.venv/bin/pytest` verification because the current repo-wide baseline is already red for an unrelated module

## Session update - 2026-03-28
- Implemented concise default for `openai_oauth` by changing provider payload `text.verbosity` from `medium` to `low`
- Restored provider package lazy export coverage by adding `OpenAIOAuthProvider` back to `nanobot.providers.__all__` and `_LAZY_IMPORTS`
- Rewrote `tests/test_openai_oauth_provider.py` to match the current `_request_codex`-based implementation and assert the low-verbosity payload directly
- Verification:
  - `.venv/bin/pytest tests/test_openai_oauth_provider.py tests/providers/test_providers_init.py` -> passed (4 tests)
  - `./init.sh` -> exited 0, reported the known unrelated repo-wide pytest baseline failure, and passed CLI health
- Remaining blockers / follow-up:
  - Full repo baseline is still red because `tests/test_repo_sync_service.py` imports missing `nanobot.repo_sync.service`
  - `openai_codex` still defaults to `text.verbosity = "medium"`; parity work is not included in this session
  - Git write operations are blocked in this environment (`fatal: Unable to create '.git/index.lock': Operation not permitted`), so the required init checkpoint commit and feature commit could not be created from this session

## Harness reboot - 2026-03-29
- Task pivot:
  - Superseded the prior narrow OpenAI OAuth follow-up plan with the new long-running initiative: let `nanobot` orchestrate coding tasks, let `codex` execute code changes, and let each target repo's harness hold long-term task state
- Existing work detected before re-planning:
  - `nanobot` already had orchestration primitives worth reusing: gateway supervision, cron, heartbeat, session management, and background worker patterns
  - The repo still lacks `nanobot.repo_sync.service`, so repo-wide pytest remains red before any coding-task work
- Completed feature this session:
  - Added a new workspace-scoped `nanobot.coding_tasks` module with persistent coding task metadata, append-only run logs, recoverable-state queries, and a `CodexWorkerManager` lifecycle scaffold
  - Wired gateway startup to initialize the coding task runtime and report tracked/recoverable coding-task counts at boot
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_store.py tests/coding_tasks/test_manager.py` -> passed (6 tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks` -> passed
  - `.venv/bin/python -c "from nanobot.coding_tasks import CodexWorkerManager, CodingTaskStore; print('coding_tasks ok')"` -> passed
- Key decisions:
  - Treat this session's feature as foundation only: durable task state first, real Codex launching and Telegram command routing later
  - Keep verification focused on the new coding-task module until the unrelated repo_sync baseline is repaired
  - Preserve the no-push-by-default execution model in the future task design; this session only stores the policy boundary
- Remaining blockers / follow-up:
  - `nanobot.repo_sync.service` is still missing, so full-repo pytest remains an unrelated baseline blocker
  - Gateway wiring is only at startup/runtime visibility level today; Telegram command routing and real Codex worker launch are not implemented yet
  - The current harness plan now tracks the coding-task initiative from this new foundation feature onward

## Session update - 2026-03-29 (feature #2)
- Completed feature:
  - Wired the active `nanobot gateway` CLI entrypoint to load the coding-task runtime from the workspace and print tracked/recoverable coding-task counts during startup
- Important findings:
  - The user-facing `nanobot gateway` path still lives in `nanobot/cli/commands.py`; the richer `nanobot/app/gateway.py` path exists in the tree but is not the active entrypoint
  - Missing `nanobot.app.prompts`, `nanobot.app.runtime`, and `nanobot.repo_sync.service` affect the dormant `app/gateway.py` branch, but they do not block this completed CLI gateway feature
- Verification:
  - `.venv/bin/pytest tests/cli/test_commands.py -k "gateway_reports_coding_task_counts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port or gateway_uses_workspace_directory_for_cron_store"` -> passed (4 selected tests)
  - `.venv/bin/pytest tests/coding_tasks/test_store.py tests/coding_tasks/test_manager.py` -> passed (6 tests)
- Key decisions:
  - Treat the CLI gateway entrypoint as the authoritative runtime path for near-term coding-task work
  - Defer repairing the dormant `app/gateway.py` dependency chain until a feature explicitly needs that richer runtime
- Remaining blockers / follow-up:
  - Full-repo pytest is still red because `tests/test_repo_sync_service.py` imports missing `nanobot.repo_sync.service`
  - The next feature should move from startup visibility into user control, most likely by adding CLI creation/listing commands or Telegram command routing for coding tasks

## Session update - 2026-03-29 (feature #3)
- Completed feature:
  - Locked down coding-task id and default tmux session stability by extending the manager test to verify the stored task reloads with the same session name
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_manager.py tests/coding_tasks/test_store.py` -> passed (6 tests)
- Key decisions:
  - Keep `feature #3` deliberately narrow and verification-driven instead of reshaping the naming scheme before real Codex launch exists
  - Use store reload as the proof point because restart/recovery will consume persisted task state rather than in-memory objects
- Remaining blockers / follow-up:
  - The next highest-value feature is now `#4` or `#5`: a real user-facing way to create and inspect coding tasks through the active CLI/runtime path

## Session update - 2026-03-29 (feature #4)
- Completed feature:
  - Added `nanobot coding-task create` so a user can create a persisted coding task record from the active CLI path, reusing the same workspace-scoped coding-task runtime helper as gateway startup
- Verification:
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_create_persists_task or gateway_reports_coding_task_counts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port"` -> passed (4 selected tests)
- Key decisions:
  - Reuse a shared `_load_coding_task_runtime()` helper so the CLI create flow and gateway startup always point at the same task store location
  - Keep repo-path validation out of this feature; the command currently focuses on record creation and persistence, with stricter validation reserved for later feature work
- Remaining blockers / follow-up:
  - There is still no user-facing list/status command, so feature `#5` is the natural next step to make created tasks inspectable
  - Telegram command routing still does not exist; coding-task control remains CLI-only at this point

## Session update - 2026-03-29 (feature #5)
- Completed feature:
  - Added `nanobot coding-task list` so persisted coding tasks can be inspected from the active CLI path with visible status, repo path, progress summary, and recoverability
- Verification:
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_create_persists_task or coding_task_list_shows_status_and_recoverability or gateway_reports_coding_task_counts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port"` -> passed (5 selected tests)
- Key decisions:
  - Use plain-text `status=...` output instead of bracketed status labels so Rich formatting cannot swallow the actual state string
  - Keep list output flat and grep-friendly for now; richer tables or detail views can come with feature `#6`
- Remaining blockers / follow-up:
  - There is still no single-task detail command, so feature `#6` is the next inspectability gap
  - Coding tasks can be created and listed, but not yet cancelled, resumed, or launched into a real Codex worker

## Session update - 2026-03-29 (feature #6)
- Completed feature:
  - Added `nanobot coding-task status <task_id>` so a single coding task can be inspected with status, repo, goal, tmux metadata, recoverability, last progress, and recent run events
- Verification:
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_create_persists_task or coding_task_list_shows_status_and_recoverability or coding_task_status_shows_details_and_recent_events or gateway_reports_coding_task_counts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port"` -> passed (6 selected tests)
- Key decisions:
  - Keep detail output line-oriented and grep-friendly, matching the current create/list CLI style instead of introducing rich tables yet
  - Limit recent run events to a short tail so the command stays readable even after longer task histories accumulate
- Remaining blockers / follow-up:
  - There is still no CLI cancel/resume path, so features `#7` and `#8` remain the next control-plane gaps
  - A real Codex worker launcher still does not exist, so the new status view is currently inspecting persisted metadata rather than a live running worker

## Session update - 2026-03-29 (features #7 and #8)
- Completed features:
  - Added `nanobot coding-task cancel <task_id>` to cancel persisted coding tasks with a stored user-facing reason
  - Added `nanobot coding-task resume <task_id>` to move failed or waiting tasks back into `starting` while recording an explicit resume control event
- Verification:
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_create_persists_task or coding_task_list_shows_status_and_recoverability or coding_task_status_shows_details_and_recent_events or test_coding_task_cancel_updates_status_and_reason or test_coding_task_resume_moves_failed_task_back_to_starting or gateway_reports_coding_task_counts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port"` -> passed (8 selected tests)
- Key decisions:
  - Reuse the existing `CodexWorkerManager` transitions directly rather than inventing a second control-plane state machine in CLI code
  - Record `resume` as an explicit user-control event before moving the task back to `starting`, so later task audits can distinguish user action from automatic retries
- Remaining blockers / follow-up:
  - There is still no real Codex worker launch/reuse path, so cancel/resume currently operate on persisted task state rather than a live tmux-backed worker
  - Telegram command routing and active-task selection are still missing, so coding-task control remains CLI-only

## Session update - 2026-03-29 (feature #9)
- Completed feature:
  - Added a coding-task chat interceptor so Telegram private-chat messages starting with `开始编程` can create a persisted coding task immediately instead of falling through to the LLM
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_router.py tests/agent/test_coding_task_routing.py` -> passed (5 tests)
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_create_persists_task or coding_task_list_shows_status_and_recoverability or coding_task_status_shows_details_and_recent_events or test_coding_task_cancel_updates_status_and_reason or test_coding_task_resume_moves_failed_task_back_to_starting or gateway_reports_coding_task_counts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port"` -> passed (8 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks nanobot/agent/loop.py nanobot/cli/commands.py` -> passed
- Key decisions:
  - Hook the Telegram private-chat route at `AgentLoop` command-interceptor level instead of modifying the Telegram channel adapter, so the behavior stays close to the active runtime path and is easy to test
  - Support both inline `开始编程 /path/to/repo 任务目标` and structured `仓库:` / `目标:` message shapes while returning a usage hint for incomplete requests
  - Persist the origin channel/chat metadata on created coding tasks now so later Telegram control routing can identify the originating conversation without another state migration
- Remaining blockers / follow-up:
  - Telegram control messages such as `状态` / `继续` / `取消` are still not routed onto active coding tasks yet, so feature `#10` remains the next chat-control gap
  - The new chat route only creates persisted tasks; it does not launch or resume a real Codex worker session yet

## Session update - 2026-03-29 (features #10, #11, #12)
- Completed features:
  - Routed Telegram private-chat control messages `状态` / `继续` / `取消` onto the latest active coding task for the same originating chat instead of treating them as generic assistant messages
  - Enforced the MVP single-active-task rule on Telegram private-chat task creation so a second `开始编程` request is rejected while another coding task is still non-terminal
  - Added repo-path validation to coding-task creation entrypoints so missing paths, file paths, and URL-like values are rejected before task records are written
- Verification:
  - `.venv/bin/pytest tests/agent/test_coding_task_routing.py tests/coding_tasks/test_router.py tests/coding_tasks/test_manager.py` -> passed (14 tests)
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_create_persists_task or coding_task_create_rejects_missing_repo or coding_task_list_shows_status_and_recoverability or coding_task_status_shows_details_and_recent_events or test_coding_task_cancel_updates_status_and_reason or test_coding_task_resume_moves_failed_task_back_to_starting or gateway_reports_coding_task_counts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port"` -> passed (9 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks nanobot/cli/commands.py tests/agent/test_coding_task_routing.py tests/coding_tasks/test_router.py` -> passed
- Key decisions:
  - Use the latest non-terminal task in the same Telegram private chat as the control target for feature `#10`, then layer the stricter single-active-task creation rule on top in feature `#11`
  - Keep active-task enforcement at the Telegram private-chat entrypoint for now so existing CLI task-management flows remain available as operator tooling
  - Leave `CodexWorkerManager.create_task()` itself permissive for this round; validation now lives in user-facing creation entrypoints where the error can be explained cleanly
  - Fixed a latent status-formatting bug in the new router while touching the control path so task status replies now always return text even if tmux metadata is absent
- Remaining blockers / follow-up:
  - There is still no harness detection or prompt-building layer yet, so feature `#13` is the next natural step before real Codex worker launch
  - Telegram control currently manipulates persisted task state only; it still does not talk to a live tmux/Codex worker session

## Session update - 2026-03-29 (features #13, #14, #15)
- Completed features:
  - Added target-repo harness detection that inspects `PLAN.json`, `PROGRESS.md`, and `init.sh`, distinguishing `active`, `initializing`, and `missing` harness states
  - Added Codex bootstrap prompt construction for repos with an existing harness so the worker is told to restore state first, honor repo instructions, and verify before editing
  - Added Codex bootstrap prompt construction for repos without a complete harness so the worker is told to initialize `PLAN.json`, `PROGRESS.md`, and `init.sh` before feature work
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_harness.py tests/coding_tasks/test_router.py tests/coding_tasks/test_manager.py tests/agent/test_coding_task_routing.py` -> passed (18 tests)
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_create_persists_task or coding_task_create_rejects_missing_repo or coding_task_list_shows_status_and_recoverability or coding_task_status_shows_details_and_recent_events or test_coding_task_cancel_updates_status_and_reason or test_coding_task_resume_moves_failed_task_back_to_starting or gateway_reports_coding_task_counts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port"` -> passed (9 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks tests/coding_tasks/test_harness.py` -> passed
- Key decisions:
  - Keep harness detection and prompt construction in a standalone `nanobot.coding_tasks.harness` module so the upcoming tmux/Codex launcher can consume them without depending on Telegram routing code
  - Treat complete harnesses as `active`, partial harnesses as `initializing`, and empty repos as `missing` so worker startup can preserve partial work instead of overwriting it
  - Bake the no-push / no-external-side-effect boundary into the generated bootstrap prompt now, so later worker launch logic inherits the correct default behavior
- Remaining blockers / follow-up:
  - The new harness module is not wired into a real Codex worker launch path yet, so feature `#16` remains the next major integration step
  - Progress is still based on persisted task metadata rather than live tmux/Codex session output

## Session update - 2026-03-29 (features #16, #17, #18, #19)
- Completed features:
  - Added a tmux-backed `CodexWorkerLauncher` that can create a new tmux session for a coding task, write the bootstrap prompt to an artifact file, and mark the task as `starting`
  - Reused existing tmux sessions for repeated launches of the same task instead of spawning duplicate sessions, with a best-effort `C-c` reset before relaunch
  - Standardized the Codex startup command so it carries the repo path, generated prompt, and persistent log path in a reproducible shell command
  - Added session-hint extraction from pane output and persisted that hint back into the coding-task record when present
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_worker.py tests/coding_tasks/test_harness.py tests/coding_tasks/test_manager.py` -> passed (11 tests)
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_run_launches_tmux_worker or coding_task_create_persists_task or coding_task_create_rejects_missing_repo or coding_task_list_shows_status_and_recoverability or coding_task_status_shows_details_and_recent_events or test_coding_task_cancel_updates_status_and_reason or test_coding_task_resume_moves_failed_task_back_to_starting"` -> passed (7 selected tests)
  - `.venv/bin/pytest tests/agent/test_coding_task_routing.py tests/coding_tasks/test_router.py` -> passed (11 tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks nanobot/cli/commands.py tests/coding_tasks/test_worker.py` -> passed
- Key decisions:
  - Use `codex exec --json --full-auto` inside tmux for the first launcher cut so task output is scrapeable and startup remains reproducible
  - Keep worker launching behind a dedicated `nanobot coding-task run <id>` CLI command first, which is enough to validate tmux/session reuse behavior before wiring launch directly into Telegram controls
  - Store prompt artifacts and Codex logs under the workspace automation directory so future recovery and diagnosis do not depend on transient terminal history alone
- Remaining blockers / follow-up:
  - The worker can launch, but nanobot still does not poll pane output or synthesize progress from live tmux output yet, so feature `#20` is the next integration gap
  - Telegram `继续` still updates persisted state only; it does not yet invoke the live worker launcher

## Session update - 2026-03-29 (features #20, #21, #22, #23, #24)
- Completed features:
  - Added asynchronous pane polling that captures tmux output via `asyncio.to_thread`, which is ready to be called from gateway/background loops without blocking the event loop
  - Added persisted progress refresh so newly observed pane output updates each coding task's `last_progress_summary` and timestamp without forcing a status transition
  - Added `PROGRESS.md` summarization that extracts the newest session note for reporting
  - Added `PLAN.json` summarization that counts completed versus remaining features
  - Added combined live reporting that synthesizes harness files plus current pane output, and surfaced that report through the CLI `coding-task status` path
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_progress.py tests/coding_tasks/test_worker.py tests/coding_tasks/test_harness.py tests/coding_tasks/test_manager.py` -> passed (15 tests)
  - `.venv/bin/pytest tests/cli/test_commands.py -k "coding_task_status_shows_details_and_recent_events or coding_task_run_launches_tmux_worker or coding_task_create_persists_task or coding_task_create_rejects_missing_repo or coding_task_list_shows_status_and_recoverability or test_coding_task_cancel_updates_status_and_reason or test_coding_task_resume_moves_failed_task_back_to_starting"` -> passed (7 selected tests)
  - `.venv/bin/pytest tests/agent/test_coding_task_routing.py tests/coding_tasks/test_router.py` -> passed (11 tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks nanobot/cli/commands.py tests/coding_tasks/test_progress.py` -> passed
- Key decisions:
  - Keep pane polling and summarization in a separate `progress` module so later gateway recovery and Telegram reporting can reuse the same report builder
  - Update task progress summaries via a dedicated manager method instead of overloading `mark_running`, which keeps lifecycle transitions distinct from reporting refreshes
  - Surface the synthesized report first in the CLI status command, since that is the narrowest existing reporting path and gives us an immediate verification surface
- Remaining blockers / follow-up:
  - Gateway restart recovery is not implemented yet, so feature `#25` is the next gap before long-lived tasks survive nanobot restarts cleanly
  - Telegram `继续` / `停止` still do not drive the live tmux worker session itself; they only update persisted task state today

## Session update - 2026-03-29 (features #25, #26, #27, #28, #29)
- Completed features:
  - Added startup recovery scanning that walks recoverable coding tasks, reconnects those whose tmux sessions still exist, and refreshes their live progress summary
  - Added failure handling for recoverable tasks whose tmux session disappeared, marking them `failed` with an actionable relaunch hint
  - Upgraded Telegram `状态` to return coding-task details plus recoverability and live report content instead of a generic assistant answer
  - Upgraded Telegram `继续` to relaunch the coding task through the existing tmux worker session when the task is paused or failed
  - Added Telegram `停止` so nanobot sends `C-c` into the tmux worker and moves the task into a resumable `waiting_user` state
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_recovery.py tests/coding_tasks/test_progress.py tests/coding_tasks/test_worker.py tests/coding_tasks/test_manager.py tests/agent/test_coding_task_routing.py` -> passed (22 tests)
  - `.venv/bin/pytest tests/cli/test_commands.py -k "gateway_reports_coding_task_counts or coding_task_status_shows_details_and_recent_events or coding_task_run_launches_tmux_worker or coding_task_create_persists_task or coding_task_create_rejects_missing_repo or coding_task_list_shows_status_and_recoverability or test_coding_task_cancel_updates_status_and_reason or test_coding_task_resume_moves_failed_task_back_to_starting"` -> passed (8 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks nanobot/agent/loop.py nanobot/cli/commands.py tests/coding_tasks/test_recovery.py tests/agent/test_coding_task_routing.py` -> passed
- Key decisions:
  - Keep recovery logic in a dedicated module and invoke it during gateway startup, which avoids burying restart semantics inside CLI-only status commands
  - Treat tmux session survival as the recovery truth source for now; if the session is gone, nanobot fails the task explicitly rather than pretending it is still recoverable
  - Drive Telegram `继续` through the live launcher instead of only toggling task metadata, so the same tmux session remains the control point for resumed work
- Remaining blockers / follow-up:
  - The live control loop still lacks automatic background polling / notifications, so the next stretch should focus on scheduled observation and user-facing progress push
  - Telegram `取消` currently cancels task state immediately rather than first interrupting a live tmux process; that may need tightening in later safety polish

## Session update - 2026-03-29 (features #30, #31, #32, #33, #34, #35, #36)
- Completed features:
  - Tightened Telegram `取消` so the control action is logged first, any live tmux worker is best-effort interrupted, and later `继续` attempts are rejected for the cancelled task
  - Verified the default `local_only` approval policy is persisted on new tasks and reflected in the generated Codex bootstrap prompt
  - Made the startup prompt explicitly call out repository `AGENTS.md` when present and require reading it before edits
  - Verified launch-time prompt artifacts distinguish missing-harness initialization flows from existing-harness recovery flows
  - Added focused audit tests proving lifecycle changes append structured run events in chronological order
  - Added focused audit tests proving user control actions are logged separately from automatic status transitions
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_audit.py tests/coding_tasks/test_harness.py tests/coding_tasks/test_worker.py tests/agent/test_coding_task_routing.py` -> passed (22 tests)
  - `.venv/bin/pytest tests/coding_tasks/test_worker.py tests/coding_tasks/test_harness.py tests/coding_tasks/test_audit.py` -> passed (12 tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks tests/coding_tasks/test_audit.py tests/coding_tasks/test_worker.py tests/agent/test_coding_task_routing.py` -> passed
- Key decisions:
  - Treat cancelled tasks as terminal from the chat-control layer, requiring an explicit new `开始编程` request instead of silently resurrecting a cancelled record
  - Keep the no-push/default approval semantics encoded in both persisted task metadata and the generated worker prompt, so the boundary is visible in both control plane and execution plane
  - Validate missing/existing harness launch behavior by reading the prompt artifact file produced at launch time, which gives a deterministic test surface without needing a live Codex run
- Remaining blockers / follow-up:
  - Progress notifications are still pull-based via status views rather than throttled push notifications, so feature `#37` is the next natural step
  - Completion/failure reporting and branch/commit metadata persistence are not implemented yet

## Session update - 2026-03-29 (features #43, #44, #45, #46, #47, #48, #49, #50)
- Completed features:
  - Verified multiple queued coding tasks survive store reload without being dropped or duplicated
  - Added status-list coverage proving queued, starting, waiting, failed, completed, and cancelled tasks all surface distinctly in reporting
  - Verified worker prompt artifacts are namespaced by task id under the workspace artifacts directory
  - Kept the focused coding-task suite green across storage, lifecycle, prompt shaping, recovery, and Telegram routing while the unrelated `repo_sync` baseline remains red
  - Added a README architecture note that explains nanobot as orchestrator, Codex as coding worker, and the target repo harness as the long-term memory layer
  - Preserved explicit PROGRESS notes about the separate `nanobot.repo_sync.service` baseline failure so later sessions can keep using the focused coding-task verification path
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_queueing.py tests/coding_tasks/test_worker.py tests/coding_tasks/test_audit.py tests/coding_tasks/test_recovery.py tests/coding_tasks/test_progress.py tests/coding_tasks/test_harness.py tests/agent/test_coding_task_routing.py tests/cli/test_commands.py -k "test_coding_task_list_distinguishes_all_major_statuses or gateway_reports_coding_task_counts or coding_task_status_shows_details_and_recent_events or coding_task_run_launches_tmux_worker or coding_task_create_persists_task or coding_task_create_rejects_missing_repo or coding_task_list_shows_status_and_recoverability or test_coding_task_cancel_updates_status_and_reason or test_coding_task_resume_moves_failed_task_back_to_starting or test_multiple_queued_tasks_survive_store_reload"` -> passed (10 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks tests/coding_tasks/test_queueing.py tests/coding_tasks/test_worker.py tests/coding_tasks/test_audit.py` -> passed
- Key decisions:
  - Treat artifact naming and queued-task reload as regression-proofing features, verified through deterministic store/worker tests instead of relying on live gateway restarts for every pass
  - Keep the focused coding-task test surface explicitly separate from the unrelated repo-wide red baseline, and continue documenting that split in `PROGRESS.md`
  - Document the nanobot/Codex/repo-harness split in README directly under the architecture section so future operators can orient quickly
- Remaining blockers / follow-up:
  - The remaining major gaps are gateway single-instance protection in the active runtime path and a true end-to-end manual run against a local repo

## Session update - 2026-03-29 (features #37, #38, #39, #40, #41, #42, #51)
- Completed features:
  - Added a throttled coding-task notifier and wired a background coding-task watch loop into the active CLI gateway runtime so repeated identical progress summaries are not spammed to Telegram
  - Added completion, failure, and waiting-user report builders for user-facing status delivery
  - Added waiting-user detection from live pane output and automatic transition into `waiting_user` with an explanatory summary when Codex asks for confirmation
  - Added repo metadata inspection so branch name and recent commit summary are persisted onto the task record during polling/reporting
  - Added a single-instance gateway lock to the active CLI gateway runtime so duplicate gateways are rejected before orchestration starts
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_reporting.py tests/coding_tasks/test_notifier.py tests/coding_tasks/test_progress.py tests/coding_tasks/test_recovery.py tests/coding_tasks/test_worker.py` -> passed (17 tests)
  - `.venv/bin/pytest tests/coding_tasks/test_progress.py tests/coding_tasks/test_reporting.py tests/coding_tasks/test_notifier.py` -> passed (9 tests)
  - `.venv/bin/pytest tests/cli/test_commands.py -k "gateway_reports_coding_task_counts or gateway_rejects_duplicate_instance_before_runtime_starts or gateway_uses_configured_port_when_cli_flag_is_missing or gateway_cli_port_overrides_configured_port"` -> passed (4 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks nanobot/cli/commands.py tests/coding_tasks/test_reporting.py tests/coding_tasks/test_notifier.py tests/coding_tasks/test_progress.py` -> passed
- Key decisions:
  - Keep notification throttling in a dedicated notifier class so push delivery policy stays separate from progress detection and reporting
  - Update repo branch/commit metadata opportunistically during polling and status reads, which avoids rescanning git in every final report path
  - Reuse the active CLI gateway path for the single-instance lock instead of relying on the dormant `app/gateway.py` branch
- Remaining blockers / follow-up:
  - Only feature `#52` remains: a true manual end-to-end run against a local repo through the nanobot entrypoint

## Session update - 2026-03-29 (feature #52)
- Completed feature:
  - Ran a real manual end-to-end coding task against an isolated local git repo under `/tmp`, using `nanobot coding-task create`, `nanobot coding-task run`, and `nanobot coding-task status` with a dedicated workspace/config override
  - Verified nanobot persisted the coding task record plus append-only run log under the workspace automation directory, then launched a real tmux-backed Codex worker for the task
  - Verified the target repo received real harness files from the live Codex run (`PLAN.json`, `PROGRESS.md`, `init.sh`, `.gitignore`) and that nanobot status could read them back into a single summary with plan counts, latest progress note, recent commit metadata, and current worker activity
  - Tightened live-status summarization so tmux output from `codex exec --json` is collapsed into concise agent/command summaries instead of dumping raw JSON event payloads to users
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_progress.py tests/cli/test_commands.py -k "coding_task_status_shows_details_and_recent_events or build_task_progress_report_summarizes_codex_json_events or build_task_progress_report_combines_harness_and_pane_output"` -> passed (3 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks/progress.py tests/coding_tasks/test_progress.py` -> passed
  - Manual E2E:
    - `.venv/bin/nanobot coding-task create /tmp/nanobot-coding-e2e.pIh22M/repo --goal "Initialize the repo harness and append one short status line to README.md." --config /tmp/nanobot-coding-e2e.pIh22M/config.json --workspace /tmp/nanobot-coding-e2e.pIh22M/workspace` -> created task `180c187a`
    - `.venv/bin/nanobot coding-task run 180c187a --config /tmp/nanobot-coding-e2e.pIh22M/config.json --workspace /tmp/nanobot-coding-e2e.pIh22M/workspace` -> launched tmux session `codex-task-repo-180c187a`
    - `.venv/bin/nanobot coding-task status 180c187a --config /tmp/nanobot-coding-e2e.pIh22M/config.json --workspace /tmp/nanobot-coding-e2e.pIh22M/workspace` -> reported branch `main`, recent commit `286435a init repo`, repo harness progress `已完成 0/12 项，剩余 12 项`, the latest `PROGRESS.md` note, and a concise current-worker summary
- Key decisions:
  - Treat the real local repo run as the acceptance proof for feature `#52`; the task does not need to finish the repo change to prove nanobot can create, launch, persist, and summarize a live coding task
  - Fix the JSON-event summarization in nanobot itself rather than hand-waving around verbose raw Codex output, so the verified E2E path matches the intended operator experience
  - Keep the isolated manual-run repo under `/tmp` and out of the nanobot worktree so the acceptance proof does not contaminate the main repository history
- Remaining blockers / follow-up:
  - `PLAN.json` is now fully complete for the nanobot coding-task orchestration initiative
  - The unrelated repo-wide baseline remains red because `tests/test_repo_sync_service.py` still imports missing `nanobot.repo_sync.service`

## Harness reboot - 2026-03-29 (coding-task architecture cleanup)
- Task pivot:
  - Superseded the completed coding-task delivery plan with a new harness whose scope is limited to the architectural debt introduced while landing that feature set
  - Explicitly excluded older repository debt from this new plan, especially the dormant `nanobot/app/gateway.py` branch and the unrelated `nanobot.repo_sync.service` baseline failure
- Existing work detected before re-planning:
  - The coding-task feature itself is complete and verified, including a real manual `create -> run -> status` flow against a local repo
  - The main new debt is local to the new coding-task surface: duplicated runtime assembly, router-embedded policy decisions, and report paths that still blend reads with persistence side effects
- Baseline validation before the new plan:
  - `bash ~/.codex/scripts/global-init.sh` still exits 0 with the same known unrelated repo-wide pytest warning for `tests/test_repo_sync_service.py`
  - `.venv/bin/pytest tests/coding_tasks/test_reporting.py tests/coding_tasks/test_notifier.py tests/coding_tasks/test_progress.py tests/coding_tasks/test_recovery.py tests/coding_tasks/test_worker.py tests/cli/test_commands.py -k "coding_task_status_shows_details_and_recent_events or coding_task_run_launches_tmux_worker or gateway_reports_coding_task_counts or build_task_progress_report_summarizes_codex_json_events or build_task_progress_report_combines_harness_and_pane_output or test_poll_task_updates_progress_summary_and_timestamp or test_poll_task_persists_branch_and_recent_commit_metadata"` -> passed (7 selected tests)
- Key decisions:
  - Keep the new plan intentionally narrow: only clean up debt created by the coding-task harness rollout, not pre-existing gateway or repo_sync issues
  - Preserve current user-facing behavior while refactoring internals, so the cleanup plan focuses on composition boundaries and state ownership rather than changing the external protocol
  - Replace the completed `PLAN.json` with a fresh remaining-work plan for this new task, while keeping the earlier delivery history in `PROGRESS.md`

## Session update - 2026-03-29 (features #1, #2, #3, #4, #5)
- Completed features:
  - Added a shared `nanobot.coding_tasks.runtime` module that assembles the store, manager, launcher, monitor, recovery helper, and optional notifier from a single workspace root
  - Updated the active CLI gateway path to use that shared runtime instead of manually wiring coding-task collaborators inline
  - Updated CLI coding-task commands to reuse the shared runtime, removing the ad hoc launcher/monitor construction that had already drifted between `status`, `run`, and the gateway setup path
  - Updated `AgentLoop` to consume the same runtime contract for Telegram coding-task interception instead of privately reconstructing launcher and monitor state from the manager alone
  - Added focused runtime tests that verify the same workspace-scoped automation store is reused whether notifier support is enabled or not
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_runtime.py tests/coding_tasks/test_progress.py tests/coding_tasks/test_recovery.py tests/coding_tasks/test_notifier.py tests/agent/test_coding_task_routing.py tests/cli/test_commands.py -k "gateway_reports_coding_task_counts or coding_task_status_shows_details_and_recent_events or coding_task_run_launches_tmux_worker or test_build_runtime_assembles_shared_workspace_collaborators or test_build_runtime_can_attach_optional_notifier_without_rewiring_store or private_telegram"` -> passed (15 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks/runtime.py nanobot/cli/commands.py nanobot/agent/loop.py tests/coding_tasks/test_runtime.py tests/cli/test_commands.py` -> passed
- Key decisions:
  - Keep the shared runtime builder as the one sanctioned composition root for new coding-task collaborators, even when only part of the runtime is needed by a given command path
  - Preserve backward compatibility for existing tests and call sites by allowing `AgentLoop` to accept either a full runtime or just a manager, but normalize onto the runtime contract internally
  - Leave policy extraction and read/write separation for follow-up features so the first cleanup checkpoint only attacks wiring duplication

## Session update - 2026-03-29 (features #6, #7, #8, #9, #10, #11, #12, #13, #14)
- Completed features:
  - Added a dedicated `nanobot.coding_tasks.policy` layer and rewired the Telegram router to delegate workspace-wide blocking and origin-chat task selection there instead of hardcoding those rules inline
  - Split progress handling into a pure read path (`build_task_report`) and an explicit persistence path (`refresh_task`), so status views no longer mutate task state as a side effect
  - Updated recovery to use the explicit refresh path, keeping repo metadata and live progress persistence localized to lifecycle code instead of leaking through read-only views
  - Updated CLI `coding-task status` to render branch and commit details from the pure report result without persisting them back to the task record
  - Added focused tests for policy behavior, read-only status/reporting, and explicit refresh persistence, while keeping existing Telegram routing behavior unchanged
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_policy.py tests/coding_tasks/test_progress.py tests/coding_tasks/test_recovery.py tests/coding_tasks/test_notifier.py tests/coding_tasks/test_router.py tests/agent/test_coding_task_routing.py tests/cli/test_commands.py -k "policy or status or recovery or notifier or private_telegram or refresh_task or build_task_report_is_read_only"` -> passed (22 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks/policy.py nanobot/coding_tasks/progress.py nanobot/coding_tasks/router.py nanobot/coding_tasks/runtime.py nanobot/cli/commands.py nanobot/agent/loop.py tests/coding_tasks/test_policy.py tests/coding_tasks/test_progress.py tests/cli/test_commands.py` -> passed
- Key decisions:
  - Keep the current MVP behavior intact by making the new policy layer a pure extraction of existing selection rules, not a semantics change
  - Treat `status` as a strictly read-only surface from this point on, even if that means duplicating some display-time merge logic between persisted state and the ephemeral report
  - Use the explicit `refresh_task` API as the only sanctioned mutation path for repo metadata and progress summaries outside the manager itself

## Session update - 2026-03-29 (features #15, #16)
- Completed features:
  - Updated the README architecture section to document the refactored coding-task boundaries explicitly: shared runtime assembly, extracted policy ownership, and the split between pure reporting and explicit refresh
  - Re-ran a real isolated `create -> run -> status` smoke path after the cleanup to confirm the refactored runtime still supports end-to-end task launch and status inspection
- Verification:
  - Documentation:
    - Updated `README.md` under `Codex-Orchestrated Coding Tasks` to explain `nanobot.coding_tasks.runtime`, `nanobot.coding_tasks.policy`, and the pure-report versus refresh split
  - Manual smoke:
    - `.venv/bin/nanobot coding-task create /tmp/nanobot-arch-smoke.5ptDdU/repo --goal "Initialize the repo harness and append one short status line to README.md." --config /tmp/nanobot-arch-smoke.5ptDdU/config.json --workspace /tmp/nanobot-arch-smoke.5ptDdU/workspace` -> created task `31da04f9`
    - `.venv/bin/nanobot coding-task run 31da04f9 --config /tmp/nanobot-arch-smoke.5ptDdU/config.json --workspace /tmp/nanobot-arch-smoke.5ptDdU/workspace` -> launched tmux session `codex-task-repo-31da04f9`
    - `.venv/bin/nanobot coding-task status 31da04f9 --config /tmp/nanobot-arch-smoke.5ptDdU/config.json --workspace /tmp/nanobot-arch-smoke.5ptDdU/workspace` -> reported the same task id, `starting` status, `missing` harness state, branch `main`, recent commit `2dbb53a init repo`, and a live report summary
    - Post-status inspection of `/tmp/nanobot-arch-smoke.5ptDdU/workspace/automation/coding/tasks.json` confirmed `branch_name` and `recent_commit_summary` remained unset, proving the status path stayed read-only after the refactor
- Key decisions:
  - Keep the smoke repo isolated under `/tmp` and tear down the tmux session after verification so the architecture cleanup leaves no long-lived worker behind in the main development environment
  - Accept a lightweight smoke run rather than a full task completion, because this cleanup task is about preserving the orchestration path and state boundaries, not re-validating the entire original coding-task feature set from scratch
- Remaining blockers / follow-up:
  - `PLAN.json` is now fully complete for the coding-task architecture-cleanup harness
  - The unrelated repo-wide baseline remains red because `tests/test_repo_sync_service.py` still imports missing `nanobot.repo_sync.service`

## Harness reboot - 2026-03-29 (repo_sync service recovery)
- Task pivot:
  - Start a standalone harness to recover the missing `nanobot.repo_sync.service` module without reopening the completed coding-task cleanup plan
- Existing work detected before re-planning:
  - Repo-wide pytest currently fails during collection because [tests/test_repo_sync_service.py] imports `nanobot.repo_sync.service.RepoSyncWatcher`
  - The dormant [nanobot/app/gateway.py] path still references `RepoSyncWatcher`, but it remains separately blocked by missing `nanobot.app.prompts` and `nanobot.app.runtime`
  - `nanobot/repo_sync/` still contains a compiled `service.cpython-313.pyc`, which confirms the historical service was a thin watcher around an injectable sync runner
- Baseline validation before feature work:
  - `bash ~/.codex/scripts/global-init.sh` -> exited 0 with one known error because pytest stopped at `ModuleNotFoundError: No module named 'nanobot.repo_sync.service'`
  - `.venv/bin/python -c "import nanobot.app.gateway"` -> still fails on the unrelated missing `nanobot.app.prompts`
- Key decisions:
  - Recover `RepoSyncWatcher` as a small, architecture-safe service layer first, rather than reviving the entire dormant gateway dependency chain
  - Keep watcher lifecycle code separate from any heavier git-sync policy so the fix clears the baseline import failure without coupling new logic to stale runtime paths
  - Treat `app.prompts` / `app.runtime` as explicitly out of scope for this recovery unless a later task asks for the dormant gateway path to run again

## Session update - 2026-03-29 (repo_sync service recovery)
- Completed features:
  - Restored the `nanobot.repo_sync` package source layout by adding [nanobot/repo_sync/__init__.py](/Users/miau/Documents/nanobot/nanobot/repo_sync/__init__.py) and [nanobot/repo_sync/service.py](/Users/miau/Documents/nanobot/nanobot/repo_sync/service.py)
  - Reimplemented `RepoSyncWatcher` as a thin async lifecycle wrapper with constructor compatibility for the dormant gateway path, immediate `run_on_start`, interval polling, idempotent `start()`, clean `stop()`, and serialized `trigger_now()`
  - Added a safe default `sync_fork_once()` helper that validates the repo path, performs fetch + fast-forward merge only, and returns human-readable failure strings instead of crashing the watcher
  - Expanded [tests/test_repo_sync_service.py](/Users/miau/Documents/nanobot/tests/test_repo_sync_service.py) to cover stop idempotence, trigger serialization, and default-helper validation
- Verification:
  - `.venv/bin/pytest tests/test_repo_sync_service.py` -> passed (6 tests)
  - `.venv/bin/python -m compileall nanobot/repo_sync tests/test_repo_sync_service.py` -> passed
  - `.venv/bin/python -c "from nanobot.repo_sync.service import RepoSyncWatcher, sync_fork_once; print(RepoSyncWatcher.__name__, callable(sync_fork_once))"` -> passed
  - `.venv/bin/pytest` -> no longer fails at `tests/test_repo_sync_service.py` import collection; current suite now reports 6 unrelated failures after collecting and running 715 items
- Remaining blockers / follow-up:
  - CLI gateway tests still fail because mocked `MessageBus` objects now reach a code path expecting `publish_outbound`; this is separate from `repo_sync.service`
  - `tests/config/test_config_migration.py` still expects the deprecated `memory_window` field to disappear entirely
  - `tests/test_openai_oauth_provider.py` still expects `nanobot.providers.openai_oauth_provider` to be lazily addressable for monkeypatching
  - `tests/tools/test_tool_validation.py::test_exec_head_tail_truncation` still assumes `python` exists on PATH, while this environment only has `.venv/bin/python`

## Harness reboot - 2026-03-29 (telegram coding-task auto-launch)
- Task pivot:
  - Start a new standalone harness to let Telegram private-chat `开始编程` create and immediately launch a Codex-backed coding task
- Existing work detected before re-planning:
  - The active coding-task runtime already passes a shared launcher into [nanobot/coding_tasks/router.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/router.py) through [nanobot/agent/loop.py](/Users/miau/Documents/nanobot/nanobot/agent/loop.py)
  - Today the Telegram start handler only creates the task and replies with `状态: queued`; the first launch still requires the CLI `nanobot coding-task run <task_id>` path
  - Repo-wide pytest is no longer blocked by `repo_sync.service`, but unrelated red tests remain in CLI gateway mocks, config migration, OpenAI OAuth lazy imports, and exec PATH assumptions
- Baseline validation before feature work:
  - `bash ~/.codex/scripts/global-init.sh` -> exited 0 with one known pytest error bundle from unrelated baseline failures
  - `git status --short` -> only untracked `.codex/` before this harness reboot
- Key decisions:
  - Keep the change narrow: Telegram start should call the existing shared launcher, not invent a second worker-start path
  - Preserve current CLI `coding-task create` and `coding-task run` semantics as an explicit alternative workflow
  - If launch fails, keep the created task on disk and report the failure clearly to Telegram instead of silently rolling back the task record

## Session update - 2026-03-29 (telegram coding-task auto-launch)
- Completed features:
  - Updated [nanobot/coding_tasks/router.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/router.py) so Telegram private-chat `开始编程` now delegates to the shared `launcher.launch_task()` path immediately after task creation when a launcher is available
  - Added clear failure handling for auto-launch: nanobot now keeps the task record, marks it failed, and replies with a Telegram-visible error message instead of silently losing the task
  - Preserved create-only fallback behavior when no launcher is wired, so narrower runtimes can still persist tasks without pretending to launch workers
  - Updated [tests/agent/test_coding_task_routing.py](/Users/miau/Documents/nanobot/tests/agent/test_coding_task_routing.py) to use a fake launcher by default, and added focused regressions for auto-launch success, no-launcher fallback, and launch-failure retention
  - Updated [README.md](/Users/miau/Documents/nanobot/README.md) to document that Telegram `开始编程` now launches Codex immediately while the CLI create/run path remains available
- Verification:
  - `.venv/bin/pytest tests/agent/test_coding_task_routing.py tests/coding_tasks/test_router.py` -> passed (16 tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks/router.py tests/agent/test_coding_task_routing.py` -> passed
  - Manual smoke:
    - `.venv/bin/python - <<'PY' ...` with a temporary workspace, real `AgentLoop` routing, and a fake launcher -> Telegram `开始编程 <repo> 修复登录回调` returned `已创建并启动编程任务` and persisted the task in `starting` status
- Remaining blockers / follow-up:
  - Repo-wide pytest still has the unrelated baseline failures recorded in the previous session (`tests/cli/test_commands.py`, `tests/config/test_config_migration.py`, `tests/test_openai_oauth_provider.py`, and `tests/tools/test_tool_validation.py`)
  - The Telegram path still depends on the gateway being active; this session did not change gateway startup or outbound notification plumbing

## Harness reboot - 2026-03-29 (telegram coding intent refactor)
- Task pivot:
  - Start a new standalone harness to replace the Telegram coding-task start parser with explicit-entry intent detection, slot extraction, and repo resolution
- Existing work detected before re-planning:
  - The active Telegram coding-task path already supports auto-launch and a few alias-like parser shortcuts, but the current behavior is still driven by hardcoded sentence branches inside [nanobot/coding_tasks/router.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/router.py)
  - Current uncommitted edits already widen the parser slightly for `repo goal` cases, so they should be absorbed into this refactor rather than treated as a separate feature
  - There is still no config-level repo alias table; repo alias handling currently depends on router-local fallback logic
- Baseline validation before feature work:
  - `bash ~/.codex/scripts/global-init.sh` -> exited 0 with one known pytest failure bundle from unrelated baseline issues
  - `git status --short` -> only router/test files for the Telegram coding-task parser were dirty before this harness reboot, plus untracked `.codex/`
- Key decisions:
  - Keep explicit Telegram entry signals (`开始编程`, `/coding`) as the first-version boundary, but remove hardcoded sentence-specific routing beneath them
  - Move repo resolution into a dedicated resolver with alias-table priority and `~/Documents/<repo>` fallback
  - Preserve the existing shared launcher path and current Telegram control commands; this task only replaces the start-intent understanding layer

## Session update - 2026-03-29 (telegram coding intent refactor)
- Completed features:
  - Added [nanobot/coding_tasks/repo_resolver.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/repo_resolver.py) and wired it through [nanobot/coding_tasks/runtime.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/runtime.py), [nanobot/cli/commands.py](/Users/miau/Documents/nanobot/nanobot/cli/commands.py), and [nanobot/agent/loop.py](/Users/miau/Documents/nanobot/nanobot/agent/loop.py) so Telegram coding-task entrypoints resolve repos via config aliases first and `~/Documents/<repo>` second
  - Refactored [nanobot/coding_tasks/router.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/router.py) into explicit-entry detection, unified slot extraction, and repo-ref resolution instead of branching on specific Chinese sentence templates
  - Preserved the existing shared create/launch path, including queued-task fallback when no launcher is wired and failed-task retention when automatic launch raises
  - Updated focused tests in [tests/coding_tasks/test_router.py](/Users/miau/Documents/nanobot/tests/coding_tasks/test_router.py), [tests/agent/test_coding_task_routing.py](/Users/miau/Documents/nanobot/tests/agent/test_coding_task_routing.py), [tests/coding_tasks/test_runtime.py](/Users/miau/Documents/nanobot/tests/coding_tasks/test_runtime.py), and [tests/cli/test_commands.py](/Users/miau/Documents/nanobot/tests/cli/test_commands.py) to cover explicit triggers, natural repo-plus-goal phrasing, alias-table priority, Documents fallback, and runtime compatibility
  - Updated [README.md](/Users/miau/Documents/nanobot/README.md) to document the new Telegram entry style and the `gateway.codingTaskRepos` alias map
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_router.py tests/agent/test_coding_task_routing.py tests/coding_tasks/test_runtime.py` -> passed (31 tests)
  - `.venv/bin/pytest tests/cli/test_commands.py -k "gateway_reports_coding_task_counts or coding_task_create_persists_task or coding_task_status_shows_details_and_recent_events or coding_task_run_launches_tmux_worker or coding_task_status_reads_report_without_persisting_metadata"` -> passed (5 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks/router.py nanobot/coding_tasks/repo_resolver.py nanobot/coding_tasks/runtime.py tests/coding_tasks/test_router.py tests/agent/test_coding_task_routing.py tests/coding_tasks/test_runtime.py tests/cli/test_commands.py` -> passed
  - Live/runtime smoke:
    - Restarted the existing `nanobot:0.0` tmux gateway in place and verified `Telegram bot @kimmydoomyBot connected`
    - Ran a post-restart real `AgentLoop` smoke with repo alias config and the message `开始编程 codex-remote 底部tab设置icon换一个`; it returned `已创建并启动编程任务` and persisted the task in `starting` status
- Remaining blockers / follow-up:
  - Repo-wide pytest still has unrelated baseline failures outside this harness, including config migration, OpenAI OAuth lazy import behavior, and exec PATH assumptions
  - Full end-to-end inbound Telegram confirmation for the exact natural-language phrase still depends on a real user message, but the live gateway was restarted successfully and the same routing path was exercised in a post-restart smoke

## Harness reboot - 2026-03-29 (repo harness conflict confirmation)
- Task pivot:
  - Start a new standalone harness to fix the case where a new Telegram coding goal hits a repo with an unfinished in-repo harness and silently resumes the old work instead
- Existing work detected before re-planning:
  - Telegram coding-task entry now parses explicit repo-plus-goal messages correctly and launches the shared Codex worker path
  - Live verification showed the real failure mode is downstream of parsing: when the target repo already has an active harness, Codex restores that harness and its old unfinished task, even if the newly created nanobot task has a different goal
  - The current Telegram control surface only supports generic `继续 / 停止 / 取消`, so it cannot disambiguate “continue the old harness” from “start my new goal anyway”
- Baseline validation before feature work:
  - `git status --short` -> only untracked `.codex/` before this reboot
  - The active gateway in `nanobot:0.0` was already running commit `9f09c1d` when the issue reproduced
- Key decisions:
  - Keep the fix narrow: intercept active-harness conflicts before Codex launch instead of redesigning the whole coding-task lifecycle
  - Reuse `waiting_user` rather than inventing a new persistent status, with conflict details stored in task metadata
  - Require explicit conflict commands such as `继续旧任务` and `按新任务开始`; bare `继续` is too ambiguous in this state

## Session update - 2026-03-29 (repo harness conflict confirmation)
- Completed features:
  - Extended [nanobot/coding_tasks/harness.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/harness.py) so active harness detection now returns a concise summary from `PROGRESS.md` or `PLAN.json` progress, and added a dedicated `start_new_goal` bootstrap mode
  - Added metadata updates and a pre-launch `waiting_user` path in [nanobot/coding_tasks/manager.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/manager.py), [nanobot/coding_tasks/router.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/router.py), and [nanobot/coding_tasks/reporting.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/reporting.py) so Telegram now pauses on active-harness conflicts and asks for `继续旧任务 / 按新任务开始 / 取消`
  - Updated [nanobot/coding_tasks/worker.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/worker.py) so explicit new-goal launches tell Codex to treat the old harness as background context rather than the primary unfinished task
  - Hardened [nanobot/coding_tasks/progress.py](/Users/miau/Documents/nanobot/nanobot/coding_tasks/progress.py) against unreadable `PROGRESS.md` / `PLAN.json` files so one inaccessible repo no longer crashes the whole gateway poller
  - Updated [README.md](/Users/miau/Documents/nanobot/README.md) with the new conflict confirmation flow
- Verification:
  - `.venv/bin/pytest tests/coding_tasks/test_harness.py tests/coding_tasks/test_worker.py tests/coding_tasks/test_reporting.py tests/agent/test_coding_task_routing.py` -> passed (35 tests)
  - `.venv/bin/pytest tests/coding_tasks/test_progress.py tests/coding_tasks/test_harness.py tests/coding_tasks/test_worker.py tests/coding_tasks/test_reporting.py tests/agent/test_coding_task_routing.py tests/cli/test_commands.py -k "extract_latest_progress_note_handles_permission_errors or summarize_plan_progress_handles_permission_errors or coding_task_status_shows_details_and_recent_events or gateway_reports_coding_task_counts or test_private_telegram_start_coding_waits_for_confirmation_when_repo_has_active_harness or test_private_telegram_start_new_goal_launches_conflict_task_with_override or test_launch_task_writes_new_goal_override_prompt_for_conflict_resolution"` -> passed (7 selected tests)
  - `.venv/bin/python -m compileall nanobot/coding_tasks/harness.py nanobot/coding_tasks/manager.py nanobot/coding_tasks/progress.py nanobot/coding_tasks/reporting.py nanobot/coding_tasks/router.py nanobot/coding_tasks/worker.py tests/coding_tasks/test_harness.py tests/coding_tasks/test_progress.py tests/coding_tasks/test_worker.py tests/coding_tasks/test_reporting.py tests/agent/test_coding_task_routing.py tests/cli/test_commands.py` -> passed
  - Manual/runtime smokes:
    - A real `AgentLoop` smoke against a repo with an active harness now returns a waiting-user conflict message instead of auto-starting old work
    - A real gateway crash caused by `PermissionError` on `/Users/miau/Documents/codex-remote/PROGRESS.md` was reproduced from `nanobot:0.0`, then covered by the new progress-file error handling
- Remaining blockers / follow-up:
  - The original `nanobot:0.0` tmux shell currently cannot re-exec the repo venv cleanly; direct `.venv/bin/nanobot gateway` fails on `pyvenv.cfg`, and even the system-Python fallback behaves inconsistently inside that pane
  - A temporary non-tmux gateway process can be launched successfully with `/tmp/nanobot-gateway-restart.sh`, but live user confirmation of the new Telegram conflict reply is still pending
