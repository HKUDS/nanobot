import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SettingsPayload } from "@/lib/types";
import { jsonResponse, settingsPayload, renderSettingsView, installSettingsViewTestHooks } from "@/tests/settings-test-utils";

  const thirdPartyBrandNotice =
    "Product names, logos, and brands are property of their respective owners. Use is for identification only and does not imply endorsement.";

describe("Settings overview and appearance", () => {
  installSettingsViewTestHooks();


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

  it("shows the third-party brand notice only with the brand logo preference", () => {
    renderSettingsView({
      initialSection: "appearance",
      initialSettings: settingsPayload(),
      showSidebar: true,
    });

    const brandLogosTitle = screen.getByText("Brand logos");
    const brandLogosRow = brandLogosTitle.parentElement?.parentElement;

    expect(brandLogosRow).not.toBeNull();
    expect(
      within(brandLogosRow as HTMLElement).getByText(thirdPartyBrandNotice),
    ).toBeInTheDocument();
    expect(screen.getAllByText(thirdPartyBrandNotice)).toHaveLength(1);
  });

  it.each(["apps", "channels"] as const)(
    "does not repeat the third-party brand notice in %s",
    (initialSection) => {
      renderSettingsView({ initialSection, initialSettings: settingsPayload() });

      expect(screen.queryByText(thirdPartyBrandNotice)).not.toBeInTheDocument();
    },
  );

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
    expect(screen.queryByText("Loading Apps...")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Browse MCP tools" }));
    expect(await screen.findByText("Add MCP server")).toBeInTheDocument();
  });

  it("shows token activity on the overview", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
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

    expect(await screen.findByLabelText("Token activity")).toBeInTheDocument();
    expect(screen.getByText("Token Usage")).toBeInTheDocument();
    expect(screen.queryByText("Token activity")).not.toBeInTheDocument();
    expect(screen.queryByText("Total tokens")).not.toBeInTheDocument();
    expect(screen.queryByText("Peak tokens")).not.toBeInTheDocument();
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

    expect(screen.getByLabelText("2026-06-03: 1.5K tokens, 2 requests")).toBeInTheDocument();
  });
});
