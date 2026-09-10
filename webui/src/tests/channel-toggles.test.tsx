import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NanobotFeatureInfo, NanobotFeaturesPayload } from "@/lib/types";
import {
  installSettingsViewTestHooks,
  jsonResponse,
  renderSettingsView,
  requestMutationMock,
  settingsPayload,
} from "@/tests/settings-test-utils";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function feature(enabled: boolean, instances = false): NanobotFeatureInfo {
  return {
    name: "test-chat",
    display_name: "Test Chat",
    type: "channel",
    installed: true,
    configured: true,
    enabled,
    running: enabled,
    runtime_status: enabled ? "running" : "stopped",
    ready: true,
    status: enabled ? "enabled" : "not_enabled",
    install_supported: true,
    requires_restart: false,
    setup: { fields: [], requirements: [] },
    ...(instances ? { instances: [{
      id: "first",
      name: "First",
      configured: true,
      enabled,
      runtime_status: enabled ? "running" : "stopped",
      config_values: {},
      configured_fields: [],
    }, {
      id: "second",
      name: "Second",
      configured: true,
      enabled: false,
      runtime_status: "stopped",
      config_values: {},
      configured_fields: [],
    }] } : {}),
  };
}

function payload(channel: NanobotFeatureInfo): NanobotFeaturesPayload {
  return { features: [channel], enabled_count: Number(channel.enabled) };
}

function renderChannel(channel: NanobotFeatureInfo) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/settings") return jsonResponse(settingsPayload());
    if (url === "/api/settings/nanobot-features") return jsonResponse(payload(channel));
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  }));
  renderSettingsView({ initialSection: "channels" });
}

describe("optimistic channel switches", () => {
  installSettingsViewTestHooks();
  afterEach(() => vi.restoreAllMocks());

  for (const surface of ["catalog", "setup", "instance"] as const) {
    it.each([
      [false, true],
      [true, true],
      [false, false],
      [true, false],
    ])(`${surface}: updates immediately from %s and settles with success=%s`, async (initial, succeeds) => {
      const mutation = deferred<unknown>();
      const validation = deferred<unknown>();
      requestMutationMock.mockImplementation((action: string) =>
        action === "settings.channel.validate" ? validation.promise : mutation.promise);
      vi.spyOn(console, "error").mockImplementation(() => {});
      renderChannel(feature(initial, surface === "instance"));

      const catalogSwitch = await screen.findByRole("switch", { name: "Test Chat channel" });
      if (surface !== "catalog") {
        fireEvent.click(screen.getByRole("button", { name: "View Test Chat settings" }));
      }
      const toggle = surface === "catalog"
        ? catalogSwitch
        : surface === "instance"
          ? await screen.findByRole("switch", { name: "First instance" })
          : within(await screen.findByRole("dialog")).getByRole("switch");

      if (!initial && succeeds) {
        toggle.focus();
        await userEvent.setup().keyboard("[Space]");
      } else {
        fireEvent.click(toggle);
      }
      expect(toggle).toHaveAttribute("aria-checked", String(!initial));
      expect(toggle).toBeDisabled();
      fireEvent.click(toggle);
      expect(requestMutationMock).toHaveBeenCalledTimes(1);
      if (surface === "instance") {
        const other = screen.getByRole("switch", { name: "Second instance" });
        expect(other).toHaveAttribute("aria-checked", "false");
        expect(other).toBeDisabled();
        fireEvent.click(other);
        expect(requestMutationMock).toHaveBeenCalledTimes(1);
      }

      await act(async () => { fireEvent(window, new Event("focus")); });
      expect(toggle).toHaveAttribute("aria-checked", String(!initial));
      expect(toggle).toBeDisabled();

      if (surface === "setup" && !initial) {
        await act(async () => validation.resolve({
          name: "test-chat", status: "connected", can_enable: true,
          checks: [], missing_fields: [], requires_restart: false,
        }));
        expect(requestMutationMock).toHaveBeenCalledTimes(2);
        expect(toggle).toHaveAttribute("aria-checked", "true");
        expect(toggle).toBeDisabled();
      }
      const result = payload(feature(!initial, surface === "instance"));
      await act(async () => {
        if (succeeds) {
          mutation.resolve(surface === "setup" && !initial ? { nanobot_features: result } : result);
        } else {
          mutation.reject(new Error("Channel update failed"));
        }
      });
      await waitFor(() => expect(toggle).toBeEnabled());
      expect(toggle).toHaveAttribute("aria-checked", String(succeeds ? !initial : initial));
      if (!succeeds) expect(screen.getByText("Channel update failed")).toBeVisible();
      if (surface === "instance") {
        expect(screen.getByRole("switch", { name: "Second instance" })).toBeEnabled();
      }
    });
  }

  it("rolls back when server validation rejects activation without saving", async () => {
    const validation = deferred<unknown>();
    requestMutationMock.mockReturnValue(validation.promise);
    renderChannel(feature(false));
    fireEvent.click(await screen.findByRole("button", { name: "View Test Chat settings" }));
    const toggle = within(await screen.findByRole("dialog")).getByRole("switch");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");

    await act(async () => validation.resolve({
      name: "test-chat", status: "invalid", can_enable: false, message: "Credentials rejected",
      checks: [], missing_fields: [], requires_restart: false,
    }));
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toBeEnabled();
    expect(screen.getByText("Credentials rejected")).toBeVisible();
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(requestMutationMock.mock.calls[0][0]).toBe("settings.channel.validate");
  });

  it("does not show installation-only requests as optimistic activation", async () => {
    const installation = deferred<unknown>();
    requestMutationMock.mockReturnValue(installation.promise);
    const channel = { ...feature(false), installed: false, requires_dependencies: true };
    renderChannel(channel);
    fireEvent.click(await screen.findByRole("button", { name: "Install Test Chat" }));
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.feature.enable", { name: "test-chat", install_only: true }, 150_000,
    );

    channel.installed = true;
    await act(async () => { fireEvent(window, new Event("focus")); });
    const toggle = await screen.findByRole("switch", { name: "Test Chat channel" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toBeDisabled();
    await act(async () => installation.resolve(payload(channel)));
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toBeEnabled();
  });
});
