# Updating nanobot

Always update nanobot using the same method you used to install it. Do not switch package managers to work around an error.

## Update from the WebUI

1. Click the update notice in the sidebar, or open **Settings → About → Update** (opening the dialog only checks for updates—it does not install or restart anything).
2. Review the target version and affected gateways. Active tasks must finish before shutdown.
3. Click **Update & restart**. nanobot downloads and verifies the release, backs up affected profiles, installs the update, and restarts your background gateways (not your computer or browser).
4. Wait for **Update complete**, then click **Done** to reload the interface.

In-app updates work for official-installer environments and supported `uv` tool installations running a background gateway. Other install methods display exact copy-and-run update commands in the dialog. Remote browsers require explicit package-install permission on the gateway.

> [!NOTE]
> Automatic updates verify official release checksums before installing. If verification fails, stay on your current version, retry later, and report persistent errors rather than bypassing verification.

## Stable and Preview

**Settings → About → Receive preview updates** is off by default. Turn it on if you want early access to new features (with a higher risk of bugs). It never downloads or installs updates automatically.

Turning it back off returns you to stable updates without downgrading—if your Preview build is newer than the latest stable release, nanobot stays on it until a newer stable release arrives.

## Installation Owners

When in-app updating is unavailable, update on the **gateway computer** using the original installation method:

| Installation method | How to update |
|---|---|
| Official installer | Use WebUI **Update & restart** |
| `uv` tool | Use WebUI **Update & restart**, or run `uv tool upgrade nanobot-ai` in the original environment |
| `pipx` | Run `pipx upgrade nanobot-ai` (preserve any custom options or injected packages) |
| Python virtual environment (`pip`) | Run `nanobot update` or `<venv-python> -m pip install --upgrade nanobot-ai` (include any extras you originally installed) |
| Source checkout | Pull the latest branch in Git, preserve local changes, and follow [`CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Docker / Compose | Pull or rebuild the image and recreate the service with your existing data volumes |

For manual updates: stop nanobot, back up your config and workspace, run the update, restart, and verify the running version in **Settings → About** or `nanobot --version`.

## Recover an Interrupted Update

Closing or refreshing your browser does not stop an in-progress update. If your connection drops, wait for it to reconnect and check status with **Check again**—do not start a second update while one is already running.

For official-installer environments, nanobot keeps a backup of the previous program before modifying packages. If installation fails, automatic recovery retries once or restores the previous version (without touching your config or conversations) and reports **Previous version restored**.

### Standalone recovery

If automatic recovery fails, the WebUI displays a repair command with the saved job ID. Run it on the **gateway computer** as the original user (it only requires your base Python 3.11+):

**macOS / Linux**

```sh
python3 -I -S ~/.nanobot/updates/recover.py <job-id>
python3 -I -S ~/.nanobot/updates/recover.py <job-id> --repair
```

**Windows PowerShell**

```powershell
python -I -S "$env:USERPROFILE\.nanobot\updates\recover.py" <job-id>
python -I -S "$env:USERPROFILE\.nanobot\updates\recover.py" <job-id> --repair
```

The first command inspects the saved job; `--repair` verifies the files and asks for confirmation before repairing (add `--yes` to skip the prompt).

### Explicit recovery before package mutation

<details>
<summary>CLI plan inspection and pre-install retry</summary>

To inspect an update plan from the CLI without installing anything (plans expire after 15 minutes):

```bash
nanobot update --plan
nanobot update --plan --channel preview
```

If an update failed during shutdown **before** packages were modified, you can inspect and retry the saved job:

```bash
nanobot update --job <plan-id>
nanobot update --job <plan-id> --retry-handoff \
  --previous-confirmation <execution-confirmation-id> --confirm-restart
```

If packages were already partially changed, use [Standalone recovery](#standalone-recovery) instead.

</details>

## Version Migration Notes

<details>
<summary>Upgrading from older JSONL installations (pre-0.4)</summary>

0.4.x releases automatically import legacy JSONL chat history and per-feature proxy settings; these importers are scheduled for removal in 0.5.0.

1. Stop nanobot and back up your complete config directory and workspace.
2. Upgrade to 0.4.x using your original installation method.
3. Start nanobot, verify your conversations and shared proxy settings, and confirm a restart works cleanly before eventually upgrading to 0.5.0.

</details>

### Standalone API service removal

<details>
<summary>Notes if you previously used <code>nanobot serve</code> or shared sessions</summary>

- **`nanobot serve` removed:** The standalone OpenAI-compatible `/v1` HTTP server (`nanobot serve` and the `nanobot-api` Compose service) has been removed. The Gateway, WebUI, Python SDK, and OpenAI-compatible model connections remain supported. Stop any old `nanobot serve` process or `nanobot-api` container before upgrading. Old `api` config blocks are ignored, and old API sessions (`api:...`) remain readable via [the Python SDK](./python-sdk.md#botsessions).
- **Shared sessions removed:** `agents.defaults.unifiedSession` is no longer supported and is ignored.

</details>

For contributor details on the update protocol, see [Update protocol](./update-protocol.md).
