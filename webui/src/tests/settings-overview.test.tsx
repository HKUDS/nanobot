import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { HostNavigationContext } from "@/components/remote/HostSwitcher";
import { AboutSettings } from "@/components/settings/overview/OverviewSettings";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider } from "@/providers/ClientProvider";
import type { SettingsPayload } from "@/lib/types";
import { jsonResponse, settingsPayload, renderSettingsView, installSettingsViewTestHooks } from "@/tests/settings-test-utils";

  const thirdPartyBrandNotice =
    "Product names, logos, and brands are property of their respective owners. Use is for identification only and does not imply endorsement.";

describe("Settings overview and appearance", () => {
  installSettingsViewTestHooks();


  it("links the host's short commit beside its version", () => {
    const commit = "abcdef12".repeat(5);
    renderSettingsView({
      initialSection: "about",
      initialSettings: { ...settingsPayload(), version: { current: "0.3.5", commit } },
    });
    expect(screen.getByText("v0.3.5")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "abcdef1" });
    expect(link).toHaveAttribute("href", `https://github.com/HKUDS/nanobot/commit/${commit}`);
    expect(link).toHaveAttribute("title", commit);
    const reportUrl = new URL(screen.getByRole("link", { name: "Report an issue" }).getAttribute("href")!);
    expect(reportUrl.origin + reportUrl.pathname).toBe("https://github.com/HKUDS/nanobot/issues/new");
    expect(reportUrl.searchParams.get("template")).toBe("bug_report.yml");
    expect(reportUrl.searchParams.get("version")).toBe(`0.3.5 (commit ${commit})`);
  });

  it.each([undefined, null])("keeps About usable when the host reports no commit (%s)", (commit) => {
    renderSettingsView({
      initialSection: "about",
      initialSettings: { ...settingsPayload(), version: { current: "0.3.5", commit } },
    });
    expect(screen.getByText("v0.3.5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check for updates" })).toBeEnabled();
    expect(document.querySelector('a[href*="/commit/"]')).toBeNull();
    const reportUrl = new URL(screen.getByRole("link", { name: "Report an issue" }).getAttribute("href")!);
    expect(reportUrl.searchParams.get("version")).toBe("0.3.5");
    expect(reportUrl.searchParams.get("python_version")).toBeNull();
    expect(reportUrl.searchParams.get("os")).toBeNull();
    expect(reportUrl.searchParams.get("channel")).toBe("WebSocket");
    expect(reportUrl.searchParams.get("llm_provider")).toBe("openai");
    expect(reportUrl.searchParams.get("model")).toBe("openai/gpt-4o");
    expect(reportUrl.searchParams.get("additional")).toBeNull();
  });

  it("prefills the remote gateway environment separately from the browser", () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Browser on Windows");
    const payload: SettingsPayload = {
      ...settingsPayload(),
      environment: { python_version: "3.14.2", os: "Darwin", os_version: "24.4.0", architecture: "arm64" },
    };
    render(
      <ClientProvider client={new NanobotClient({ url: "ws://localhost:8765" })} token="tok">
        <HostNavigationContext.Provider value={{ kind: "embedded", name: "Remote", hostname: "private-host", open: vi.fn() }}>
          <AboutSettings settings={payload} />
        </HostNavigationContext.Provider>
      </ClientProvider>,
    );
    const url = new URL(screen.getByRole("link", { name: "Report an issue" }).getAttribute("href")!);
    expect(url.searchParams.get("python_version")).toBe("3.14.2");
    expect(url.searchParams.get("os")).toBe("macOS 24.4.0 (arm64)");
    expect(url.searchParams.get("channel")).toBe("WebSocket");
    expect(url.searchParams.get("browser")).toBe("Browser on Windows");
    expect(url.searchParams.get("connection")).toBe("Remote host");
    expect(url.searchParams.get("model")).toBe("openai/gpt-4o");
    expect(url.searchParams.get("llm_provider")).toBe("openai");
    expect(url.searchParams.get("additional")).toBeNull();
    expect(url.href).not.toContain(encodeURIComponent(payload.runtime.config_path));
    expect(url.href).not.toContain("private-host");
  });

  it("persists the file edit display local preference", async () => {
    renderSettingsView({
      initialSection: "appearance",
      initialSettings: settingsPayload(),
      showSidebar: true,
    });

    expect(screen.getByText("File edit display")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Diff" }));

    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem("nanobot-webui.settings-preferences") || "{}");
      expect(saved.fileEditDisplayMode).toBe("diff");
    });
  });

  it("shows the brand logo explanation in a tooltip when requested", async () => {
    renderSettingsView({
      initialSection: "appearance",
      initialSettings: settingsPayload(),
      showSidebar: true,
    });

    fireEvent.click(screen.getByRole("button", { name: "Brand logos" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(thirdPartyBrandNotice);
  });


  it("publishes the latest settings payload to the shell", async () => {
    const payload = settingsPayload();
    const onSettingsChange = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ onSettingsChange });

    await waitFor(() => expect(onSettingsChange).toHaveBeenCalledWith(payload));
  });

  it("does not keep Apps loading while an empty CLI catalog refresh is pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({
            apps: [],
            installed_count: 0,
            catalog_updated_at: null,
            catalog_refresh_pending: true,
          });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView();

    expect(await screen.findByText("No apps available.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Browse MCP tools" }));
    expect(await screen.findByText("Add MCP server")).toBeInTheDocument();
  });

  it("shows token activity on the overview", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      usage: {
        days: [
          {
            date: new Date().toISOString().slice(0, 10),
            input_tokens: 1200,
            output_tokens: 300,
            cache_read_tokens: 500,
            cache_write_tokens: 0,
            cache_read_observed_input_tokens: 1200,
            cache_write_observed_input_tokens: 1200,
            total_tokens: 1500,
            requests: 2,
          },
        ],
        total_tokens: 1500,
        total_tokens_30d: 1500,
        total_tokens_365d: 1500,
        peak_day_tokens: 1500,
        current_streak_days: 1,
        longest_streak_days: 1,
        active_days_30d: 1,
        requests_30d: 2,
        updated_at: "2026-06-03T00:00:00Z",
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "overview" });

    expect(await screen.findByLabelText("1,500 tokens")).toBeInTheDocument();
    expect(screen.getByText("Token usage")).toBeInTheDocument();
  });

  it("coalesces focus refreshes while usage is already loading", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      usage: {
        days: [],
        total_tokens: 0,
        total_tokens_30d: 0,
        total_tokens_365d: 0,
        peak_day_tokens: 0,
        current_streak_days: 0,
        longest_streak_days: 0,
        active_days_30d: 0,
        requests_30d: 0,
        updated_at: null,
      },
    };
    let resolveUsage!: (response: Response) => void;
    const pendingUsage = new Promise<Response>((resolve) => {
      resolveUsage = resolve;
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/usage") return pendingUsage;
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "overview", initialSettings: payload });

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => (
        String(input) === "/api/settings/usage"
      ))).toHaveLength(1);
    });
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("focus"));

    expect(fetchMock.mock.calls.filter(([input]) => (
      String(input) === "/api/settings/usage"
    ))).toHaveLength(1);
    await act(async () => {
      resolveUsage(jsonResponse(payload.usage));
      await pendingUsage;
    });
  });

  it("aligns token activity days with the configured timezone", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-02T18:00:00Z"));
    const basePayload = settingsPayload();
    const payload: SettingsPayload = {
      ...basePayload,
      agent: {
        ...basePayload.agent,
        timezone: "Asia/Shanghai",
      },
      usage: {
        days: [
          {
            date: "2026-06-03",
            input_tokens: 1200,
            output_tokens: 300,
            cache_read_tokens: 500,
            cache_write_tokens: 0,
            cache_read_observed_input_tokens: 1200,
            cache_write_observed_input_tokens: 1200,
            total_tokens: 1500,
            requests: 2,
          },
        ],
        total_tokens: 1500,
        total_tokens_30d: 1500,
        total_tokens_365d: 1500,
        peak_day_tokens: 1500,
        current_streak_days: 1,
        longest_streak_days: 1,
        active_days_30d: 1,
        requests_30d: 2,
        updated_at: "2026-06-03T00:00:00Z",
      },
    };
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({ initialSection: "overview", initialSettings: payload });

    expect(screen.getByLabelText(/2026-06-03: 1,500 tokens, 2 requests/)).toBeInTheDocument();
  });
});
