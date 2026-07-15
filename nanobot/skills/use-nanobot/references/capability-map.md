# Capability Map

Use this reference for work performed now: workspace changes, research, external integrations,
artifacts, memory, runtime diagnosis, and reusable workflows. Inspect the current tool schemas
before selecting a route because availability varies by runtime.

## Capability Families

| Family | Useful primitives | Typical closed loop |
|---|---|---|
| Workspace understanding and change | `find_files`, `list_dir`, `grep`, `read_file`, `apply_patch`, `edit_file`, `write_file`, `exec` | Locate → inspect → change → run a focused check → report evidence. |
| Current or external information | `web_search`, `web_fetch`, domain skills, existing CLIs | Find current primary sources → inspect details → compare → cite or save the result. |
| External systems and accounts | Attached CLI apps, configured MCP tools, established domain CLIs such as `gh` | Load relevant guidance → use the authenticated integration → verify remote state. |
| Documents, images, and artifacts | Document-aware `read_file`, `generate_image`, deterministic scripts, `message` media | Read or create → inspect/revise → save → deliver the actual artifact. |
| Reusable know-how | Skills index, `skill-creator`, workspace instructions | Discover an existing procedure; create a skill when a recurring workflow benefits from guidance or bundled resources. |
| Memory and personalization | Conversation history, memory skill, `USER.md`, Dream-managed memory | Recover context → distinguish durable facts from temporary state → store in the appropriate layer. |
| Runtime awareness | `my`, actual tool schemas, runtime context | Inspect model, limits, routing, tool config, or subagent status → adapt without exposing secrets. |

Prefer the highest-level capability already connected to the target. Do not reimplement an
attached app or MCP integration through raw HTTP or shell, and do not ask the user to paste data
that an authenticated integration can retrieve. If a specialized procedure exists in the skills
index, read it before improvising. For a future inbound webhook or event that should wake the
conversation, use the continuity reference rather than treating it as an immediate integration.

## Close the Deliverable Gap

Many failures come from completing an internal step but not the user's requested result:

- A code fix is not complete after diagnosis. Reproduce the issue, inspect ownership, edit,
  run the smallest reliable test, and disclose what remains unverified.
- Research is not complete after search. Open useful sources, resolve disagreements, make
  freshness explicit, and produce the requested answer or artifact.
- A generated image or existing PDF is not delivered by reading or saving it. Attach it through
  `message` when the user asked to receive the file.
- A remote change is not complete after preparing a command. Use the authorized integration,
  inspect the remote result, and surface externally visible consequences.
- A bulk transformation needs deterministic validation such as counts, totals, checksums, schema
  checks, or representative samples before delivery.
- Remembering a preference is not scheduling an action. Memory preserves context; continuity
  mechanisms create future execution.

## Combine Families Deliberately

Use these examples as prompts for invention:

- **Investigate and fix:** search, read the ownership boundary, reproduce with `exec`, patch,
  test, and attach logs only if the user needs the file itself.
- **GitHub failure to local fix:** read the GitHub skill, inspect the run with `gh`, correlate the
  failure with local code, patch and test, then re-check remote state when authorized.
- **Current research report:** search current primary sources, fetch decisive pages, compare,
  write the report, verify its contents, and send the file.
- **Document or data transformation:** read the input format, use a deterministic library or
  script for bulk work, validate representative output and invariants, then deliver the result.
- **Image request:** read image-generation guidance, generate or edit, inspect and iterate, then
  send the saved artifact through media delivery.
- **Authenticated app workflow:** use the attached app or MCP surface. If login is the only
  missing edge, keep the prepared task state and follow the human handoff reference.
- **Personalized output:** recover durable style preferences from memory, gather current inputs,
  create the artifact, verify it, and deliver it.

## Create the Smallest Missing Capability

When no existing capability closes an edge, choose the smallest bridge:

- Use a one-off tool call or short script for a one-time mechanical task.
- Put deterministic repeated transformations in a script with tests and explicit inputs/outputs.
- Put recurring judgment, routing guidance, references, and recovery instructions in a skill.
- Combine a script and skill when deterministic processing feeds agent decisions.
- Search a trusted skill registry before recreating a common domain workflow; inspect what will
  be installed before enabling third-party code.
- Prefer a configured app, MCP server, or established CLI for a real external system instead of
  building a large bespoke integration for one request.

Do not productize a trivial one-off task, but do not repeatedly delegate mechanical work to the
user when nanobot can encode it once.

## Diagnose from Actual State

If a capability is missing or behaves unexpectedly, inspect the error and relevant runtime state
before inventing a reason. Use `my` for model, context window, iteration limits, tool config,
routing metadata, and subagent status when those facts affect the plan. Use the actual skills
index and tool schemas to distinguish unavailable, disabled, unattached, misconfigured, and
unsupported capabilities. Choose a safe alternative without bypassing the boundary that caused
the failure.
