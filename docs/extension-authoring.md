# Extension Authoring

nanobot extensions are packages with a strict `nanobot.extension.json`
manifest. The manifest can be inspected without importing optional SDKs or
executing package code. Runtime activation then projects each contribution into
the native nanobot registry that owns that capability.

This guide covers native Python extensions and the compatibility boundary for
Pi and OpenClaw packages. Users installing packages should read
[Extensions](./extensions.md).

## Package Layout

A minimal native package is:

```text
my-extension/
|-- nanobot.extension.json
`-- my_extension/
    `-- __init__.py
```

`nanobot.extension.json`:

```json
{
  "id": "acme.review",
  "name": "Acme Review",
  "version": "1.0.0",
  "apiVersion": 1,
  "runtime": "python",
  "entry": "my_extension:register",
  "description": "Adds a review tool and command.",
  "homepage": "https://example.com/acme-review",
  "license": "MIT",
  "contributions": [
    {
      "kind": "tool",
      "name": "review_code",
      "description": "Review a local change."
    },
    {
      "kind": "command",
      "name": "review",
      "description": "Start a review from chat."
    }
  ],
  "dependencies": [
    {
      "kind": "python",
      "name": "acme-review-core",
      "specifier": ">=1,<2",
      "optional": false
    }
  ],
  "permissions": [
    {
      "name": "workspace.read",
      "reason": "Read files selected for review."
    }
  ]
}
```

Unknown fields are rejected. This is deliberate: a misspelled permission,
dependency, or contribution must not silently change package behavior.

## Manifest Reference

### Top-level fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | Stable lowercase package identity |
| `name` | yes | Human-readable name |
| `version` | yes | Installed package version |
| `apiVersion` | no | Manifest API, currently `1` |
| `runtime` | yes | `python`, `pi`, `openclaw`, or `declarative` |
| `entry` | runtime-dependent | One activation entry |
| `entries` | runtime-dependent | Multiple Pi/OpenClaw entries; takes precedence over `entry` |
| `contributions` | no | Capabilities owned by the package |
| `dependencies` | no | Activation prerequisites |
| `permissions` | no | Privileged host capabilities requested from the user |
| `description` | no | Catalog summary |
| `homepage` | no | Project or documentation URL |
| `license` | no | SPDX-style license label |

Entries must be relative to the package root and cannot contain `..`.

### Contributions

Supported `kind` values are:

```text
tool
skill
channel
llm_provider
transcription_provider
image_generation_provider
web_search_provider
mcp_server
hook
command
webui
```

Each contribution has a stable `name`, optional runtime `target`, optional
`description`, and optional `replaces` list. `replaces` contains extension IDs,
not contribution names. Replacement is still checked against scope precedence.

The manifest declares ownership. It does not create an implementation by
itself. A runtime must register the corresponding native capability.

### Dependencies

| Kind | `name` identifies | Version behavior |
|---|---|---|
| `python` | Installed Python distribution | PEP 440 specifier |
| `npm` | Package under the extension's `node_modules` | npm installation constraint |
| `executable` | Command on `PATH` | No version probe |
| `environment` | Environment variable | Must be non-empty |
| `extension` | Another extension ID | Installed extension version |

Set `optional: true` when the extension can activate without the dependency.
Do not put API keys in the manifest.

### Permissions

Permission names are lowercase namespaced identifiers such as
`workspace.read`, `workspace.write`, or `network.http`. Include a concrete
reason the user can evaluate. Activation requires every requested permission to
be granted.

Permissions describe host policy; they are not an OS sandbox. Keep the request
set minimal and use native host operations when one exists.

## Native Python Runtime

The Python entry is `module[:attribute]`; the default attribute is `register`.
The function is synchronous and must return `None`:

```python
from nanobot.agent.tools.base import Tool


class ReviewTool(Tool):
    @property
    def name(self) -> str:
        return "review_code"

    @property
    def description(self) -> str:
        return "Review a local code change."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        }

    async def execute(self, path: str) -> str:
        return f"Review requested for {path}"


def register(api) -> None:
    api.register_tool(ReviewTool())
```

The v1 Python API exposes:

