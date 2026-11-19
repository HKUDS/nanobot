# Connect to an Existing Remote nanobot

Use your local nanobot WebUI to connect directly to a nanobot instance already running on a remote Linux server—without manually setting up SSH port forwarding or exposing a public admin port.

Open your local WebUI, click the host name (**Local**) at the bottom of the sidebar, and choose **Manage connections…**. From there, pick one of two ways to connect:

- **Quick pairing (recommended for Linux servers):** Copy one command, run it on the server, and click the return link—no SSH key setup or config path needed.
- **Existing SSH settings:** Connect using an SSH address (like `ubuntu@your-server`) or an alias from your local `~/.ssh/config`.

> [!NOTE]
> This connects to a nanobot instance **already running on your server**. It does not install nanobot, copy workspaces, or move conversations.

## Quick Pairing (Recommended)

For a Linux server with nanobot already installed:

1. In your local WebUI, open **Manage connections… → Connect to remote nanobot** and click **Copy command**.
2. Open your server's terminal (for example, your cloud provider's web console or SSH) and run the copied command in the environment where nanobot is installed.
3. Follow the prompts to pick the nanobot configuration (if there are multiple), confirm the server address if asked, and approve **full nanobot access** for this computer.
4. Click the **Return to nanobot** link printed in the terminal (on the same computer and browser), review the server details, and click **Connect**.

If your terminal cannot open links, choose **Other ways → Use a connection code instead** in the WebUI and paste the `nbpc1.…` code from the terminal.

- **Security:** The invitation expires in 10 minutes, the server's SSH host key is pinned automatically, and the dedicated device key expires after 90 days. No relay server or public WebUI port is used.
- **Requirements:** Linux server with OpenSSH (`restrict` and `expiry-time` support), `/usr/bin/python3`, and an Ed25519 host key. Windows servers and containers are not supported by quick pairing—use existing SSH settings instead.

> [!CAUTION]
> A paired connection grants **full access to nanobot** on that server, including its tools and files. Never import a connection code from someone you do not trust.

## Connect with Existing SSH Settings

Choose **Other ways → Use existing SSH settings** if you already have SSH key access to the server (including Docker or non-systemd setups):

1. Enter an SSH address (such as `ubuntu@your-server`), pick a suggested host from your `~/.ssh/config`, or paste a simple SSH command like `ssh -p 2222 -i ~/.ssh/key ubuntu@your-server`.
2. Expand **Connection options** if you need a custom port, SSH config file, private key path, remote config path, or service account.
3. Click **Connect**. On first connection, verify the server's SSH fingerprint before continuing.

After SSH connects, nanobot looks for your server's config and `nanobot*.service` systemd units automatically. If it cannot find one (for example, in Docker or a custom path), enter the server's config path manually.

**Prerequisites for existing SSH:**

- Your local WebUI runs on localhost with the system OpenSSH client available.
- Your SSH key already works for that server (encrypted keys should be unlocked in your SSH agent; interactive SSH passwords are not supported).
- Python 3 (`python3` or `python`) is available on the server, and the remote nanobot has `tokenIssueSecret` (or `token`) set in its `config.json`.

## Switching, Disconnecting, and Revoking

- **Switch hosts:** Click the host name at the bottom of the sidebar to switch between **Local** and saved servers (up to four connected at once). Each host keeps its own chat view and draft while connected.
- **Disconnect:** Closes the local SSH tunnel without stopping the remote nanobot.
- **Forget server:** Removes the saved entry and local pairing keys from this computer. It does not touch remote conversations or files.
- **Revoke a paired device:** Forgetting a server locally does not revoke its server-side key. To revoke access on the server, run the command shown in the server's **Connection details**:

```bash
nanobot remote revoke DEVICE_ID --ssh-user LOGIN_ACCOUNT
```

### Versions and updating the right machine

Open a server's **… → Version & compatibility** in **Manage connections…** to check whether your local WebUI and remote gateway are compatible. Same-version local and remote installs are recommended—align versions first when troubleshooting.

- **Update this server:** Update nanobot on the remote machine using its original install method, restart it, and reconnect.
- **Update this computer:** Update your local nanobot installation and reconnect.

See [Updating nanobot](../updating.md) for update steps.

## Troubleshooting

- **SSH works in terminal but not in WebUI:** Make sure nanobot was started in an environment that can reach your SSH agent, and check **Connection options** for the right key or SSH config file.
- **Paired device rejected after expiry or revocation:** Re-run **Quick pairing** to issue a fresh device key.
- **Remote WebUI password or port changed:** Re-pair the server (or update the connection settings) so nanobot picks up the new config.
- **Backing up local remote-connection settings:** Stop your local gateway and back up the `webui/` folder beside your local `config.json` (preserving private file permissions). Do not copy it to an untrusted computer, as it grants access to your paired remote servers.
