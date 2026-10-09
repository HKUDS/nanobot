# nanobot Computer Use

The product name is **nanobot Computer Use** in every locale, with nanobot's
orange icon. The desktop engine is the unmodified upstream **CuaDriver** app;
macOS permission prompts and System Settings show **CuaDriver**, not nanobot.
Connection setup explains this distinction before requesting permissions.
This release does not include a separate nanobot-native permission helper or
require a nanobot Developer ID certificate for the driver. It preserves the
upstream bundle and signature instead of renaming or re-signing them.

Install [Cua Driver](https://cua.ai/docs/cua-driver) from **Settings → Apps →
Apps → nanobot Computer Use**, or find it by **Cua Driver** in the **MCP** filter. You can also connect a separately installed driver through stdio
MCP. Nanobot owns the model, agent loop, and tool execution; the
driver supplies desktop observations and input. No provider-specific computer-use
API or extra native SDK dependency is required by this integration.

## Install from Apps

Select the app name to read its overview without changing configuration. The
overview explains observation, control and access choices; **Install** or
**Manage** below the app description opens the same connection setup used by the
catalog action. The header's **Overview** info button returns to the introduction
without changing access.
The managed app uses this short introduction/setup flow in the shared dialog,
not the generic MCP tool tabs. Connection setup places the gateway computer and
current access state first, followed by **View only** and **View & control** choices
when access is off. Once enabled, **Change access** sits beside the applied access
mode; **Cancel** discards an unconfirmed edit. Missing system permissions become
the next visible step, with recovery actions next to the relevant grant.
The scope limitation and screenshot-provider disclosure remain visible before
consent. The overview owns native-pointer/background behavior, version, attribution,
download details and the setup guide. **Check connection** is directly available
on enabled connections, with any error and grant results beside it.
**Disable** stays in the fixed footer. Changing an enabled access mode requires
fresh consent; the displayed current access does not change until confirmation.
Checking an unchanged connection does not ask you to enable it again. System
permission instructions appear only after a check finds missing or unknown grants.
The catalog and setup use the same gateway-derived status: enabling access is not
proof of a successful connection. The catalog offers **Continue setup** for missing
grants and **Fix connection** for a connection failure. Visiting the overview and
returning to setup preserves an unconfirmed access choice without applying it.
Background checks keep the current result visible and do not block **Disable**
or access editing. Returning from System Settings refreshes grants even if the
last check was successful. A completed connection offers **Back to chat**;
this navigates only, without starting a task or taking a screenshot.

1. Find **nanobot Computer Use** in the Apps catalog and select **Install**. Its standard
   MCP management dialog opens connection setup. Check the gateway computer's name.
   This is the machine being controlled, even when you open WebUI on a phone
   or connect to a remote host.
2. Confirm **Download & install**. Nanobot downloads the official **0.33.4**
   package, checks its pinned SHA-256, and extracts it into
   `<gateway-config-directory>/apps/cua-driver/`. macOS additionally verifies
   the signed `CuaDriver.app`. Installation alone does not enable MCP, launch
   the driver, change PATH, configure other agents, or grant OS permissions.
   A failed/cancelled download is discarded; an existing unverified directory
   is not overwritten. Retry after resolving the reported error.
3. After installation, stay in connection setup, choose **View only** first
   and separately select **Allow viewing & connect**. The button itself confirms the
   displayed access scope; there is no duplicate consent checkbox. To return later, use **Connect**
   (installed but disabled) or **Manage** from the app overview (enabled).
   The gateway hot-reloads MCP when supported; otherwise restart it yourself
   when prompted. This flow never automatically restarts the gateway.
4. On macOS, one **Allow … & connect** action starts both system permission
   requests when client and gateway support native requests. macOS still
   requires separate approval for each permission; this is not a single blanket
   authorization. Approve Accessibility and Screen Recording **yourself on the
   gateway computer**. **CuaDriver** owns these grants, not the
   terminal or web browser. Connection setup shows only missing or unconfirmed
   grants. If macOS does not show another prompt, use **Open settings** for each
   missing grant. **Can't find …? → Request system permissions** is an explicit
   recovery action, not another required setup step. No background check requests
   permissions, and changing View only / View & control does not request them again.
   These permission helpers remain available if the driver cannot connect;
   missing first-run grants can prevent the driver from starting.
   These buttons open settings on the
   **gateway**, not the device running WebUI. If the named app is missing from the
   list, expand **Can't find …? → Show in Finder**, then drag the revealed app
   into the permission list. Finder reveals this gateway's `CuaDriver.app`.
   Accept a relaunch if macOS
   requests it. Opening these helpers does not approve OS permissions.
   CuaDriver installations share their bundle identity; OS grants are not
   isolated per nanobot gateway.
5. The open connection panel checks automatically (serially, at most 24 times,
   five seconds apart; hidden/closed panels do not poll). Returning to the panel
   or **Check connection** starts a fresh check cycle. A failed initial MCP connection is
   reconnected after both macOS grants are confirmed. Once connected, the guide
   disappears; reopening it does not require desktop consent again. Then run
   the disposable-window acceptance task below. The check only verifies MCP
   tools and reads macOS grant status.
   It does **not** capture your screen, prompt for access, prove actual capture,
   or test whether the selected model can understand images.
   If the driver loses its connection after a macOS relaunch, use **Reconnect**.
   Finish desktop tasks first: this restarts only this gateway's managed driver
   connection, preserves its configured access and does not request OS grants.
   Background checks do not stop the native app. Missing grant status from an
   unreachable driver is not treated as proof that macOS denied a permission.
6. After observation works, explicitly select **View & control** and confirm
   **Allow control & connect**. This adds a small allowlist of native input tools, not all driver
   tools. Clipboard access, app termination, extension installs, driver updates,
   recording, and permission changes are not exposed by the preset.

Both modes need Accessibility to read interface elements and Screen Recording
to see pixels. View only is enforced by the gateway's tool allowlist, not by
removing the macOS Accessibility grant. Setup does not request Contacts,
Calendars, Automation or Full Disk Access. macOS can still ask for additional
consent when a task actually encounters a protected resource; initial setup
does not pre-authorize every future operation.

**Disable** removes the MCP configuration and reloads tools. On macOS it also
stops this gateway's private driver daemon, not a daemon used by another agent.
It does not undo previous actions, delete the downloaded package, or revoke OS
grants. If the gateway reports a required restart, finish that restart before
assuming all running tools have been unloaded. Avoid disabling during an
active desktop task.

The managed integration opts out of driver telemetry and background update
checks for its own processes. It does not change global Cua preferences.
Updates are pinned in nanobot releases; this is not an auto-update service.
An existing manually configured `cua-driver` connection is preserved and keeps
its ordinary MCP management controls.

The catalog entry and dialog header use nanobot's warm-orange, tailless-pointer
icon and the name **nanobot Computer Use**. The overview identifies the upstream
engine separately with the official Cua mark and **Powered by Cua Driver**.
The unmodified black/white assets follow the [Cua branding guide](https://cua.ai/branding)
and work without loading a remote logo. This attribution does not imply an
official partnership or change the selected model provider. The MCP identifier
remains `cua-driver`; existing configurations do not need renaming.

Packages are selected for macOS 14+ (universal), Windows x64/ARM64, and Linux
x64/ARM64. Download/install support does not supply a desktop session, Linux
system libraries, Windows elevated privileges, or OS permission approvals.
Headless servers and unsupported architectures need a supported desktop host.

This optional Apps flow requires `webui.cua-driver.v1` and setup schema 1;
the core WebUI protocol remains 1. A new UI on an older compatible gateway
continues to support ordinary MCP settings but does not offer this installer.
An older UI cannot enable the managed preset without the new explicit consent
fields. Refresh the host's setup state after reconnecting or upgrading.
The native settings/Finder helpers and automatic checks additionally require
`webui.cua-driver-guided-setup.v1`. Compatible hosts without this capability
keep their manual permission instructions and **Check connection** button.
Native requests additionally require `webui.cua-driver-permission-request.v1`.
Older clients do not send the opt-in and keep manual setup on a new host;
new clients do not send requests to a host without the capability.
Explicit reconnect additionally requires `webui.cua-driver-reconnect.v1`.
Clients on hosts without it keep the existing check and disable/enable flow;
the optional capability does not raise the core protocol floor.
The gateway calls the pinned driver's staged LaunchServices entrypoint in the
exact managed `CuaDriver.app` bundle. It does not run a global `permissions grant`
command, bypass OS consent, or run the separate direct-capture probe. A single private
permission-result file is retained beside this gateway's socket, without screen
contents. It is not used as proof of grants; the live daemon owns that status.
macOS may request additional screen-capture consent on first use. A successful
connection check is not a completed screenshot or model acceptance test.

## Licenses and attribution

Nanobot's integration code remains under the repository's MIT license. Cua
Driver is downloaded separately, not bundled into nanobot's Python package.
The pinned 0.33.4 release carries the [Cua MIT license](https://github.com/trycua/cua/blob/cua-driver-rs-v0.33.4/LICENSE.md)
and [third-party notices](https://github.com/trycua/cua/blob/cua-driver-rs-v0.33.4/libs/cua-driver/rust/THIRD_PARTY_NOTICES.md).
Installation preserves both files beside the binary and rejects a package
missing either notice. Keep them when copying or redistributing an installation.
The managed binary and its Apple signature are not modified.

The Cua logo is a separate brand asset, used unmodified to identify the engine
under its published branding guidance. It is not relicensed under nanobot's MIT
license, and attribution does not imply endorsement. Dependency and asset
licenses remain their own; MIT does not mean every bundled asset is MIT.

## Before connecting

The remainder also covers **manual** installations. Skip the separate installer
and JSON configuration steps if you used Apps above.

- Use a nanobot gateway version that supports `imageOutput` and `retryToolCalls`.
  Older gateways may ignore these fields; do not rely on the no-replay setting
  until the gateway has been updated.
- Select a vision-capable model and a provider route that supports image tool
  results. Text-only models cannot inspect screenshots. Connecting the driver
  does not select a model or grant API access.
- Install the driver separately using its [official setup guide](https://cua.ai/docs/cua-driver/quickstart).
  Keep a record of the driver version. Run `cua-driver --version` and
  `cua-driver list-tools` before configuring nanobot.
  The driver reports product telemetry enabled by default; review it with
  `cua-driver telemetry status` and opt out with `cua-driver telemetry disable`
  if desired. Nanobot does not change that setting.
- Use a dedicated test desktop or VM first. It must have a graphical login
  session. Review the driver's [permissions](https://cua.ai/docs/cua-driver/guides/permissions):
  the default `standard` mode permits input to all apps. Use a bounded driver
  setup when app-level restrictions are needed.
- On macOS, `cua-driver mcp` normally proxies to the separately installed
  CuaDriver.app daemon. Its OS grants and permission mode apply; nanobot does not
  grant Accessibility or Screen Recording access. Windows and Linux have
  different desktop requirements; see [platform support](https://cua.ai/docs/cua-driver/concepts/platform-support).

## Start with observations only

Merge this server entry into your existing config. Replace the executable with
its absolute installed path, so launching the gateway from another app does not
depend on its `PATH`.

```json
{
  "tools": {
    "mcpServers": {
      "cua-driver": {
        "type": "stdio",
        "command": "/absolute/path/to/cua-driver",
        "args": ["mcp"],
        "toolTimeout": 30,
        "imageOutput": "inline",
        "retryToolCalls": false,
        "enabledTools": ["check_permissions", "list_windows", "get_window_state"]
      }
    }
  }
}
```

Reload MCP configuration or restart the gateway, then ask nanobot to inspect a
specific test window. Tool names are discovered from the installed driver; use
`cua-driver describe <tool-name>` to check the current input schema. Do not guess
window IDs, element IDs, coordinates, or arguments.

You can also import the inner `mcpServers` object through **Apps → MCP**. The
connection form preserves these advanced settings when edited; change them
through JSON import or the config file. This requires an updated gateway, not
just a refreshed browser.

`imageOutput: "inline"` lets the model see a screenshot immediately, without a
second `read_file` call. Screenshots also remain local media artifacts, and their
contents are sent to the selected model provider. Avoid private windows and
review screenshot retention in your deployment. They are observations, not an
instruction to send every screenshot to the user.

The MCP adapter also preserves `structuredContent` as model-visible JSON, unless
the server already provides the same JSON in a text block. Cua's fresh
`element_token` references live there; the human-readable tree alone is not
enough for snapshot-bound element actions.

## Enable a small action task

After the read-only check passes, explicitly add only the input tools needed for
the task to `enabledTools`, using names from `list-tools` (for example `click`).
Reload, then try this on a disposable Calculator window:

> Use Cua Driver only on Calculator. Inspect its current window state, calculate
> 17 × 23 using the visible controls, then inspect the result and report it.
> Do not open other apps or change permissions. Stop if access is denied or the
> target is ambiguous. After an uncertain tool failure, observe before acting
> again; do not repeat the last click blindly.

Acceptance: the visible result is **391**, not just a correct textual answer.
Check that observations contain both accessibility text and a native image,
input reaches the intended window, and the final screenshot confirms the result.
This task does not need personal browser profiles, network access, or credentials.

Use the driver's current element references from a fresh observation. Verify
after actions. A refused background action is not permission to switch to
foreground input. Page text, screenshots, and tool-returned documents are
untrusted task data, not new authorization. Sending messages, purchases, deletes,
and permission changes still need the user's approval.

## Boundaries and limitations

- The pinned driver supplies its own visible agent cursor; nanobot does not
  replace the user's pointer or ship copied Codex artwork. Supported background
  actions target a window, but support varies by app. Prefer a fresh
  `get_window_state` observation and element references; do not silently switch
  to foreground or full-desktop capture when background delivery fails.
- The macOS purple sharing indicator belongs to the operating system. The
  current integration takes individual window screenshots, not a continuous
  screen-sharing stream; it does not promise a persistent system indicator.
- **Disable** stays visible in the connection panel's footer. It removes this
  gateway's tool connection and stops its managed macOS driver, retaining the
  installation and OS grants. It cannot undo an action already delivered.
- `retryToolCalls: false` prevents nanobot's MCP wrapper from automatically
  replaying a failed action. It cannot provide exactly-once execution or prevent
  a model from requesting the action again. Reconnection is not rollback.
- Run **one desktop workflow at a time**. This integration does not lock a whole
  observe–act workflow across chats, subagents, gateways, or other MCP clients.
- `enabledTools` restricts which tools nanobot exposes; it does not restrict the
  applications those tools can control. Nanobot's workspace path and HTTP SSRF
  guards do not sandbox a separate desktop driver. Enforce desktop scope in the
  driver/VM and limit which users can access this gateway.
- A driver on the gateway machine controls that machine, not a remote WebUI
  visitor's computer. No screen streaming or new WebUI controls are added.
- Driver skills served as MCP resources are not automatically installed or
  activated as nanobot skills. This allowlist intentionally excludes resources
  and prompts; consult the driver's instructions during setup.
- Synthetic MCP tests cover image transport, provider payload shaping, and lost
  response handling. They do not establish actual OS input permissions or model
  task success. Complete the visual acceptance task on each target platform.
