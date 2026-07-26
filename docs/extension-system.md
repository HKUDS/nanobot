# Extension system

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

## Security model

Extensions are trusted code, not prompts or static skills. Installation and
activation are separate actions. The host records source, version, requested
permissions, dependency state, and trust scope before executing code.

Project-local extensions require workspace trust. Contribution conflicts never
grant an implicit override. Secrets remain in nanobot provider or host config
and are exposed only through declared host interfaces. Existing workspace,
network, SSRF, and shell restrictions continue to apply to host-provided
operations.

## Market boundary

The market is an index, not a runtime. It describes packages available from
PyPI, npm, Git, ClawHub, Pi catalogs, or local sources using the same manifest
shape. Installing a listing still goes through the local installer, policy,
dependency checks, and trust flow. This keeps discovery independent from code
execution and allows multiple catalogs without coupling the agent to one
store.
