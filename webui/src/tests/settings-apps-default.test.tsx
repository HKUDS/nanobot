import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NanobotClient } from "@/lib/nanobot-client";
import {
  installSettingsViewTestHooks,
  jsonResponse,
  renderSettingsView,
  settingsPayload,
} from "@/tests/settings-test-utils";

const app = {
  name: "example", display_name: "Example App", category: "productivity", description: "Example app",
  requires: "", source: "catalog", entry_point: "example", install_supported: true,
  installed: false, available: false, status: "not_installed", skill_installed: false,
};
const mcp = {
  name: "docs", display_name: "Docs MCP", category: "productivity", description: "Example MCP",
  docs_url: "", transport: "stdio", requires: "", note: "", install_supported: true,
  installed: true, configured: true, available: true, status: "configured", required_fields: [],
  connection_summary: "", source: "preset", runtime_status: "connected",
};
const plugin = { ...mcp, name: "plugin", display_name: "Example Plugin", source: "agent-plugin", enabled: true };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("Apps default filter", () => {
  installSettingsViewTestHooks();

  it("opens Apps when nothing is ready, including disconnected MCP and disabled plugins", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [app], installed_count: 0 });
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse({
        presets: [{ ...mcp, runtime_status: "disconnected" }, { ...plugin, enabled: false }], installed_count: 2,
      });
      return jsonResponse(settingsPayload());
    }));
    renderSettingsView({ initialSettings: settingsPayload() });

    expect(await screen.findByRole("heading", { name: "Example App" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "CLI Apps" })).toHaveAttribute("aria-pressed", "true");
  });

  it("preserves a manual choice while MCP loads, then defaults to the cached Ready items on re-entry", async () => {
    const client = { status: "open", onStatus: () => () => {} } as unknown as NanobotClient;
    const pending = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input) === "/api/settings/cli-apps") return Promise.resolve(jsonResponse({ apps: [app], installed_count: 0 }));
      if (String(input) === "/api/settings/mcp-presets") return pending.promise;
      return Promise.resolve(jsonResponse(settingsPayload()));
    }));
    renderSettingsView({ client, initialSettings: settingsPayload() });
    await act(async () => {});
    expect(screen.queryByRole("heading", { name: "Example App" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CLI Apps" }));
    await act(async () => { pending.resolve(jsonResponse({ presets: [mcp], installed_count: 1 })); });
    expect(screen.getByRole("button", { name: "CLI Apps" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "Example App" })).toBeInTheDocument();

    cleanup();
    renderSettingsView({ client, initialSettings: settingsPayload() });
    expect(screen.getByRole("button", { name: "Ready" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "Docs MCP" })).toBeInTheDocument();
  });
});