- `register_tool(tool)`
- `register_command(command, handler, prefix=False)`
- `register_hook_factory(factory)`

These methods use existing nanobot registries. Do not import or patch
`AgentLoop`, reach into WebSocket internals, or create a second tool registry.
If a new contribution kind needs execution support, add an adapter at the
native subsystem boundary and keep the manifest API independent from that
implementation.

## Publish and Discover

For npm discovery, include the exact `nanobot-extension` keyword:

```json
{
  "keywords": [
    "nanobot-extension"
  ]
}
```

Compatibility packages use their upstream metadata and keyword:

- Pi: `pi-package` plus `pi.extensions`
- OpenClaw: `openclaw-plugin` plus `openclaw.extensions` or
  `openclaw.runtimeExtensions`

Native Python packages can be installed from a local directory or Git source.
The market is an index; installation always passes through local validation,
dependency checks, permission review, trust, and activation.

## Compatibility Matrix

The matrix describes the current adapter, not an intention to support every
upstream API.

| Upstream capability | Pi | OpenClaw | nanobot behavior |
|---|---|---|---|
| Tool registration and calls | Executable | Executable | Projected as native `Tool`; implementation stays in Node sidecar |
| Slash commands | Executable | Executable | Registered in native command router |
| Supported lifecycle events | Observation-only | Observation-only | Receives serialized run/tool events; cannot mutate native context |
| Provider registration | Metadata only | Metadata only | Visible in catalog and diagnostics; not an executable provider |
| Transcription/image/web-search provider contracts | N/A | Metadata only | Visible but not projected into native provider registries |
| Skills declared in plugin metadata | N/A | Metadata only | Catalog ownership only; runtime skill installation is not synthesized |
| Channels | N/A | Metadata only | No OpenClaw channel host emulation |
| Session tree and custom entries | Unsupported | Unsupported | No compatible host surface |
| Terminal UI, widgets, renderers, shortcuts | Unsupported | Unsupported | WebUI and CLI have different rendering contracts |
| Model selection and thinking control | Unsupported | Unsupported | Remains owned by nanobot model presets and request policy |
| Arbitrary upstream host services | Unsupported | Unsupported | Reported as diagnostics rather than silently emulated |

### Pi package shape

```json
{
  "name": "@acme/pi-review",
  "version": "1.0.0",
  "keywords": ["pi-package"],
  "pi": {
    "extensions": ["./index.ts"]
  }
}
```

The sidecar supports `registerTool`, `registerCommand`, and selected `on(...)`
lifecycle handlers. TypeScript uses Node's native type stripping when
available, with `jiti` as a fallback installed with the package runtime.

### OpenClaw package shape

```json
{
  "name": "@acme/openclaw-review",
  "version": "1.0.0",
  "keywords": ["openclaw-plugin"],
  "openclaw": {
    "runtimeExtensions": ["./dist/index.js"]
  }
}
```

If present, `openclaw.plugin.json` supplies catalog identity, contribution
contracts, command aliases, and compatibility diagnostics. The OpenClaw
`register` function must complete synchronously during load.

## Test an Extension

Use an isolated config and workspace while developing:

```bash
nanobot extensions install ./my-extension --kind local
nanobot extensions inspect acme.review
nanobot extensions permissions acme.review workspace.read
nanobot extensions trust acme.review
nanobot extensions enable acme.review
nanobot agent -m "Use review_code on README.md"
```

Also test:

- install while untrusted does not execute code;
- missing hard dependencies leave the package inactive;
- denied or missing permissions prevent activation;
- duplicate contribution names become diagnostics;
- disable, untrust, reload, and uninstall remove runtime registrations;
- one broken package does not block unrelated packages.

For nanobot itself, extension tests live under `tests/extensions/`. Keep
compatibility fixtures small and assert diagnostics for unsupported APIs.

## Design Rules

1. Extend the control plane, not the core loop.
2. Keep one native owner for each capability.
3. Make discovery metadata-only.
4. Separate install, permission grant, trust, and enable.
5. Report partial compatibility honestly.
6. Keep market metadata independent from runtime execution.
7. Roll back all registrations owned by a failed or unloaded extension.
