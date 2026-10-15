import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CliAppInfo, McpPresetInfo, NanobotFeatureInfo } from "@/lib/types";
import {
  installSettingsViewTestHooks,
  jsonResponse,
  renderSettingsView,
  settingsPayload,
} from "@/tests/settings-test-utils";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

const app: CliAppInfo = {
  name: "anygen", display_name: "AnyGen", category: "generation",
  description: "Generate documents.", requires: "ANYGEN_API_KEY", source: "harness",
  entry_point: "cli-anything-anygen", install_supported: true, installed: true,
  available: true, status: "installed", skill_installed: true,
};
const plugin: McpPresetInfo = {
  name: "plugin-computer-use", display_name: "Computer Use", category: "Plugin",
  description: "Control the desktop.", requires: "accessibility", transport: "stdio",
  install_supported: false, installed: true, configured: true, enabled: false,
  available: false, status: "disabled", required_fields: [], source: "agent-plugin",
  docs_url: "", note: "", connection_summary: "",
};
const channel: NanobotFeatureInfo = {
  name: "discord", display_name: "Discord", type: "channel", installed: true,
  configured: false, enabled: false, ready: false, status: "not_enabled",
  install_supported: true, requires_restart: false,
};

describe("catalog loading", () => {
  installSettingsViewTestHooks();

  it("keeps loaded Apps rows visible while waiting for Agent Plugins", async () => {
    const cli = deferred<Response>();
    const mcp = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings/cli-apps") return cli.promise;
      if (url === "/api/settings/mcp-presets") return mcp.promise;
      return Promise.resolve(jsonResponse(settingsPayload()));
    }));
    renderSettingsView({ initialSettings: settingsPayload() });
    expect(screen.getByRole("status", { name: "Loading apps…" })).toHaveAttribute("aria-busy", "true");

    await act(async () => { cli.resolve(jsonResponse({ apps: [app], installed_count: 1 })); });
    expect(screen.getByRole("heading", { name: "AnyGen" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading apps…" })).toBeInTheDocument();
    await act(async () => { mcp.resolve(jsonResponse({ presets: [plugin], installed_count: 1 })); });
    expect(screen.getByRole("heading", { name: "Computer Use" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading apps…" })).not.toBeInTheDocument();
  });

  it("finishes an empty MCP category independently but waits for Apps when searching", async () => {
    const cli = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings/cli-apps") return cli.promise;
      if (url === "/api/settings/mcp-presets") {
        return Promise.resolve(jsonResponse({ presets: [], installed_count: 0 }));
      }
      return Promise.resolve(jsonResponse(settingsPayload()));
    }));
    renderSettingsView({ initialSettings: settingsPayload() });
    await act(async () => {});
    expect(screen.getByRole("status", { name: "Loading apps…" })).toBeInTheDocument();
    expect(screen.queryByText("No apps available.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "MCP" }));
    expect(screen.getByText("No MCP tools available.")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading apps…" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Search tools"), { target: { value: "AnyGen" } });
    expect(screen.getByRole("status", { name: "Loading apps…" })).toBeInTheDocument();
    expect(screen.queryByText("No tools match your search.")).not.toBeInTheDocument();
    await act(async () => { cli.resolve(jsonResponse({ apps: [app], installed_count: 1 })); });
    expect(screen.getByRole("heading", { name: "AnyGen" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading apps…" })).not.toBeInTheDocument();
  });

  it.each(["apps", "channels"] as const)("reports a failed %s read without claiming an empty catalog", async (section) => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      throw new Error("Catalog offline");
    }));
    renderSettingsView({ initialSection: section, initialSettings: settingsPayload() });
    expect(await screen.findByText("Catalog offline")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: /Loading (apps|channels)/ })).not.toBeInTheDocument();
    expect(screen.queryByText("No apps available.")).not.toBeInTheDocument();
    expect(screen.queryByText("No channels match this filter.")).not.toBeInTheDocument();
  });

  it("shows Channels placeholders until the first response and preserves rows on a focus refresh", async () => {
    const initial = deferred<Response>();
    const refresh = deferred<Response>();
    const fetchFeatures = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValue(refresh.promise);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (
      String(input) === "/api/settings/nanobot-features"
        ? fetchFeatures() : Promise.resolve(jsonResponse(settingsPayload()))
    )));
    renderSettingsView({ initialSection: "channels", initialSettings: settingsPayload() });
    expect(screen.getByRole("status", { name: "Loading channels…" })).toHaveAttribute("aria-busy", "true");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search channels" }), {
      target: { value: "discord" },
    });
    await act(async () => { initial.resolve(jsonResponse({ features: [channel], enabled_count: 0 })); });
    expect(screen.getByRole("button", { name: "View Discord settings" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading channels…" })).not.toBeInTheDocument();

    act(() => { window.dispatchEvent(new Event("focus")); });
    expect(fetchFeatures).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "View Discord settings" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading channels…" })).not.toBeInTheDocument();
    await act(async () => { refresh.resolve(jsonResponse({ features: [], enabled_count: 0 })); });
    expect(screen.getByText("No channels match this filter.")).toBeInTheDocument();
  });
});
