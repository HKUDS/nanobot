---
name: mobile-testing
description: "Plan and run mobile App automated tests with Maestro. Use for Android/iOS flow automation, smoke/regression checks, and evidence collection."
metadata: {"nanobot":{"requires":{"bins":["maestro"]},"install":[{"id":"maestro-curl","kind":"shell","command":"curl -fsSL \"https://get.maestro.mobile.dev\" | bash","bins":["maestro"],"label":"Install Maestro CLI"},{"id":"maestro-brew","kind":"brew","formula":"maestro","bins":["maestro"],"label":"Install Maestro CLI (brew tap required)"}]}}
---

# Mobile Testing

Use this skill when the user asks to automate testing for iOS/Android apps with Maestro.

## Default Workflow

1. Confirm target platform (`android` or `ios`) and app package/bundle id.
2. Ensure workspace scaffold exists (recommended once): `nanobot mobile setup`.
3. Edit or create flows under `mobile/flows/`.
4. Run test:
```bash
nanobot mobile run --suite smoke --platform android
# prefer MCP execution when configured:
nanobot mobile run --mode mcp --mcp-server maestro
# or single flow:
maestro test mobile/flows/<flow>.yaml
```
5. Save artifacts in:
- `reports/mobile/runs/<run-id>/`
- `reports/mobile/artifacts/<run-id>/<flow-id>/` (via Maestro `--test-output-dir`)
6. Update `reports/mobile/summary-latest.json` with run status and artifact paths.

## With MCP (Recommended)

If Maestro MCP is configured (`tools.mcpServers.maestro`), prefer MCP tools for execution and result retrieval.

Typical MCP tool names from Maestro:
- `maestro_list_devices`
- `maestro_start_device`
- `maestro_run_flow_files`
- `maestro_run_test_suite`
- `maestro_take_screenshot`
- `maestro_inspect_view_hierarchy`
- `maestro_stop_device`

Use them to keep execution deterministic and tool-native in the agent loop.

## Flow Authoring Rules

- Keep one user journey per flow file.
- Use stable selectors (text/resource-id/accessibility id).
- For flaky steps, add explicit waits and robust assertions.
- Name flow files by intent, for example:
  - `login-smoke.yaml`
  - `checkout-regression.yaml`
  - `settings-permission.yaml`

## Report Contract

After each run, produce a concise summary with:
- `runId`
- `status` (`passed`/`failed`)
- `platform`
- `suite`
- `startedAt` / `finishedAt`
- artifact list (screenshots, logs, videos)

Store this summary in `reports/mobile/summary-latest.json`.
