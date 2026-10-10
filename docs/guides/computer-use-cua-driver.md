# Computer Use

The product name is **Computer Use** in every locale, with nanobot's
orange icon. The name and short app description stay in English in the catalog
and setup dialog; interface actions and permission instructions follow the
selected interface language. New macOS 14.2+ installations use **nanobot Computer Use**,
including that name in permission prompts and System Settings. Its native payload
comes with the macOS platform wheel; users do not need Rust or developer staging.
Existing official **CuaDriver** installations keep their identity and grants until
explicitly uninstalled. Linux and Windows retain the pinned official driver.
Connection setup always names the actual installed permission owner.

Install [Cua Driver](https://cua.ai/docs/cua-driver) from **Settings → Apps →
Apps → Computer Use**, or find it by **Cua Driver** in the **MCP** filter. You can also connect a separately installed driver through stdio
MCP. Nanobot owns the model, agent loop, and tool execution; the
driver supplies desktop observations and input. No provider-specific computer-use
API is required. No SDK or model installation is required on the user's computer.

## macOS native sharing

The host in [`native/computer-use`](../../native/computer-use/README.md)
embeds the pinned MIT Cua SDK and the branded orange/pink cursor. It is **not**
the official 0.33.4 binary. Its permission identity is **nanobot Computer Use**;
it never renames the upstream app or borrows its signature or macOS grants.
The platform wheel supplies a verified release payload; neither the model nor the
WebUI can select a source archive, executable or download URL. The manifest binds
source revision, architecture, application source and archive checksum. Source
checkouts can build into `nanobot/apps/computer_use_bundle/` using the linked guide.
Missing native payloads produce an installation error, not a silent switch to
CuaDriver. To switch an older installation, disable and uninstall it first.

The native build uses the same Apps install/consent/disable/uninstall dialog.
Installation does not start it. Connecting requests Accessibility first; Screen
Recording is requested only when the user advances that step. Permission checks
never create new prompts or capture screen content. macOS still owns both grants.
The current builder uses ad-hoc signing, not Developer ID or Apple notarization.
It does not bypass Gatekeeper. Public distribution requires the clean-install and
signing decision gates in the [release checklist](../releasing.md).

Each gateway agent run owns one native connection, shared across its desktop
tools. `get_window_state(pid, window_id)` selects a real window stream before
observing or acting. macOS supplies the purple sharing indicator; the SDK supplies
the cursor for supported actions. The sharing stream has no full-display fallback,
records no audio and saves no preview frames. Agent screenshots still use nanobot's
normal media artifacts, as described below. Other tasks cannot replace an active task's window.
Task completion, cancellation and MCP disconnect release the stream. Idle sharing
expires after 60 seconds. **Stop Sharing** revokes the SDK session and persists a
pause; tool calls and automatic reconnection cannot clear it. Only an explicit
Apps reconnect or new access confirmation resumes desktop access.

Window selection is not an app allowlist: the agent can select a different window
in a later observation, and foreground/input behavior still depends on the target
application. Restrict access to this gateway accordingly. The sharing preview
stays local; SDK screenshots from agent tasks may reach the selected model.

The package preserves Cua's original MIT notice and upstream authorship, plus
nanobot's MIT notice and dependency licenses. UniFFI dependencies retain MPL-2.0;
their unchanged sources and full license are included in `Contents/Resources/MPL-SOURCES.tar.gz`.
Host source and build inputs are in `NANOBOT-SOURCES.tar`; notices also preserve
the Inter font license and upstream derived-code credits.
This does not relicense those dependencies as MIT. See the
[Mozilla distribution guidance](https://www.mozilla.org/en-US/MPL/2.0/FAQ/#q8-i-want-to-distribute-outside-my-organization-executable-programs-or-libraries-that-i-have-compiled-from-someone-elses-unchanged-mpl-licensed-source-code-either-standalone-or-part-of-a-larger-work-what-do-i-have-to-do).

Native metadata requires the additive `webui.computer-use-native.v1` capability.
Unknown permission identities remain unconfirmed on older clients; unrelated
MCP features keep using WebUI protocol 1.

## Install from Apps

The app name and catalog action open the same setup window without changing
configuration. Before installation it shows the three core capabilities, the
gateway computer and a fixed **Install** footer (or **Download & install** for the
official driver). This installs the verified payload directly; there is no second installation page. Progress
and the subsequent access choice stay in the same dialog. Its height follows
the content, capped by the viewport, with the action footer outside the scrolling
body; it does not reserve blank space for another screen.
The header's **Overview** info button opens supporting details in the shared
animated popover without replacing or resizing setup. Close the popover or press
Escape to return focus to the info button without applying changes. There is no navigation-only Install
button under the title.
The managed app uses this flow in the shared dialog, not the generic MCP tool
tabs. After installation, connection setup places the gateway computer and
current access state first, followed by **View only** and **View & control** choices
when access is off. Once enabled, the compact current-access row is itself the
**Change access** control. It stays visible while expanded; selecting it again
collapses the choices and discards an unconfirmed edit. **Cancel** in the footer
does the same and returns focus to that row. Missing or unconfirmed system
permissions take priority over reconnecting: the setup shows one permission
checklist, with actions for pending grants and a checkmark for confirmed grants.
Only after both Mac grants are confirmed does a failed connection make
**Reconnect** the primary action. If the private connection is absent, setup help
also offers an explicit reconnect for users who have already granted access and
accepted a macOS relaunch. The computer and current access remain visible as compact metadata.
The scope limitation and screenshot-provider disclosure remain visible before
consent. The overview owns native-pointer/background behavior, version, attribution,
download details and the setup guide. Technical download details are folded under
**Installation details**. **Check connection** is directly available in the footer
while setup is pending; after connection or when **Reconnect** is the next step,
it moves into **Connection details** so only the next step is prominent. Check limitations and recovery help
live in **Connection details** after authorization. During authorization, a single
**Can’t find the app or connect?** disclosure contains missing-app Finder recovery,
post-relaunch recovery and check limitations. The default view shows the current
instruction, the matching macOS pane names and a full-width settings button; it does not repeat status prose
or display a second connection-details disclosure. Both use the shared animated
disclosure. Action errors stay visible inside setup,
including while editing access; they never require opening the help section.
An explicit **Check connection** shows **Checking…**, then keeps a **Manual check
result** in the dialog footer. It distinguishes a confirmed connection, missing
Mac permissions, unknown grants, disconnected tools, an incomplete host response
and a failed request. The result includes a next step and never claims to verify
screen capture or model vision. Background checks keep updating live status but
do not clear or replace this manual receipt. Another explicit check or settings
action replaces it; a superseded request cannot restore an outdated result.
Opening setup does not focus the secondary **Change access**
action.
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
last check was successful. A completed connection explains the next step and offers **Back to chat**;
this navigates only, without starting a task or taking a screenshot.

1. Find **Computer Use** in the Apps catalog and select **+** (Install). Its standard
   MCP management dialog opens the same installation screen as the app name.
   Check the gateway computer's name.
   This is the machine being controlled, even when you open WebUI on a phone
   or connect to a remote host. The catalog button only opens setup; it does not
   download the driver or enable desktop access. Its tooltip and accessible name
   describe the action, and closing setup returns keyboard focus to its opener.
2. Confirm **Install** on macOS or **Download & install** on other platforms.
   Nanobot verifies the bundled native payload on macOS; Linux/Windows download
   the pinned official **0.33.4** package. The SHA-256-checked package is extracted
   into `<gateway-config-directory>/apps/cua-driver/`. macOS additionally verifies
   the actual app's code signature. Installation alone does not enable MCP, launch
   the driver, change PATH, configure other agents, or grant OS permissions.
   A failed/cancelled download is discarded; an existing unverified directory
   is not overwritten. The button shows **Installing…** during the download.
   You can close and reopen the setup dialog without cancelling or starting
   another download. Errors stay visible in setup; retry after resolving them.
3. After installation, stay in connection setup, choose **View only** first
   and separately select **Allow viewing & connect**. The button itself confirms the
   displayed access scope; there is no duplicate consent checkbox. To return later, use **Connect**
   (installed but disabled) or **Manage** from the catalog (enabled).
   The gateway hot-reloads MCP when supported; otherwise restart it yourself
   when prompted. This flow never automatically restarts the gateway.
4. On macOS, one **Allow … & connect** action starts the signed driver's
   first-run permission flow. Setup and the MCP connection reuse the same
   daemon, including while it waits for grants; nanobot does not launch a
   second permission-request process alongside it. macOS still
   requires separate approval for each permission; this is not a single blanket
   authorization. Approve Accessibility and Screen Recording **yourself on the
   gateway computer**. **nanobot Computer Use** (or **CuaDriver** for an existing
   official installation) owns these grants, not the
   terminal or web browser. Connection setup shows only missing or unconfirmed
   grants. The guide highlights one permission at a time, with one **Open
   settings** action for the selected step. A confirmed first grant advances
   the guide to Screen Recording, but never opens another page automatically.
   Either unconfirmed step remains selectable if the driver is unreachable;
   selecting a step or opening settings is not recorded as permission granted.
   Newer macOS calls Accessibility **Device Control & Data Access** and may
   call Screen Recording **Screen & System Audio Recording**. These are
   separate pages. The current step shows both names directly, rather than assuming the
   browser's operating system matches the gateway.
   The native host requests Accessibility first and Screen Recording only when
   you advance that step. For an existing official installation, the pinned
   upstream 0.33.4 startup can still request both permissions and
   open both settings panes, leaving the recording pane in front of a control
   permission alert. This native behavior is not fixed by the WebUI guide:
   finish the matching system prompt, then open the guide's current page.
   The redundant **Request system permissions** recovery button has been
   removed: joining an existing daemon did not re-register a missing entry.
   No background check requests
   permissions, and changing View only / View & control does not request them again.
   These permission helpers remain available if the driver cannot connect;
   missing first-run grants can prevent the driver from starting.
   These buttons open settings on the
   **gateway**, not the device running WebUI. If the named app is missing from the
   list, expand **Can’t find the app or connect? → Show in Finder** within the current step, then drag the revealed app
   into the permission list, or use the list's **+** button to add it. Turn on the
   added entry. Finder reveals this gateway's actual installed app.
   Accept a relaunch if macOS
   requests it. macOS may reopen the app without nanobot's private socket arguments.
   If both grants are allowed but checks cannot reach the driver, choose
   **Can’t find the app or connect? → Reconnect**. This restores this gateway's
   managed connection with its existing access scope; it does not treat a missing
   connection as proof of granted or denied permissions, and never runs automatically.
   Opening settings or Finder does not approve OS permissions.
   Installations of the same app share their bundle identity; OS grants are not
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
After disabling, **Uninstall** removes only this gateway's verified installed
package. It requires a separate confirmation and the additive
`webui.cua-driver-uninstall.v1` capability. A failed native stop keeps the package
for recovery. Chat data, staged install archives and other driver installations
remain. OS grants are retained by default: uninstalling files is not a fresh
macOS permission test.

For the independent **nanobot Computer Use** native build, the confirmation also
offers **Also revoke Mac permissions**, unchecked by default. This needs the
additive `webui.computer-use-uninstall-reset.v1` capability. It resets only
Accessibility and Screen Recording decisions for `io.nanobot.computer-use`,
using Apple's [documented reset tool](https://developer.apple.com/documentation/xcode/resetting-access-to-protected-resources-in-macos).
After reinstalling and connecting, approve those grants again. macOS identifies
the app, not the gateway: this reset affects all instances of that app on the
same Mac. It never resets the official CuaDriver identity. Official-driver
installs retain their grants; revoke those separately in System Settings.
A failed reset leaves desktop access disabled and the package installed for
retry; some grants may already have been reset. The gateway stops the driver
before resetting grants and removes files only after both resets succeed.
New clients hide this option on older hosts, and a distinct consent value makes
older hosts reject a reset request rather than silently performing a normal
uninstall. Ordinary uninstall remains compatible with older clients.

Installing again does not enable access automatically. Install/uninstall/settings
mutations are serialized; background permission checks never delay disabling.
The dialog stays open when disabling from the **Ready** list. Closing it then
returns keyboard focus to catalog search if its original row is no longer listed.
If native startup or shutdown fails after access was saved, the UI refreshes the
gateway's persisted configuration and keeps the failure visible; it does not
assume that a failed connection means access was never enabled.

The managed integration opts out of driver telemetry and background update
checks for its own processes. It does not change global Cua preferences.
Updates are pinned in nanobot releases; this is not an auto-update service.
An existing manually configured `cua-driver` connection is preserved and keeps
its ordinary MCP management controls.

The catalog entry and dialog header use nanobot's warm-orange, tailless-pointer
icon and the name **Computer Use**. Catalog sorting uses that visible name,
while searching still accepts the upstream Cua Driver name. The overview identifies the upstream
engine separately with the official Cua mark and **Powered by Cua Driver**.
The unmodified black/white assets follow the [Cua branding guide](https://cua.ai/branding)
and work without loading a remote logo. This attribution does not imply an
official partnership or change the selected model provider. The MCP identifier
remains `cua-driver`; existing configurations do not need renaming.

New packages are selected for macOS 14.2+ (arm64 or x86_64), Windows x64/ARM64,
and Linux x64/ARM64. Existing official macOS 14+ universal installations are
preserved. Download/install support does not supply a desktop session, Linux
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
The explicit native setup action additionally requires
`webui.cua-driver-permission-request.v1`. Older clients do not send this
extra setup opt-in; connecting MCP can still invoke the upstream driver's
normal startup permission flow. New clients do not send setup requests to a
host without the capability.
Explicit reconnect additionally requires `webui.cua-driver-reconnect.v1`.
Clients on hosts without it keep the existing check and disable/enable flow;
the optional capability does not raise the core protocol floor.
The gateway starts the exact managed app through LaunchServices, using its
actual bundle path rather than choosing another installation by name.
Native setup, MCP launch and shutdown share the same per-instance lifecycle lock.
The native host owns sequential permission requests; an existing official
installation retains the upstream first-run gate. The gateway does not run
an additional permissions helper, a global
`permissions grant` command, bypass OS consent, or run the separate direct-capture
probe. Read-only checks remain non-launching and non-prompting.
macOS may request additional screen-capture consent on first use. A successful
connection check is not a completed screenshot or model acceptance test.

## Licenses and attribution

Nanobot's integration code remains under the repository's MIT license. The
macOS wheel bundles the native host, Cua/nanobot MIT notices, dependency/font/runtime
licenses and the source materials described above. The release packager refuses
missing materials. Third-party licenses are not replaced by nanobot's MIT license.

The official Cua Driver binary used on Linux/Windows and by existing macOS
installations is downloaded separately. Its pinned 0.33.4 release carries the
[Cua MIT license](https://github.com/trycua/cua/blob/cua-driver-rs-v0.33.4/LICENSE.md)
and [third-party notices](https://github.com/trycua/cua/blob/cua-driver-rs-v0.33.4/libs/cua-driver/rust/THIRD_PARTY_NOTICES.md).
Installation preserves both files beside the binary and rejects a package
missing either notice. Keep them when copying or redistributing an installation.
The official binary and its signature are not modified. Native builds use their
own nanobot identity and signature; they do not borrow Cua's signature or grants.

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
  legacy/manual official-driver path takes individual window screenshots and does not
  promise a persistent indicator. The default macOS native host above owns a
  real window-sharing stream with a system stop callback.
- **Disable** stays visible in the connection panel's footer. It removes this
  gateway's tool connection and stops its managed macOS driver, retaining the
  installation and OS grants. It cannot undo an action already delivered.
- `retryToolCalls: false` prevents nanobot's MCP wrapper from automatically
  replaying a failed action. It cannot provide exactly-once execution or prevent
  a model from requesting the action again. Reconnection is not rollback.
- Run **one desktop workflow at a time**. The official-driver path does not lock a whole
  observe–act workflow across chats, subagents, gateways, or other MCP clients.
  The macOS native host enforces one active task per gateway, not across gateways.
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
