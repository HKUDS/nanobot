import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CuaDriverSetupPanel, CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_PERMISSIONS_CAPABILITY, CUA_RECONNECT_CAPABILITY } from "@/components/settings/system/CuaDriverSetupPanel";
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

  it("explains the upstream permission identity and keeps retries in recovery help", () => {
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
    expect(screen.getByText(/Turn on CuaDriver in System Settings/)).toBeVisible();
    expect(screen.getByText("Can’t find CuaDriver?")).toBeVisible();
    expect(screen.getByRole("button", { name: "Request system permissions" })).not.toBeVisible();
    fireEvent.click(screen.getByText("Can’t find CuaDriver?"));
    fireEvent.click(screen.getByRole("button", { name: "Request system permissions" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", {
      target: "permissions", consent: CUA_PERMISSIONS_CAPABILITY,
    });
    view.rerender(<CuaDriverSetupPanel preset={preset} {...props} capabilities={[CUA_CAPABILITY]} />);
    fireEvent.click(screen.getByRole("button", { name: "Allow viewing & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", { mode: "observe", consent: `${CUA_CAPABILITY}:observe` });
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
    expect(screen.getByText(/does not verify screen capture or model vision/)).toBeVisible();
    expect(screen.getByText(/Screen Recording: unknown/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable" }).closest("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    expect(action).toHaveBeenCalledWith("disable", "cua-driver", {});
  });

  it("requires fresh consent when changing enabled access, but not just to inspect the connection", () => {
    const action = vi.fn();
    render(<CuaDriverSetupPanel preset={{ ...cuaPreset, configured: true, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" } }}
      capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_PERMISSIONS_CAPABILITY]} actionKey={null} error={null} onAction={action} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check connection" }).closest("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));
    expect(action).toHaveBeenLastCalledWith("test", "cua-driver", {});
    fireEvent.click(screen.getByRole("button", { name: "Change access" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Change access" }));
    expect(screen.getByRole("radio", { name: "View only" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "View & control" }));
    fireEvent.click(screen.getByRole("button", { name: "Allow control & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", { mode: "control", consent: `${CUA_CAPABILITY}:control` });
    // Changing the tool allowlist does not start another OS permission request.
  });

  it("shows only unconfirmed grants and hides native actions on older hosts", () => {
    const action = vi.fn();
    const preset = { ...cuaPreset, configured: true, driver_setup: { ...cuaPreset.driver_setup!, installed: true, mode: "observe" as const } };
    const props = { actionKey: null, error: null, onAction: action, check: { connected: true, accessibility: true, screen_recording: false, capture_verified: false } };
    const view = render(<CuaDriverSetupPanel preset={preset} capabilities={[CUA_CAPABILITY, CUA_SETUP_CAPABILITY]} {...props} />);
    expect(screen.queryByRole("button", { name: "Open Accessibility settings" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Screen Recording settings" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", { target: "screen_recording" });
    fireEvent.click(screen.getByText("Can’t find CuaDriver?"));
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
    expect(screen.getByText("Access off")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Request system permissions" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Allow viewing & connect" }));
    expect(action).toHaveBeenLastCalledWith("enable", "cua-driver", {
      mode: "observe", consent: `${CUA_CAPABILITY}:observe`, permissions: CUA_PERMISSIONS_CAPABILITY,
    });
    const enabled = { ...installed, configured: true, driver_setup: { ...installed.driver_setup, mode: "observe" as const } };
    const pending = { connected: false, accessibility: null, screen_recording: null, capture_verified: false };
    view.rerender(<CuaDriverSetupPanel preset={enabled} capabilities={capabilities} {...props} check={pending} />);
    // A first-run permission gate can prevent the daemon from starting. Reconnect
    // support must not hide the settings and permission-request recovery path.
    expect(screen.getByRole("button", { name: "Open Accessibility settings" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open Screen Recording settings" })).toBeVisible();
    fireEvent.click(screen.getByText("Can’t find CuaDriver?"));
    fireEvent.click(screen.getByRole("button", { name: "Request system permissions" }));
    expect(action).toHaveBeenLastCalledWith("setup", "cua-driver", { target: "permissions", consent: CUA_PERMISSIONS_CAPABILITY });
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
    expect(screen.getByText(/Access is not limited to a single app/).closest("details")).toBeNull();
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
    expect(screen.getByRole("button", { name: "Check connection" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(back).toHaveBeenCalledOnce();
    expect(action).toHaveBeenCalledTimes(2); // Navigation never starts a task or captures a screen.
    fireEvent.click(screen.getByRole("button", { name: "Change access" }));
    expect(screen.getByRole("radio", { name: "View & control" })).toBeEnabled();
    view.rerender(<CuaDriverSetupPanel {...props} check={{ ...check, screen_recording: false }} />);
    expect(screen.queryByRole("button", { name: "Back to chat" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Screen Recording settings" })).toBeVisible();
    view.unmount();
  });

  it("offers an explicit reconnect only when the host supports it, not during background checking", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(action).toHaveBeenLastCalledWith("reconnect", "cua-driver", {});
    view.unmount();
  });
});
