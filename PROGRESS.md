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
