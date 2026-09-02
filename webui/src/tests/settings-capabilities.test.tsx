import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SettingsPayload } from "@/lib/types";
import { requestMutationMock, jsonResponse, settingsPayload, renderSettingsView, openPopover, installSettingsViewTestHooks } from "@/tests/settings-test-utils";


describe("Settings capabilities", () => {
  installSettingsViewTestHooks();


  it("selects image models from provider-specific options", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      image_generation: {
        ...base.image_generation,
        providers: [
          {
            name: "openrouter",
            label: "OpenRouter",
            configured: true,
            models: ["openai/gpt-5.4-image-2"],
            default_model: "openai/gpt-5.4-image-2",
          },
          {
            name: "gemini",
            label: "Gemini",
            configured: true,
            models: ["gemini-2.5-flash-image", "imagen-4.0-generate-001"],
            default_model: "gemini-2.5-flash-image",
          },
          {
            name: "custom",
            label: "Custom",
            configured: true,
            models: [],
            default_model: null,
          },
        ],
      },
    };

    renderSettingsView({ initialSection: "image", initialSettings: payload });

    expect(screen.queryByDisplayValue("openai/gpt-5.4-image-2")).not.toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "OpenRouter" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Gemini" }));

    expect(await screen.findByRole("button", { name: "gemini-2.5-flash-image" })).toBeInTheDocument();
    await openPopover(screen.getByRole("button", { name: "gemini-2.5-flash-image" }));
    fireEvent.click(await screen.findByRole("option", { name: "imagen-4.0-generate-001" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "imagen-4.0-generate-001" })).toBeInTheDocument(),
    );

    await openPopover(screen.getByRole("button", { name: "imagen-4.0-generate-001" }));
    const modelInput = await screen.findByRole("combobox", { name: "Search or type model ID" });
    fireEvent.change(modelInput, { target: { value: "imagen-5-preview" } });
    fireEvent.click(await screen.findByRole("option", { name: "Use “imagen-5-preview”" }));
    expect(await screen.findByRole("button", { name: "imagen-5-preview" })).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", { name: "Gemini" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Custom" }));
    expect(screen.getByRole("button", { name: "imagen-5-preview" })).toBeInTheDocument();

    await openPopover(screen.getByRole("button", { name: "imagen-5-preview" }));
    const customProviderInput = await screen.findByRole("combobox", {
      name: "Search or type model ID",
    });
    fireEvent.change(customProviderInput, { target: { value: "private/image-v2" } });
    fireEvent.keyDown(customProviderInput, { key: "Enter" });
    expect(await screen.findByRole("button", { name: "private/image-v2" })).toBeInTheDocument();
  });

  it("saves network safety without exposing technical SSRF copy", async () => {
    const payload = settingsPayload();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      ...payload,
      advanced: { ...payload.advanced, webui_allow_local_service_access: false },
      requires_restart: true,
      restart_required_sections: ["runtime"],
    });

    renderSettingsView({ initialSection: "advanced" });

    expect(await screen.findByText("Web safety")).toBeInTheDocument();
    expect(screen.queryByText(/SSRF/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Private Service Protection")).not.toBeInTheDocument();
    expect(screen.getByText("Default access")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restricted" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Default Permission" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Full Access" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Local services" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.network_safety.update",
        {
          webui_allow_local_service_access: false,
          webui_default_access_mode: "default",
        },
        20_000,
      ),
    );
  });

  it("saves optional-key web search providers without an API key", async () => {
    const payload = {
      ...settingsPayload(),
      web_search: {
        ...settingsPayload().web_search,
        provider: "duckduckgo",
        providers: [
          { name: "duckduckgo", label: "DuckDuckGo", credential: "none" as const },
          { name: "keenable", label: "Keenable", credential: "optional_api_key" as const },
        ],
      },
    };
    const updatedPayload = {
      ...payload,
      web_search: {
        ...payload.web_search,
        provider: "keenable",
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce(updatedPayload);

    renderSettingsView({ initialSection: "browser" });

    fireEvent.pointerDown(await screen.findByRole("button", { name: /DuckDuckGo/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Keenable" }));
    const saveButton = screen
      .getAllByRole("button", { name: "Save" })
      .find((button) => !(button as HTMLButtonElement).disabled);
    if (!saveButton) throw new Error("enabled Save button was not found");
    fireEvent.click(saveButton);

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.web_search.update",
        {
          provider: "keenable",
          max_results: 5,
          timeout: 30,
          use_jina_reader: true,
        },
        20_000,
      ),
    );
  });

  it("uses native host safety copy on the native surface", async () => {
    const payload = {
      ...settingsPayload(),
      surface: "native" as const,
      runtime_surface: "native" as const,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "advanced" });

    expect(await screen.findByText("App safety")).toBeInTheDocument();
    expect(screen.queryByText("Web safety")).not.toBeInTheDocument();
    expect(screen.getByText("Allow Full Access shell commands to reach services on this Mac.")).toBeInTheDocument();
  });

  it("refreshes settings with a fresh token after native engine restart", async () => {
    const payload = {
      ...settingsPayload(),
      surface: "native" as const,
      runtime_surface: "native" as const,
      runtime_capabilities: {
        can_restart_engine: true,
        can_pick_folder: true,
        can_open_logs: true,
        can_export_diagnostics: true,
      },
    };
    const restartedPayload = {
      ...payload,
      advanced: { ...payload.advanced, webui_allow_local_service_access: false },
      requires_restart: true,
      restart_required_sections: ["runtime"],
    };
    const refreshedPayload = {
      ...restartedPayload,
      requires_restart: false,
      restart_required_sections: [],
    };
    const restartEngine = vi.fn(async () => "fresh-token");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const auth = (init?.headers as Record<string, string> | undefined)?.Authorization;
      if (url === "/api/settings" && auth === "Bearer fresh-token") {
        return jsonResponse(refreshedPayload);
      }
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce(restartedPayload);

    renderSettingsView({
      initialSection: "advanced",
      onNativeEngineRestart: restartEngine,
    });

    expect(await screen.findByText("App safety")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Local services" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(restartEngine).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          headers: { Authorization: "Bearer fresh-token" },
        }),
      ),
    );
  });
});
