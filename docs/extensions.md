# Extensions

Extensions add native tools, slash commands, or lifecycle hooks without
changing nanobot core. An extension is a Python package with one manifest and
one registration entry point.

Use an extension when a capability needs executable integration with nanobot.
Use a [skill](./skills.md) when instructions alone are enough, an App when the
agent should call an external CLI, and MCP when a service already exposes an
MCP server.

## Install

Install from a Git repository:

```bash
nanobot extensions install https://github.com/acme/nanobot-review.git
```

Install a local package while developing it:

```bash
nanobot extensions install /absolute/path/to/nanobot-review --kind local
```

Git installs may select a branch, tag, or commit:

```bash
nanobot extensions install https://github.com/acme/nanobot-review.git \
  --ref v1.2.0
```

The WebUI **Extensions** page exposes the same Git and local installation
flows. Local paths are accepted only from a browser running on the nanobot
host.

## Review before activation

New packages are installed enabled but untrusted. They cannot execute until
you review the manifest, grant every requested permission, and trust them:

```bash
nanobot extensions inspect acme.review
nanobot extensions permissions acme.review workspace.read
nanobot extensions trust acme.review
```

Use `list` to check the result:

```bash
nanobot extensions list
```

Disable, untrust, or remove a package at any time:

```bash
nanobot extensions disable acme.review
nanobot extensions untrust acme.review
nanobot extensions uninstall acme.review
```

Changes made in the WebUI reload its gateway extension host immediately.
Changes made by the standalone CLI take effect the next time the gateway or
agent process starts. Failed registrations are rolled back and reported as
diagnostics.

## Safety model

Extensions are executable Python code. nanobot provides these controls:

- packages are copied into `~/.nanobot/extensions/` with an integrity digest;
- package symlinks and special files are rejected;
- installation, permission grants, trust, and activation are separate steps;
- changed package contents invalidate trust;
- registration is transactional, so a failed extension does not leave tools,
  commands, or hooks behind;
- remote WebUI clients cannot grant trust or permissions.

Permission declarations are consent gates, not an operating-system sandbox.
Only install code you are willing to run with the same account as nanobot.

## Package compatibility

The core runtime intentionally executes only the native nanobot Python
contract. Pi and OpenClaw packages are not loaded directly. Compatibility
adapters can be distributed as separate nanobot extensions later without
adding JavaScript runtimes or package-market policy to the agent core.

See [Extension Authoring](./extension-authoring.md) to build a package.
