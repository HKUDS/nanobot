import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CuaDriverSetupPanel, CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_PERMISSIONS_CAPABILITY, CUA_RECONNECT_CAPABILITY, CUA_NATIVE_CAPABILITY, CUA_UNINSTALL_CAPABILITY, CUA_UNINSTALL_RESET_CAPABILITY } from "@/components/settings/system/CuaDriverSetupPanel";
import i18n from "@/i18n";
import type { McpPresetInfo } from "@/lib/types";

export const cuaPreset: McpPresetInfo = {
  name: "cua-driver", display_name: "Cua Driver", category: "computer",
  description: "Computer use", docs_url: "https://cua.ai/docs/cua-driver/quickstart",
  transport: "stdio", requires: "", note: "", install_supported: true,
  installed: false, configured: false, available: false, status: "not_installed",
  required_fields: [], connection_summary: "", source: "preset",
  driver_setup: {
    schema: 1, version: "0.33.4", platform: "Darwin", machine: "test-gateway",
    supported: true, installed: false, managed: true, mode: "off",
  },
};

describe("managed Cua Driver setup", () => {
  beforeEach(async () => { await i18n.changeLanguage("en"); });
  afterEach(() => vi.useRealTimers());

  it("keeps uninstall explicit and leaves older hosts without a removal action", async () => {
    const onAction = vi.fn();
    const preset = { ...cuaPreset, driver_setup: { ...cuaPreset.driver_setup!, installed: true } };
    const props = { preset, actionKey: null, error: null, onAction };
    const view = render(<CuaDriverSetupPanel {...props} capabilities={[CUA_CAPABILITY, CUA_UNINSTALL_CAPABILITY]} />);
    fireEvent.click(screen.getByRole("button", { name: "Uninstall", exact: true }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Chats, other apps and macOS permissions are kept");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(onAction).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Uninstall", exact: true })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "Uninstall", exact: true }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Uninstall", exact: true }));
    expect(onAction).toHaveBeenCalledWith("uninstall", "cua-driver", { consent: CUA_UNINSTALL_CAPABILITY });
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={[CUA_CAPABILITY]} />);
    expect(screen.queryByRole("button", { name: "Uninstall", exact: true })).not.toBeInTheDocument();
  });

  it("uses the native permission identity and never presents stopped sharing as ready", () => {
    const preset = { ...cuaPreset, configured: true, runtime_status: "connected" as const,
      driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "control" as const, permission_app: "nanobot Computer Use" as const } };
    const capabilities = [CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_RECONNECT_CAPABILITY, CUA_NATIVE_CAPABILITY];
    const check = { connected: true, accessibility: true, screen_recording: true, capture_verified: false, sharing_paused: true };
    const onAction = vi.fn();
    render(<CuaDriverSetupPanel preset={preset} capabilities={capabilities} check={check}
      checkFeedback={{ state: "done", check, runtimeConnected: true, error: null }} active={false}
      actionKey={null} error={null} onAction={onAction} />);
    expect(screen.getByText("Sharing stopped")).toBeVisible();
    expect(screen.getByRole("status", { name: "Manual check result" })).toHaveTextContent("Sharing was stopped in macOS");
    expect(screen.queryByText("Connected")).not.toBeInTheDocument();
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Reconnect", exact: true }));
    expect(onAction).toHaveBeenCalledWith("reconnect", "cua-driver", {});
  });

  it("offers grant reset only for a capable native host and requires a fresh choice", () => {
    const onAction = vi.fn();
    const preset = { ...cuaPreset, driver_setup: { ...cuaPreset.driver_setup!, installed: true, permission_app: "nanobot Computer Use" as const } };
    const capabilities = [CUA_CAPABILITY, CUA_NATIVE_CAPABILITY, CUA_UNINSTALL_CAPABILITY, CUA_UNINSTALL_RESET_CAPABILITY];
    const props = { preset, actionKey: null, error: null, onAction };
    const view = render(<CuaDriverSetupPanel {...props} capabilities={capabilities} />);
    fireEvent.click(screen.getByRole("button", { name: "Uninstall", exact: true }));
    const checkbox = screen.getByRole("checkbox", { name: "Also revoke Mac permissions" });
    expect(checkbox).not.toBeChecked();
    expect(screen.getByRole("alertdialog")).toHaveTextContent("all nanobot instances on this Mac");
    fireEvent.click(checkbox);
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Uninstall", exact: true }));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Uninstall", exact: true }));
    expect(onAction).toHaveBeenLastCalledWith("uninstall", "cua-driver", { consent: CUA_UNINSTALL_RESET_CAPABILITY });
    // New clients do not send reset consent to a host that cannot implement it.
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={capabilities.filter(value => value !== CUA_UNINSTALL_RESET_CAPABILITY)} />);
    fireEvent.click(screen.getByRole("button", { name: "Uninstall", exact: true }));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Uninstall", exact: true }));
    expect(onAction).toHaveBeenLastCalledWith("uninstall", "cua-driver", { consent: CUA_UNINSTALL_CAPABILITY });
    view.rerender(<CuaDriverSetupPanel {...props} preset={{ ...preset, driver_setup: { ...preset.driver_setup, permission_app: "CuaDriver" } }} capabilities={capabilities} />);
    fireEvent.click(screen.getByRole("button", { name: "Uninstall", exact: true }));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("explains the upstream identity and recovers missing entries without another native request", () => {
    const action = vi.fn();
    const preset = { ...cuaPreset, driver_setup: { ...cuaPreset.driver_setup!, installed: true, permission_app: "CuaDriver" as const } };
    const capabilities = [CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_PERMISSIONS_CAPABILITY, CUA_RECONNECT_CAPABILITY];
    const props = { capabilities, actionKey: null, error: null, onAction: action };
    const view = render(<CuaDriverSetupPanel preset={preset} {...props} />);
    expect(screen.getByText(/CuaDriver, nanobot’s desktop engine/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Allow viewing & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", {
      mode: "observe", consent: `${CUA_CAPABILITY}:observe`, permissions: CUA_PERMISSIONS_CAPABILITY,
    });
    view.rerender(<CuaDriverSetupPanel preset={{ ...preset, configured: true, driver_setup: { ...preset.driver_setup, mode: "observe" } }} {...props}
      check={{ connected: true, accessibility: false, screen_recording: false, capture_verified: false }} />);
    expect(screen.getByText("Open Accessibility and turn on CuaDriver.")).toBeVisible();
    expect(screen.getByText("Can’t find CuaDriver?").closest("[inert]")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Connection details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request system permissions" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Can’t find the app or connect?" }));
    expect(screen.getByText("Can’t find CuaDriver?")).toBeVisible();
    expect(screen.getByText(/Permissions are checked automatically/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Request system permissions" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show in Finder" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", { target: "finder" });
    view.rerender(<CuaDriverSetupPanel preset={preset} {...props} capabilities={[CUA_CAPABILITY]} />);
    fireEvent.click(screen.getByRole("button", { name: "Allow viewing & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", { mode: "observe", consent: `${CUA_CAPABILITY}:observe` });
  });

  it("guides one permission at a time without treating step selection or opening settings as a grant", () => {
    const action = vi.fn();
    const preset = { ...cuaPreset, configured: true, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const props = { preset, capabilities: [CUA_CAPABILITY, CUA_SETUP_CAPABILITY], actionKey: null, error: null, onAction: action };
    const check = { connected: false, accessibility: null, screen_recording: null, capture_verified: false };
    const view = render(<CuaDriverSetupPanel {...props} check={check} />);
    expect(screen.getAllByRole("button", { name: /Open .* settings/ })).toHaveLength(1);
    expect(screen.getByText(/newer macOS calls this Device Control & Data Access/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open Accessibility settings" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", { target: "accessibility" });
    expect(screen.queryByText("granted")).not.toBeInTheDocument();
    // Unknown status must not trap a user who has completed the first grant
    // while the daemon is unreachable. Choosing the next guide never opens it.
    fireEvent.click(screen.getByRole("button", { name: /Screen Recording unknown/ }));
    expect(screen.getByText(/Look for Screen & System Audio Recording/)).toBeVisible();
    expect(action).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Open Screen Recording settings" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", { target: "screen_recording" });
    expect(screen.queryByText("granted")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Accessibility unknown/ }));
    view.rerender(<CuaDriverSetupPanel {...props} check={{ ...check, accessibility: true }} />);
    expect(screen.getByText("granted")).toBeVisible();
    expect(screen.getByRole("button", { name: /Accessibility granted/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open Screen Recording settings" })).toBeVisible();
    expect(action).toHaveBeenCalledTimes(2); // Read results cannot open a second pane.
  });

  it("asks separately for install and desktop access, defaulting to observation", () => {
    const action = vi.fn();
    const props = { capabilities: [CUA_CAPABILITY], actionKey: null, error: null, onAction: action };
    const view = render(<CuaDriverSetupPanel preset={cuaPreset} {...props} />);
    const dialog = view.container;
    expect(within(dialog).getByText(/test-gateway/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Download & install" }));
    expect(action).toHaveBeenCalledWith("install", "cua-driver", { consent: `${CUA_CAPABILITY}:install` });
    expect(action).toHaveBeenCalledTimes(1);
    view.rerender(<CuaDriverSetupPanel preset={{ ...cuaPreset, driver_setup: { ...cuaPreset.driver_setup!, installed: true } }} {...props} />);
    expect(within(dialog).getByText(/Screenshots may be sent/)).toBeVisible();
    expect(within(dialog).getByRole("radio", { name: "View only" })).toBeChecked();
    expect(within(dialog).getByText(/test-gateway/).closest("details")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Allow viewing & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", { mode: "observe", consent: `${CUA_CAPABILITY}:observe` });
    fireEvent.click(within(dialog).getByRole("radio", { name: "View & control" }));
    expect(action).toHaveBeenCalledTimes(2); // A mode selection alone never enables access.
  });

  it.each([
    [undefined, cuaPreset.driver_setup],
    [[], cuaPreset.driver_setup],
    [[CUA_CAPABILITY], { ...cuaPreset.driver_setup, schema: 2 }],
    [[CUA_CAPABILITY], { ...cuaPreset.driver_setup, installed: "yes" }],
    // A gateway still running the deferred native-host experiment must not be mislabeled.
    [[CUA_CAPABILITY], { ...cuaPreset.driver_setup, permission_app: "nanobot Computer Use" }],
    [[CUA_CAPABILITY], null],
  ])("does not offer mutations for missing or unrecognized optional support (%j)", (capabilities, setup) => {
    const view = render(<CuaDriverSetupPanel preset={{ ...cuaPreset, driver_setup: setup as McpPresetInfo["driver_setup"] }}
      capabilities={capabilities} actionKey={null} error={null} onAction={vi.fn()} />);
    const dialog = view.container;
    expect(within(dialog).getByText(/not confirmed/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Download & install" })).not.toBeInTheDocument();
  });

  it("accepts unrelated future capabilities without relaxing desktop consent", () => {
    render(<CuaDriverSetupPanel preset={cuaPreset} capabilities={[CUA_CAPABILITY, "future.v9"]}
      actionKey={null} error={null} onAction={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Download & install" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Allow viewing & connect" })).not.toBeInTheDocument();
  });

  it("does not label a connection check as screen-capture or model acceptance", () => {
    const action = vi.fn();
    render(<CuaDriverSetupPanel preset={{ ...cuaPreset, configured: true, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" } }}
      capabilities={[CUA_CAPABILITY]} actionKey={null} error={null} onAction={action}
      check={{ connected: true, accessibility: true, screen_recording: null, capture_verified: false }} />);
    expect(screen.getByText(/does not verify screen capture or model vision/).closest("[inert]")).not.toBeNull();
    fireEvent.click(screen.getByText("Connection details"));
    expect(screen.getByText(/does not verify screen capture or model vision/)).toBeVisible();
    expect(screen.getByText(/Screen Recording: unknown/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable" }).closest("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    expect(action).toHaveBeenCalledWith("disable", "cua-driver", {});
  });

  it("distinguishes missing permissions, disconnected tools and incomplete check responses", () => {
    const preset = { ...cuaPreset, configured: true, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const props = { preset, capabilities: [CUA_CAPABILITY], actionKey: null, error: null, onAction: vi.fn() };
    const check = { connected: true, accessibility: true, screen_recording: false, capture_verified: false };
    const view = render(<CuaDriverSetupPanel {...props} checkFeedback={{ state: "done", check, runtimeConnected: true, error: null }} />);
    expect(screen.getByRole("status", { name: "Manual check result" })).toHaveTextContent("System permissions are still missing.");
    view.rerender(<CuaDriverSetupPanel {...props} checkFeedback={{ state: "done", check: { ...check, screen_recording: true }, runtimeConnected: false, error: null }} />);
    expect(screen.getByRole("status", { name: "Manual check result" })).toHaveTextContent("The connection is not ready.");
    view.rerender(<CuaDriverSetupPanel {...props} checkFeedback={{ state: "done", runtimeConnected: true, error: null }} />);
    expect(screen.getByRole("status", { name: "Manual check result" })).toHaveTextContent("The gateway did not return a complete check result.");
  });

  it("requires fresh consent when changing enabled access, but not just to inspect the connection", () => {
    const action = vi.fn();
    const preset = { ...cuaPreset, configured: true, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const capabilities = [CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_PERMISSIONS_CAPABILITY];
    const view = render(<CuaDriverSetupPanel preset={preset}
      capabilities={capabilities} actionKey={null} error={null} onAction={action} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check connection" }).closest("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));
    expect(action).toHaveBeenLastCalledWith("test", "cua-driver", {});
    fireEvent.click(screen.getByRole("button", { name: "Change access" }));
    expect(screen.getByRole("radio", { name: "View only" })).toHaveFocus();
    expect(screen.getByText(/Access is not limited to a single app/)).toBeVisible();
    expect(screen.getByText(/Screenshots may be sent/)).toBeVisible();
    fireEvent.click(screen.getByRole("radio", { name: "View & control" }));
    expect(action).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: "View only" }));
    fireEvent.click(screen.getByRole("radio", { name: "View & control" }));
    expect(action).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Current access: View only")).toBeVisible();
    expect(screen.getByText("Access changes take effect after you confirm.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Allow control & connect" })).not.toBeInTheDocument();
    expect(action).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Change access" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Change access" }));
    expect(screen.getByRole("radio", { name: "View only" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "View & control" }));
    fireEvent.click(screen.getByRole("button", { name: "Allow control & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", { mode: "control", consent: `${CUA_CAPABILITY}:control` });
    // Changing the tool allowlist does not start another OS permission request.
    view.rerender(<CuaDriverSetupPanel preset={preset}
      capabilities={capabilities} actionKey={null} error="Access change failed" onAction={action} />);
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Access change failed");
    expect(screen.getByText("Current access: View only")).toBeVisible();
    expect(screen.getByRole("radio", { name: "View & control" })).toBeChecked();
  });

  it("offers native actions only for unconfirmed grants on supported hosts", () => {
    const action = vi.fn();
    const preset = { ...cuaPreset, configured: true, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const props = { actionKey: null, error: null, onAction: action, check: { connected: true, accessibility: true, screen_recording: false, capture_verified: false } };
    const view = render(<CuaDriverSetupPanel preset={preset} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY]} {...props} />);
    expect(screen.queryByRole("button", { name: "Open Accessibility settings" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Screen Recording settings" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", { target: "screen_recording" });
    fireEvent.click(screen.getByRole("button", { name: "Can’t find the app or connect?" }));
    fireEvent.click(screen.getByRole("button", { name: "Show in Finder" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", { target: "finder" });
    view.rerender(<CuaDriverSetupPanel preset={preset} capabilities={[CUA_CAPABILITY]} {...props} />);
    expect(screen.queryByRole("button", { name: /Open .* settings/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check connection" })).toBeInTheDocument();
  });

  it("opts into native requests only on supported Macs and only after a user action", () => {
    const action = vi.fn();
    const capabilities = [CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_PERMISSIONS_CAPABILITY, CUA_RECONNECT_CAPABILITY];
    const installed = { ...cuaPreset, driver_setup: { ...cuaPreset.driver_setup!, installed: true } };
    const props = { actionKey: null, error: null, onAction: action };
    const view = render(<CuaDriverSetupPanel preset={installed} capabilities={capabilities} {...props} />);
    expect(action).not.toHaveBeenCalled();
    expect(screen.getByText("Installed · access off")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Request system permissions" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Allow viewing & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", {
      mode: "observe", consent: `${CUA_CAPABILITY}:observe`, permissions: CUA_PERMISSIONS_CAPABILITY,
    });
    const enabled = { ...installed, configured: true, driver_setup: { ...installed.driver_setup, mode: "observe" as const } };
    const pending = { connected: false, accessibility: null, screen_recording: null, capture_verified: false };
    view.rerender(<CuaDriverSetupPanel preset={enabled} capabilities={capabilities} {...props} check={pending} />);
    // A first-run permission gate can prevent the daemon from starting. Reconnect
    // support must not hide either settings step or missing-entry recovery.
    expect(screen.getByRole("button", { name: "Open Accessibility settings" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Screen Recording unknown" }));
    expect(screen.getByRole("button", { name: "Open Screen Recording settings" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Can’t find the app or connect?" }));
    fireEvent.click(screen.getByRole("button", { name: "Show in Finder" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", { target: "finder" });
    fireEvent.click(screen.getByRole("button", { name: "Accessibility unknown" }));
    view.rerender(<CuaDriverSetupPanel preset={enabled} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY]} {...props} check={pending} />);
    expect(screen.queryByRole("button", { name: "Request system permissions" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Accessibility settings" })).toBeInTheDocument();
    view.rerender(<CuaDriverSetupPanel preset={{ ...installed, driver_setup: { ...installed.driver_setup, platform: "Windows" } }} capabilities={capabilities} {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Allow viewing & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", { mode: "observe", consent: `${CUA_CAPABILITY}:observe` });
  });

  it("serially checks after enable finishes, stops on close and never auto-enables", async () => {
    vi.useFakeTimers();
    let finish: () => void = () => {};
    const action = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    const preset = { ...cuaPreset, configured: true, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const props = { capabilities: [CUA_CAPABILITY, CUA_SETUP_CAPABILITY], error: null, onAction: action };
    const view = render(<CuaDriverSetupPanel preset={preset} actionKey="enable:cua-driver" {...props} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(action).not.toHaveBeenCalled();
    view.rerender(<CuaDriverSetupPanel preset={preset} actionKey={null} {...props} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(action).toHaveBeenCalledTimes(1);
    expect(action).toHaveBeenCalledWith("test", "cua-driver", { quiet: "true" });
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(action).toHaveBeenCalledTimes(1);
    view.rerender(<CuaDriverSetupPanel preset={preset} actionKey={null} active={false} {...props} />);
    await act(async () => { finish(); await vi.advanceTimersByTimeAsync(10000); });
    fireEvent.focus(window);
    expect(action).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("does not flash missing permissions before the first check and keeps disable visible", () => {
    const action = vi.fn();
    const preset = { ...cuaPreset, configured: true, runtime_status: "connected" as const,
      driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "control" as const } };
    render(<CuaDriverSetupPanel preset={preset} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY]}
      actionKey={null} error={null} onAction={action} />);
    expect(screen.getByText("Checking system permissions…")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Finish Mac setup" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open .* settings/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change access" })).not.toHaveFocus();
    const disable = screen.getByRole("button", { name: "Disable" });
    expect(disable.closest("details")).toBeNull();
    fireEvent.click(disable);
    expect(action).toHaveBeenLastCalledWith("disable", "cua-driver", {});
  });

  it("stops the guide after verified connection and keeps granted access without re-consent", async () => {
    vi.useFakeTimers();
    const action = vi.fn(async () => {});
    const preset = { ...cuaPreset, configured: true, runtime_status: "connected" as const, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const view = render(<CuaDriverSetupPanel preset={preset} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY]} actionKey={null} error={null} onAction={action}
      check={{ connected: true, accessibility: true, screen_recording: true, capture_verified: false }} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(action).toHaveBeenCalledTimes(1); // Fresh check even when opening cached setup.
    expect(screen.getByText("Connected")).toBeVisible();
    expect(screen.getByText("Current access: View only")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Open .* settings/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Allow viewing & connect" })).not.toBeInTheDocument();
    view.unmount();
  });

  it("keeps checking when reopening a previously connected driver finds a revoked grant", async () => {
    vi.useFakeTimers();
    const action = vi.fn(async () => {});
    const preset = { ...cuaPreset, configured: true, runtime_status: "connected" as const, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const props = { preset, capabilities: [CUA_CAPABILITY, CUA_SETUP_CAPABILITY], actionKey: null, error: null, onAction: action };
    const check = { connected: true, accessibility: true, screen_recording: true, capture_verified: false };
    const view = render(<CuaDriverSetupPanel {...props} check={check} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    view.rerender(<CuaDriverSetupPanel {...props} check={{ ...check, screen_recording: false }} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(action).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Open Screen Recording settings" })).toBeInTheDocument();
    view.unmount();
  });

  it("refreshes ready grants on return and keeps disable and access editing usable during a check", async () => {
    vi.useFakeTimers();
    const action = vi.fn(async () => {});
    const back = vi.fn();
    const preset = { ...cuaPreset, configured: true, runtime_status: "connected" as const,
      driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const props = { preset, capabilities: [CUA_CAPABILITY, CUA_SETUP_CAPABILITY], actionKey: null, error: null, onAction: action, onBackToChat: back };
    const check = { connected: true, accessibility: true, screen_recording: true, capture_verified: false };
    const view = render(<CuaDriverSetupPanel {...props} check={check} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(action).toHaveBeenCalledTimes(1);
    fireEvent.focus(window);
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    expect(action).toHaveBeenCalledTimes(2);
    view.rerender(<CuaDriverSetupPanel {...props} actionKey="test:cua-driver" check={check} />);
    expect(screen.getByRole("button", { name: "Disable" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Check connection" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connection details" }));
    expect(screen.getByRole("button", { name: "Checking…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(back).toHaveBeenCalledOnce();
    expect(action).toHaveBeenCalledTimes(2); // Navigation never starts a task or captures a screen.
    fireEvent.click(screen.getByRole("button", { name: "Change access" }));
    expect(screen.getByRole("radio", { name: "View & control" })).toBeEnabled();
    view.rerender(<CuaDriverSetupPanel {...props} check={{ ...check, screen_recording: false }} />);
    expect(screen.queryByRole("button", { name: "Back to chat" })).not.toBeInTheDocument();
    // Background checks must not interrupt an unconfirmed access edit.
    expect(screen.getByRole("radio", { name: "View & control" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Open Screen Recording settings" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Change access" })).toHaveFocus();
    view.unmount();
  });

  it("can recover after macOS relaunch loses the private connection without assuming grants", () => {
    const action = vi.fn();
    const preset = { ...cuaPreset, configured: true, runtime_status: "failed" as const,
      driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "control" as const } };
    const props = { preset, actionKey: null, error: null, onAction: action, active: false,
      check: { connected: false, accessibility: null, screen_recording: null, capture_verified: false } };
    const capabilities = [CUA_CAPABILITY, CUA_SETUP_CAPABILITY];
    const view = render(<CuaDriverSetupPanel {...props} capabilities={capabilities} />);
    fireEvent.click(screen.getByRole("button", { name: "Can’t find the app or connect?" }));
    expect(screen.queryByRole("button", { name: "Reconnect" })).not.toBeInTheDocument();
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={[...capabilities, CUA_RECONNECT_CAPABILITY]} />);
    expect(screen.getByText("Already allowed both permissions?")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Permissions pending");
    expect(action).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(action).toHaveBeenCalledTimes(1);
    expect(action).toHaveBeenCalledWith("reconnect", "cua-driver", {});
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={[...capabilities, CUA_RECONNECT_CAPABILITY]} actionKey="reconnect:cua-driver" />);
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeDisabled();
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={[...capabilities, CUA_RECONNECT_CAPABILITY]}
      preset={{ ...preset, runtime_status: "connected" }}
      check={{ ...props.check, connected: true, accessibility: true, screen_recording: true }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Connected");
    expect(screen.queryByRole("heading", { name: "Finish Mac setup" })).not.toBeInTheDocument();
  });

  it("prioritizes permission setup before a primary reconnect action", async () => {
    vi.useFakeTimers();
    const action = vi.fn<Parameters<typeof CuaDriverSetupPanel>[0]["onAction"]>(async () => {});
    const preset = { ...cuaPreset, configured: true, runtime_status: "connected" as const,
      driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const props = { preset, actionKey: null, error: null, onAction: action,
      check: { connected: false, accessibility: null, screen_recording: null, capture_verified: false } };
    const view = render(<CuaDriverSetupPanel {...props} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY]} />);
    expect(screen.queryByRole("button", { name: "Reconnect" })).not.toBeInTheDocument();
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_RECONNECT_CAPABILITY]} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(action.mock.calls.every(([kind]) => kind === "test")).toBe(true);
    expect(screen.getByRole("heading", { name: "Finish Mac setup" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Permissions pending");
    expect(screen.queryByRole("button", { name: "Reconnect" })).not.toBeInTheDocument();
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_RECONNECT_CAPABILITY]}
      check={{ ...props.check, accessibility: true, screen_recording: false }} />);
    expect(screen.getByText("granted")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open Accessibility settings" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Screen Recording settings" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reconnect" })).not.toBeInTheDocument();
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY]}
      check={{ ...props.check, accessibility: true, screen_recording: true }} />);
    expect(screen.queryByRole("button", { name: "Reconnect" })).not.toBeInTheDocument();
    view.rerender(<CuaDriverSetupPanel {...props} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_RECONNECT_CAPABILITY]}
      check={{ ...props.check, accessibility: true, screen_recording: true }} />);
    expect(screen.queryByRole("heading", { name: "Finish Mac setup" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check connection" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connection details" }));
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));
    expect(action).toHaveBeenLastCalledWith("test", "cua-driver", {});
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(action).toHaveBeenLastCalledWith("reconnect", "cua-driver", {});
    view.unmount();
  });
});
