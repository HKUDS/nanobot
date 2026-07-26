# Extensions

Extensions add capabilities to nanobot without modifying the agent loop. A
package can declare tools, commands, hooks, skills, channels, providers, MCP
servers, or WebUI surfaces in one governable manifest. Extension API v1
executes native Python tools, commands, and hooks plus the compatible Pi and
OpenClaw surfaces listed below; other contribution kinds are catalog metadata
until their owning nanobot subsystem provides an activation adapter.

Use this page to install and manage extensions. To publish one, read
[Extension Authoring](./extension-authoring.md). For the internal design, read
[Extension System](./extension-system.md).

## Install Safely

The WebUI **Extensions** page and the `nanobot extensions` commands use the same
local extension store. The safe lifecycle is:

1. Find or install a package.
2. Inspect its source, runtime, dependencies, requested permissions, and
   diagnostics.
3. Grant only the permissions you understand.
4. Mark the package trusted.
5. Enable it.

Installation does not grant trust. An installed package remains visible but
inactive until it is enabled, trusted, has all requested permissions, and
passes integrity and dependency checks.

### WebUI

Open **Extensions** in the sidebar:

- **Installed** manages packages in `~/.nanobot/extensions/`.
- **Discover** searches npm packages marked for nanobot, Pi, or OpenClaw.
- **Built in** shows native nanobot capabilities projected into the same
  catalog. Built-in entries are informational and are not uninstallable.

Select an entry to see its contributions, dependencies, permission reasons,
source, compatibility notices, and activation errors. Trust and permission
controls are intentionally separate.

### CLI

```bash
# Search all supported npm ecosystems
nanobot extensions search "memory"

# Search one compatibility ecosystem
nanobot extensions search "review" --ecosystem pi

# Install without trusting the package
nanobot extensions install @scope/package

# Inspect before activation
nanobot extensions inspect pi.scope.package

# Grant exactly the requested host permissions
nanobot extensions permissions pi.scope.package network.http workspace.read

# Trust and enable
nanobot extensions trust pi.scope.package
nanobot extensions enable pi.scope.package
```

Install from Git or a local directory when the package is not published:

```bash
nanobot extensions install https://github.com/acme/nanobot-tool.git --kind git
nanobot extensions install ./my-extension --kind local
```

Local-directory installation is available only to local WebUI requests. Remote
browser clients cannot ask the gateway to read an arbitrary server path.

## Sources and Scopes

Extensions can come from three scopes:

| Scope | Typical source | Behavior |
|---|---|---|
| Built in | nanobot package | Trusted by construction; shown for ownership and diagnostics |
| User | `~/.nanobot/extensions/` | Installed and governed through the WebUI or CLI |
| Workspace | `<workspace>/.nanobot/extensions/` | Project-local code; controlled by workspace trust policy |

When the same extension ID exists in multiple scopes, the nearest eligible copy
wins: workspace over user, user over built in. An untrusted, disabled, denied,
or invalid copy does not hide a usable lower-scope copy. A contribution cannot
silently replace another extension's contribution. Disable one owner before
activating the other; extension API v1 does not let packages replace core or
third-party registrations.

## Pi and OpenClaw Packages

nanobot reads native Pi and OpenClaw package metadata and runs supported
JavaScript or TypeScript entries in a Node.js sidecar. Compatibility is not
all-or-nothing:

- Adapted packages always request `runtime.node`, making process-level code
  execution explicit before trust and activation.
- Tools, slash commands, and supported lifecycle observation hooks can run.
- Provider-like registrations and several host-specific capabilities may be
  cataloged but not executable.
- Terminal UI, session-tree, renderer, shortcut, and model-control APIs do not
  have equivalent nanobot host surfaces.
- Every degraded or unsupported registration appears in diagnostics.

Check the [compatibility matrix](./extension-authoring.md#compatibility-matrix)
before depending on a package. A package appearing in search results means its
metadata is recognizable, not that every upstream API is implemented.

## Trust and Permissions

An extension is executable code. Review it with the same care as a Python or npm
dependency.

- **Enabled** says the extension may activate.
- **Trusted** says you approve executing its code.
- **Granted permissions** record the exact capabilities you reviewed and
  approved.
- **Dependencies** must themselves be active before activation.

Permissions are consent and activation gates, not runtime capability
enforcement or an operating-system sandbox. Direct extension code may access
anything available to its process. A trusted native Python extension executes
inside nanobot. A Pi or OpenClaw extension executes in a separate Node.js
process, which improves failure isolation but is not a strong security
boundary. Their generated manifests therefore request `runtime.node`; granting
it acknowledges this execution model but does not confine the process. Use
containers or another OS sandbox for untrusted third-party code.

nanobot records a package content hash at installation. If files change later,
the package cannot activate, even if configuration marks it trusted; reinstall
it so the new contents can be reviewed.

npm installation uses lifecycle scripts disabled. This prevents package
`preinstall` and `postinstall` scripts from running during installation, but the
extension entry itself will run after you explicitly trust and enable it.

## Configuration

Most users should manage installed packages in the WebUI or CLI. Advanced
deployments can also define extension policy in `~/.nanobot/config.json`:

```json
{
  "extensions": {
    "enabled": true,
    "paths": ["/opt/nanobot/extensions"],
    "allow": [],
    "deny": ["acme.blocked"],
    "workspaceTrust": "ask",
    "entries": {
      "acme.review": {
        "enabled": true,
        "trusted": true,
        "permissions": ["workspace.read"],
        "config": {
          "mode": "strict"
        }
      }
    }
  }
}
```

Config entries do not rewrite the installation registry. See
[Configuration](./configuration.md#extensions) for exact fields. Actions from
the Extensions WebUI or CLI reload the extension host. Direct edits to advanced
`extensions` config fields are applied on the next process start.

## Diagnose an Inactive Extension

Start with:

```bash
nanobot extensions list
nanobot extensions inspect <extension-id>
```

Common causes:

| State or diagnostic | What to do |
|---|---|
| Untrusted | Review the package, then use `trust` |
| Requested permission pending | Grant the exact requested permission set |
| Disabled | Use `enable` or remove it from `extensions.deny` |
| Integrity mismatch | Reinstall and review the changed package |
| Missing dependency | Install and activate the named package, executable, environment variable, or extension |
| Contribution conflict | Disable one owner before activating the other |
| Compatibility notice | Read which upstream API was translated, degraded, or unsupported |
| Activation failed | Check the package entry, runtime dependency, and gateway logs |

Policy changes reload the active extension host. A broken extension becomes a
diagnostic and does not prevent unrelated extensions from being discovered.

## Remove an Extension

```bash
nanobot extensions disable <extension-id>
nanobot extensions uninstall <extension-id>
```

Uninstall removes the user-scope package and its local policy record. It does
not remove a built-in capability or a separately configured workspace copy.
