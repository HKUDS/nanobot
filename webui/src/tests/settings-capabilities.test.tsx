import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SettingsPayload } from "@/lib/types";
import { DEFAULT_TRANSCRIPTION_SETTINGS } from "@/components/settings/capabilities/TranscriptionSettings";
import { requestMutationMock, jsonResponse, settingsPayload, renderSettingsView, openPopover, installSettingsViewTestHooks } from "@/tests/settings-test-utils";


describe("Settings capabilities", () => {
  installSettingsViewTestHooks();

  it("opens configuration for disabled features without enabling them", () => {
    const payload = settingsPayload();
    payload.image_generation.enabled = false;
    payload.transcription = { ...DEFAULT_TRANSCRIPTION_SETTINGS, enabled: false };
    payload.runtime_config = { "tools.web.enable": false };
    renderSettingsView({ initialSection: "capabilities", initialSettings: payload });
    for (const name of ["Image generation", "Transcription", "Web access"]) {
      expect(screen.getByRole("switch", { name })).not.toBeChecked();
      fireEvent.click(screen.getByRole("button", { name, exact: true }));
      const dialog = screen.getByRole("dialog", { name });
      expect(within(dialog).getAllByRole("combobox").length).toBeGreaterThan(0);
      fireEvent.click(within(dialog).getByRole("button", { name: "Close", exact: true }));
      expect(screen.getByRole("switch", { name })).not.toBeChecked();
    }
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("keeps other capability switches stable while saving and queues their edits", async () => {
    const payload = { ...settingsPayload(), runtime_config: {
      "tools.web.enable": true, "agents.defaults.dream.enabled": true,
    } };
    const memorySaved = { ...payload, runtime_config: { ...payload.runtime_config, "agents.defaults.dream.enabled": false } };
    let finishMemory!: (value: SettingsPayload) => void;
    requestMutationMock.mockImplementationOnce(() => new Promise<SettingsPayload>((resolve) => { finishMemory = resolve; }))
      .mockResolvedValueOnce({ ...memorySaved, runtime_config: { ...memorySaved.runtime_config, "tools.web.enable": false } });
    renderSettingsView({ initialSection: "capabilities", initialSettings: payload });
    const memory = screen.getByRole("switch", { name: "Memory consolidation" });
    const web = screen.getByRole("switch", { name: "Web access" });
    const webStyle = web.className;
    fireEvent.click(memory);
    await waitFor(() => expect(memory).toBeDisabled());
    expect(web).toBeEnabled();
    expect(web).toBeChecked();
    expect(web.className).toBe(webStyle);
    fireEvent.click(web);
    expect(web).not.toBeChecked();
    await act(async () => finishMemory(memorySaved));
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.runtime_config.update", { values: { "tools.web.enable": false } }, 20_000,
    ));
    await waitFor(() => expect(web).toBeEnabled());
    expect(memory).not.toBeChecked();
    expect(web).not.toBeChecked();
  });

  it("keeps missing image credentials local and does not submit an invalid draft", async () => {
    renderSettingsView({ initialSection: "capabilities", initialSettings: settingsPayload() });
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    const image = within(screen.getByRole("dialog", { name: "Image generation" }));
    expect(image.getByRole("alert")).toHaveTextContent("Configure this provider before enabling image generation.");
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(requestMutationMock).not.toHaveBeenCalled();
    expect(screen.queryByText("image generation provider is not configured")).not.toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("keeps a rejected image save attached to the feature when its editor is collapsed", async () => {
    const payload = settingsPayload();
    payload.image_generation.providers = [{ name: "openrouter", label: "OpenRouter", configured: true }];
    requestMutationMock.mockRejectedValue(new Error("image generation provider is not configured"));
    renderSettingsView({ initialSection: "capabilities", initialSettings: payload });
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    const image = within(screen.getByRole("dialog", { name: "Image generation" }));
    await waitFor(() => expect(image.getByRole("alert")).toHaveTextContent("Configure this provider before enabling image generation."));
    expect(screen.queryByText("image generation provider is not configured")).not.toBeInTheDocument();
    fireEvent.click(image.getByRole("button", { name: "Close", exact: true }));
    expect(screen.getByRole("region", { name: "Image generation" })).toContainElement(screen.getByRole("alert"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("keeps capabilities together and separates expanding settings from enabling a feature", () => {
    const payload = settingsPayload();
    payload.image_generation.enabled = true;
    payload.image_generation.providers = [{ name: "openrouter", label: "OpenRouter", configured: true }];
    payload.runtime_config = { "tools.web.enable": true, "agents.defaults.dream.enabled": true };
    renderSettingsView({ initialSection: "capabilities", initialSettings: payload });
    expect(screen.getAllByRole("switch")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Capabilities", exact: true })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: "Image", exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "OpenRouter", exact: true })).not.toBeInTheDocument();
    const editor = screen.getByRole("button", { name: "Image generation", exact: true });
    expect(editor).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(editor);
    expect(editor).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("combobox", { name: "OpenRouter", exact: true })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    expect(screen.queryByRole("button", { name: "OpenRouter", exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Image generation" })).toBeChecked();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("reveals image settings only after enabling and preserves them when disabled", async () => {
    const payload = settingsPayload();
    payload.image_generation.providers = [{ name: "openrouter", label: "OpenRouter", configured: true }];
    requestMutationMock.mockImplementation(async (_method, update) => ({
      ...payload,
      image_generation: { ...payload.image_generation, enabled: update.enabled },
      requires_restart: true,
      restart_required_sections: ["image"],
    }));
    renderSettingsView({ initialSection: "image", initialSettings: payload });

    expect(screen.queryByRole("button", { name: "OpenRouter" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    expect(screen.getByRole("combobox", { name: "OpenRouter" })).toBeVisible();
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.image_generation.update", expect.objectContaining({ enabled: true }), 20_000,
    ));
    await waitFor(() => expect(screen.queryByText("Saving…")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    expect(screen.queryByRole("button", { name: "OpenRouter" })).not.toBeInTheDocument();
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.image_generation.update", expect.objectContaining({
        enabled: false, provider: "openrouter", model: payload.image_generation.model,
      }), 20_000,
    ));
    expect(await screen.findByText("Saved. Restart when ready.")).toBeVisible();
  });

  it("hides web search details until web tools are enabled", async () => {
    const payload = { ...settingsPayload(), runtime_config: { "tools.web.enable": false } };
    requestMutationMock.mockResolvedValue({
      ...payload, runtime_config: { "tools.web.enable": true },
    });
    renderSettingsView({ initialSection: "browser", initialSettings: payload });
    expect(screen.queryByRole("button", { name: "DuckDuckGo" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Web access" }));
    expect(screen.getByRole("combobox", { name: "DuckDuckGo" })).toBeVisible();
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.web.enable": true } }, 20_000,
    ));
  });

  it("hides voice configuration while transcription is disabled", () => {
    const payload: SettingsPayload = { ...settingsPayload(), transcription: {
      enabled: false, provider: "groq", provider_configured: true, model: "whisper-large-v3",
      language: null, max_duration_sec: 120, max_upload_mb: 25,
      providers: [{ name: "groq", label: "Groq", configured: true }],
    } };
    renderSettingsView({ initialSection: "voice", initialSettings: payload });
    expect(screen.queryByRole("button", { name: "Groq" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Transcription" }));
    expect(screen.getByRole("combobox", { name: "Groq" })).toBeVisible();
    expect(screen.getByDisplayValue("whisper-large-v3")).toBeVisible();
  });


  it("selects image models from provider-specific options", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      image_generation: {
        ...base.image_generation,
        enabled: true,
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
    fireEvent.keyDown(screen.getByRole("combobox", { name: "OpenRouter" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: "Gemini" }));

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

    fireEvent.keyDown(screen.getByRole("combobox", { name: "Gemini" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: "Custom" }));
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
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();

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

    fireEvent.keyDown(await screen.findByRole("combobox", { name: /DuckDuckGo/ }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: "Keenable" }));
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();

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
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();

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
