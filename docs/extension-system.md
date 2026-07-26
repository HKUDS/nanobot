# Extension system

This page documents the maintainer-facing architecture. For installation and
operations, read [Extensions](./extensions.md). For the package contract, read
[Extension Authoring](./extension-authoring.md).

nanobot treats an extension as an installable, governable unit and a
contribution as one capability supplied by that unit. This distinction keeps
the agent core small without forcing tools, channels, providers, skills, MCP
servers, hooks, commands, and WebUI code into one artificial runtime interface.

## Architecture

The extension platform is a control plane over existing native registries:

```text
package / workspace directory / compatibility package
                         |
                         v
                ExtensionManifest
                         |
                         v
                ExtensionRegistry
            selection, policy, ownership
                         |
        +----------------+----------------+
        |                |                |
        v                v                v
   native adapters   Pi adapter    OpenClaw adapter
        |                |                |
        +----------------+----------------+
                         |
                         v
       tools / skills / channels / providers / MCP /
               hooks / commands / WebUI
```

`ExtensionManifest` is dependency-free metadata. Discovery can inspect it
without importing optional SDKs or executing plugin code. `ExtensionRegistry`
selects the active installation, applies allow/deny policy, and resolves
contribution ownership. Runtime adapters activate only the contributions the
host supports.

Packages expose this metadata as `nanobot.extension.json`. The same canonical
JSON shape is used on disk, over the Node sidecar protocol, and in market
indexes. Unknown fields are rejected so a misspelled permission or contribution
cannot silently change behavior.

The agent loop does not discover or execute plugins. Assembly code resolves
extensions before constructing the runtime and passes native tools, hooks, and
other contributions through the interfaces those subsystems already expose.

## Identity and precedence

An extension ID is stable across installations. The same ID may exist in three
scopes:

1. `builtin`
2. `user`
3. `workspace`

The nearest scope wins for the same extension ID. Different extensions may not
silently take over the same contribution name. Replacing another extension's
contribution must be explicit and may only come from an equal or higher scope.
Conflicts become diagnostics instead of crashing unrelated extensions.

## Compatibility runtimes

Pi and OpenClaw extensions are JavaScript or TypeScript programs, so Python
cannot import them as native nanobot modules. Compatibility runs them in a
Node.js sidecar and projects supported registrations into nanobot's native
registries over a versioned protocol.

Compatibility is capability-based rather than all-or-nothing:

- A package may load while one unsupported contribution is disabled.
- Inspection reports every supported, translated, degraded, and unsupported
  contribution.
- UI- or host-specific behavior is never reported as working when nanobot
  cannot provide the required host interface.
- Plugin failures are isolated from the agent process and produce actionable
  diagnostics.

The compatibility sidecar is a failure-isolation boundary, not a security
sandbox. The exact executable and metadata-only surfaces are listed in the
[compatibility matrix](./extension-authoring.md#compatibility-matrix).

## Security model

Extensions are trusted code, not prompts or static skills. Installation and
activation are separate actions. The host records source, version, requested
permissions, dependency state, and trust scope before executing code.

Project-local extensions require workspace trust. Contribution conflicts never
grant an implicit override. Secrets remain in nanobot provider or host config
and are exposed only through declared host interfaces. Existing workspace,
network, SSRF, and shell restrictions continue to apply to host-provided
operations.

Untrusted packages remain visible in the catalog with an inactive state. They
do not own active contributions and their runtime is not imported. Built-in
capabilities are trusted by construction; installed and workspace packages
need an explicit trusted entry or an allowed workspace trust policy.

The root `extensions` config controls explicit search paths, allow/deny policy,
per-extension enablement, package-owned config, and workspace trust. Discovery
does not import extension code. Installation does not imply workspace trust,
and activation does not rewrite `config.json` behind the user's back.

The activation gates are deliberately independent:

```text
installed -> dependencies ready -> permissions granted -> trusted + enabled
```

Only candidates that pass every gate own active contributions. Reload first
rolls back registrations by extension owner and then activates the new
snapshot. A failed activation is converted into a diagnostic.

## Market boundary

The market is an index, not a runtime. It describes packages available from
PyPI, npm, Git, ClawHub, Pi catalogs, or local sources using the same manifest
shape. Installing a listing still goes through the local installer, policy,
dependency checks, and trust flow. This keeps discovery independent from code
execution and allows multiple catalogs without coupling the agent to one
store.

## Ownership boundaries

The extension package owns identity, policy, and contribution declarations.
Native subsystems continue to own execution:

| Concern | Owner |
|---|---|
| Package identity, source, trust, permissions | `nanobot.extensions` |
| Tool execution contract | `nanobot.agent.tools` |
| Commands | `nanobot.command` |
| Agent lifecycle hooks | `nanobot.agent.hook` |
| Providers | `nanobot.providers` |
| Channels | `nanobot.channels` |
| Skills | `nanobot.skills` |
| Browser management surface | `webui` |

Do not add extension discovery or compatibility branching to `AgentLoop`.
Runtime assembly creates an `ExtensionHost`, projects supported registrations
through native APIs, and closes the host with the surrounding runtime.

## Protocol boundary

Pi and OpenClaw entries run behind a versioned NDJSON request/response protocol.
The Python process sends load, call, lifecycle event, and close requests. The
Node process returns registrations, results, outputs, and diagnostics. Protocol
messages contain JSON-compatible values only.

The adapter must reject malformed messages, time out stalled requests, and
close the sidecar when activation fails. Unsupported upstream methods are
either explicit no-ops with diagnostics or rejected; they must never be
reported as executable contributions.
