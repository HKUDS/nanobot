import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RuntimeConfigSettings, useRuntimeConfigSettings } from "@/components/settings/system/RuntimeConfigSettings";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { SettingsPayload } from "@/lib/types";
import { installSettingsViewTestHooks, renderSettingsView, requestMutationMock, settingsPayload } from "@/tests/settings-test-utils";

function payload(): SettingsPayload {
  const base = settingsPayload();
  return { ...base, runtime_config: {
    "tools.exec.enable": true, "tools.exec.sandbox": "bwrap", "tools.exec.sandbox_launcher": "",
    "tools.exec.sandbox_ro_binds": [], "tools.exec.sandbox_rw_binds": [],
  }, advanced: { ...base.advanced, exec_sandbox_status: {
    state: "unavailable", reason: "launcher_missing", launcher: null, revision: "saved-one", supported_backend: "bwrap",
  } } };
}

const capability = ["webui.sandbox-settings.v1"];
function open() {
  renderSettingsView({ initialSection: "advanced", initialSettings: payload(), webuiCapabilities: capability });
  return within(screen.getByRole("region", { name: "Command sandbox" }));
}

describe("Saved sandbox settings", () => {
  installSettingsViewTestHooks();

  it("checks saved configuration explicitly without changing the isolation policy", async () => {
    const sandbox = open();
    expect(sandbox.getByText(/Bubblewrap \(bwrap\) was not found on the gateway/)).toBeVisible();
    expect(requestMutationMock).not.toHaveBeenCalled();
    requestMutationMock.mockResolvedValue({ sandbox: {
      ...payload().advanced.exec_sandbox_status, state: "passed", reason: "", launcher: "/usr/bin/bwrap",
    } });
    fireEvent.click(sandbox.getByRole("button", { name: "Check sandbox" }));
    expect(await sandbox.findByText("Basic check passed")).toBeVisible();
    expect(requestMutationMock).toHaveBeenCalledWith("settings.sandbox.check", {}, 20_000);
    expect(sandbox.getByText(/Restart the gateway/)).toBeVisible();
  });

  it.each([
    ["bwrap", "Bubblewrap (bwrap)"],
    ["seatbelt", "macOS Seatbelt (sandbox-exec)"],
  ] as const)("opens the gateway's %s path editor without editing or checking automatically", (backend, launcher) => {
    const settings = payload();
    settings.runtime_config!["tools.exec.sandbox"] = backend;
    settings.advanced.exec_sandbox_status!.supported_backend = backend;
    renderSettingsView({ initialSection: "advanced", initialSettings: settings, webuiCapabilities: capability,
      focusTarget: "sandbox-launcher" });
    const sandbox = within(screen.getByRole("region", { name: "Command sandbox" }));
    expect(sandbox.getByRole("button", { name: "Advanced options" })).toHaveAttribute("aria-expanded", "true");
    expect(sandbox.getByRole("textbox", { name: "Trusted launcher path" })).toHaveFocus();
    expect(sandbox.getByRole("textbox", { name: "Trusted launcher path" })).toHaveValue("");
    expect(sandbox.getByText(/Usually leave this blank for system lookup of/)).toHaveTextContent(launcher);
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("retains rejected path drafts and localizes errors", async () => {
    const sandbox = open();
    fireEvent.click(sandbox.getByRole("button", { name: "Advanced options" }));
    const input = sandbox.getByRole("textbox", { name: "Trusted launcher path" });
    fireEvent.change(input, { target: { value: "/vol1/@apphome/nanobot/bin/bwrap" } });
    expect(sandbox.getByRole("button", { name: "Check sandbox" })).toBeDisabled();
    requestMutationMock.mockRejectedValueOnce(new Error("sandbox_launcher_unprotected_installation"));
    fireEvent.click(sandbox.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sandbox.getAllByRole("alert")[0]).toHaveTextContent(/protected installation/));
    expect(input).toHaveValue("/vol1/@apphome/nanobot/bin/bwrap");
    expect(sandbox.queryByText("sandbox_launcher_unprotected_installation")).not.toBeInTheDocument();
  });

  it("requires confirmation before disabling and cancellation makes no mutation", async () => {
    const sandbox = open();
    fireEvent.click(sandbox.getByRole("combobox", { name: "Command sandbox" }));
    fireEvent.click(screen.getByRole("option", { name: "No isolation" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep isolation" }));
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(sandbox.getByRole("combobox", { name: "Command sandbox" }));
    fireEvent.click(screen.getByRole("option", { name: "No isolation" }));
    const saved = payload();
    saved.runtime_config!["tools.exec.sandbox"] = "";
    saved.advanced.exec_sandbox_status = { ...saved.advanced.exec_sandbox_status!, state: "off", reason: "", revision: "saved-off" };
    requestMutationMock.mockResolvedValue(saved);
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Turn off isolation" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.runtime_config.update", { values: { "tools.exec.sandbox": "" } }, 20_000));
  });

  it("clears a saved override explicitly to restore default lookup", async () => {
    const settings = payload();
    settings.runtime_config!["tools.exec.sandbox_launcher"] = "/opt/protected/bwrap";
    renderSettingsView({ initialSection: "advanced", initialSettings: settings, webuiCapabilities: capability });
    const sandbox = within(screen.getByRole("region", { name: "Command sandbox" }));
    fireEvent.click(sandbox.getByRole("button", { name: "Advanced options" }));
    fireEvent.change(sandbox.getByRole("textbox", { name: "Trusted launcher path" }), { target: { value: "" } });
    requestMutationMock.mockResolvedValue(payload());
    fireEvent.click(sandbox.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.runtime_config.update", { values: { "tools.exec.sandbox_launcher": "" } }, 20_000));
  });

  it("does not expose new controls without the optional host capability", () => {
    renderSettingsView({ initialSection: "advanced", initialSettings: payload() });
    expect(screen.queryByRole("button", { name: "Check sandbox" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Trusted launcher path" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Command sandbox" })).toBeVisible();
  });

  it("does not offer a probe or custom launcher on an unsupported host", () => {
    const settings = payload();
    settings.advanced.exec_sandbox_status = { ...settings.advanced.exec_sandbox_status!, state: "unsupported", reason: "platform_unsupported", supported_backend: null };
    renderSettingsView({ initialSection: "advanced", initialSettings: settings, webuiCapabilities: capability });
    expect(screen.getByText("Not supported")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Check sandbox" })).not.toBeInTheDocument();
  });

  it("does not tell an unsupported host with isolation off to choose a sandbox", () => {
    const settings = payload();
    settings.runtime_config!["tools.exec.sandbox"] = "";
    settings.advanced.exec_sandbox_status = { ...settings.advanced.exec_sandbox_status!, state: "off", reason: "", supported_backend: null };
    renderSettingsView({ initialSection: "advanced", initialSettings: settings, webuiCapabilities: capability });
    expect(screen.getByText("This isolation method is not supported on the gateway’s operating system.")).toBeVisible();
    expect(screen.queryByText(/Choose an isolation method/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check sandbox" })).not.toBeInTheDocument();
  });

  it("ignores a completed probe from the previously selected host", async () => {
    let finish!: (response: unknown) => void;
    const first = { requestMutation: vi.fn(() => new Promise((resolve) => { finish = resolve; })) } as unknown as NanobotClient;
    const next = { requestMutation: vi.fn() } as unknown as NanobotClient;
    const settings = payload();
    function Harness({ client }: { client: NanobotClient }) {
      const state = useRuntimeConfigSettings(settings, client, () => {});
      return <RuntimeConfigSettings page="advanced" settings={settings} state={state} client={client} sandboxSupported isRestarting={false} remoteBrowserAccess={false} />;
    }
    const { rerender } = render(<Harness client={first} />);
    fireEvent.click(screen.getByRole("button", { name: "Check sandbox" }));
    rerender(<Harness client={next} />);
    finish({ sandbox: { ...settings.advanced.exec_sandbox_status, state: "passed", reason: "" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Check sandbox" })).not.toBeDisabled());
    expect(screen.queryByText("Basic check passed")).not.toBeInTheDocument();
  });

  it("does not refocus the launcher when restart state changes", () => {
    const settings = payload();
    const client = { requestMutation: vi.fn() } as unknown as NanobotClient;
    function Harness({ restarting }: { restarting: boolean }) {
      const state = useRuntimeConfigSettings(settings, client, () => {});
      return <><button>Keep focus here</button><RuntimeConfigSettings page="advanced" settings={settings} state={state}
        client={client} sandboxSupported isRestarting={restarting} remoteBrowserAccess={false} focusTarget="sandbox-launcher" /></>;
    }
    const { rerender } = render(<Harness restarting={false} />);
    expect(screen.getByRole("textbox", { name: "Trusted launcher path" })).toHaveFocus();
    const other = screen.getByRole("button", { name: "Keep focus here" });
    other.focus();
    rerender(<Harness restarting />);
    expect(other).toHaveFocus();
    rerender(<Harness restarting={false} />);
    expect(other).toHaveFocus();
  });
});
