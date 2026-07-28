# Extension Authoring

A native nanobot extension is a directory containing:

```text
nanobot-review/
├── nanobot.extension.json
└── extension.py
```

The manifest describes identity, activation prerequisites, and requested
permissions. The Python entry point performs the real registration. This keeps
one authoritative source for tool, command, and hook ownership.

## Manifest

```json
{
  "id": "acme.review",
  "name": "Acme Review",
  "version": "1.0.0",
  "entry": "extension:register",
  "description": "Adds repository review tools.",
  "apiVersion": 1,
  "license": "MIT",
  "homepage": "https://github.com/acme/nanobot-review",
  "dependencies": [
    {
      "kind": "executable",
      "name": "git"
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

Required fields are `id`, `name`, and `version`. `entry` defaults to
`"extension:register"` and `apiVersion` defaults to `1`.

IDs use lowercase letters, digits, dots, underscores, and hyphens. Entry points
use `module:function` syntax and must resolve inside the package.

### Dependencies

| Kind | Meaning |
|---|---|
| `python` | Installed Python distribution; `specifier` accepts a version constraint |
| `executable` | Command available on `PATH` |
| `environment` | Non-empty environment variable |

Set `"optional": true` when a missing dependency should not block activation.

### Permissions

Permissions are lowercase namespaced identifiers chosen by the package, such
as `workspace.read` or `network`. Give each permission a concrete reason.
Activation waits until every requested permission is granted.

The host currently uses permissions as explicit user consent. They do not
sandbox Python code, so do not describe a permission as stronger isolation
than it provides.

## Registration API

The entry point receives `PythonExtensionApi` and must return `None`:

```python
from typing import Any

from nanobot.agent.tools.base import Tool


class ReviewTool(Tool):
    @property
    def name(self) -> str:
        return "review_repository"

    @property
    def description(self) -> str:
        return "Review the current repository."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        return "No findings."


def register(api) -> None:
    api.register_tool(ReviewTool())
```

The API has three stable methods:

```python
api.register_tool(tool)
api.register_command("review", handler)
api.register_hook_factory(factory)
```

Command handlers use nanobot's `CommandContext` and return an
`OutboundMessage` or `None`. Hook factories receive `AgentTurnHookContext` and
return an `AgentHook` or `None`.

Do not modify `AgentLoop` or global registries directly. The API tags every
registration with the extension ID so reload, failure rollback, and uninstall
can remove exactly what the package owns.

## Collision and failure behavior

Tool and command names are unique across core and active extensions. If an
extension registers a duplicate name, activation fails for that extension and
all of its partial registrations are rolled back.

Missing dependencies are reported as diagnostics instead of crashing the
gateway.

## Develop locally

1. Create the manifest and entry module.
2. Install the directory with `--kind local`.
3. Inspect and grant its permissions.
4. Trust it.
5. Reinstall after editing so nanobot records a new integrity digest.

```bash
nanobot extensions install "$PWD" --kind local
nanobot extensions inspect acme.review
nanobot extensions permissions acme.review workspace.read
nanobot extensions trust acme.review
```

Keep tests in the extension repository. At minimum, test registration,
duplicate-name failure, and behavior when each required dependency is missing.

## Distribution

Publish the directory in a Git repository. Users can pin a release tag or
commit with `--ref`. The repository root must contain
`nanobot.extension.json`; install scripts and generated compatibility manifests
are not part of the native contract.
