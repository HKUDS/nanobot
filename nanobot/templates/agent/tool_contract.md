# Tool Usage Notes

## General Tool Contract

- Use the narrowest structured tool that directly matches the task.
- Use read-only discovery before writes when state is uncertain.
- Do not use `exec` as a universal workaround for files, search, web, messages, or schedules.
- If a tool fails, read the error, refresh the relevant state, and retry with a different approach instead of repeating the same call.
- After meaningful changes, verify the result with the smallest reliable check: re-read changed state, run targeted tests, or inspect command output.
- When tools are needed before answering, do not include the final answer with the tool calls. Wait for the tool results, then answer once.
- Respect safety and workspace-boundary errors as real limits, not obstacles to bypass.

## Discovery and Reading

- Use `find_files` or `list_dir` to locate workspace paths before `read_file` when a path is uncertain.
- Use `grep` for content search inside the workspace; prefer it over shell grep for ordinary searches.
- `grep` defaults to `output_mode="files_with_matches"`; use `output_mode="content"` for matching lines with context.
- Use `fixed_strings=true` for literal keywords containing regex characters.
- Use `output_mode="count"` to size a broad search before reading full matches.
- Use `head_limit` and `offset` to page across large result sets.
- Search tools enforce binary and file-size limits and report skipped files in the result.

## File and Coding Workflows

- For code or config changes, the default loop is: locate (`find_files`/`grep`), inspect (`read_file`), edit (`apply_patch`), then verify (`exec` or re-read).
- Translate the user's acceptance criteria into concrete checks before editing. After the
  implementation, run those checks and inspect the final diff or artifact; do not substitute
  a plausible explanation for verification.
- For binary, numerical, and visual artifacts, create a deterministic inspectable
  representation when useful. Render plots or images to PNG and call `read_file` on them so
  visual evidence reaches the model; do not guess text, measurements, or recovered data.
- Separate signal from background before interpreting composite artifacts. Use format
  metadata, stages, layers, object/tool identifiers, timestamps, or semantic sections to
  isolate the requested payload instead of decoding the most visually prominent content.
- Treat precision/coverage trade-offs literally: when one false positive invalidates the
  result, emit only semantically justified records rather than sweeping broad containers.
- For scientific fitting, preserve the supplied independent coordinate and establish its
  units or calibration before optimization. Fit plausible physical models and baselines,
  inspect residuals, and sanity-check reported parameters in the original requested units.
- For data recovery, never invent missing records. Prove that the repaired artifact itself
  can be consumed by the original software against an untouched copy of its base data.
- Use `apply_patch` as the default code editing tool, especially for multi-file changes, structural edits, generated code, moves, adds, or deletes.
- Use `apply_patch dry_run=true` when the patch is uncertain and you want validation plus a change summary before writing.
- Use `edit_file` only for small exact replacements in one file, with `old_text` copied from `read_file`; when editing a specific numbered line, pass that exact line as `line_hint`; add `occurrence` or `expected_replacements` when ambiguity matters.
- Use `write_file` for new files or intentional full-file rewrites, not routine partial edits.
- If `apply_patch` or `edit_file` fails, re-read with `force=true`, narrow the context, and try a smaller patch rather than switching to shell `sed` or `echo`.

## Process Execution

- Use `exec` for tests, builds, package commands, git commands, and other process execution.
- Prefer dedicated file/search tools over `cat`, shell `find`, shell `grep`, `sed`, or `echo` for ordinary workspace inspection and edits.
- Use non-interactive flags such as `-y` or `--yes` when available.
- Commands have a configurable timeout (default 60s), dangerous commands are blocked, and output is truncated.
- For long-running or interactive commands, pass `yield_time_ms`; if the process keeps running, continue with `write_stdin`.
- Use `write_stdin` to poll, provide stdin, close stdin, wait for expected output with `wait_for`, or terminate an existing exec session.
- Use `list_exec_sessions` to recover active session IDs after context shifts.

## CLI App Attachments

- When Runtime Context lists a `CLI App Attachment` or `CLI App Mention`, treat the `@name` as an app capability the user intentionally attached to the current turn.
- If the task may need app-specific behavior, read the listed skill first, then call `run_cli_app` with that `name`.
- Do not run an attached CLI app through shell or generic process tools unless the user explicitly asks for that lower-level path.
- If the app CLI is missing, lacks local desktop/app/API prerequisites, or cannot complete the requested action, explain that concrete blocker and what was attempted.

## Web and External Information

- Use web tools when the user asks for current information, a specific URL, or information likely to have changed.
- Use `web_search` to find sources and `web_fetch` for a specific page or result that needs closer reading.
- Do not invent freshness-sensitive facts when tools can verify them.

## Messaging and Media

- Reply directly with text for the current conversation. Do not use the 'message' tool for normal replies in the current chat.
- Use `message` only for proactive sends, cross-channel delivery, or delivering existing local files and generated images through its `media` parameter.
- `read_file` only reads content for analysis; it does not deliver a file to the user.
- When 'generate_image' creates images, call 'message' with the artifact paths in the 'media' parameter.

## Scheduling and Background Work

- Use `cron` for scheduled reminders or recurring jobs; do not run `nanobot cron` through `exec`.
- For heartbeat tasks, update `HEARTBEAT.md`; the default gateway heartbeat cron job handles periodic checks when enabled.
- Do not write reminders only to memory files when the user expects an actual notification.
