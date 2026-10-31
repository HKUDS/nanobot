import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { SettingsView } from "@/components/settings/SettingsView";
import { ClientProvider } from "@/providers/ClientProvider";
import { expect, it, vi } from "vitest";
import type { SettingsPayload } from "@/lib/types";
import { DEFAULT_TRANSCRIPTION_SETTINGS } from "@/components/settings/capabilities/TranscriptionSettings";
import { requestMutationMock, jsonResponse, settingsPayload, renderSettingsView, openPopover, installSettingsViewTestHooks } from "@/tests/settings-test-utils";


describe("Settings capabilities", () => {
  installSettingsViewTestHooks();

  it("uses a named image connection and saves image-only parameters", async () => {
    const payload = settingsPayload();
    payload.image_generation = {
      ...payload.image_generation, enabled: true, provider: "custom-sensenova",
      request_overrides_supported: true,
      providers: [{ name: "custom-sensenova", label: "SenseNova", configured: true, uses_images_api: true, api_base: "https://images.test/v1" }],
    };
    requestMutationMock.mockImplementation(async (_action, args) => ({
      ...payload, image_generation: {
        ...payload.image_generation,
        extra_headers: args.extra_headers ? JSON.parse(args.extra_headers) : null,
        extra_body: args.extra_body ? JSON.parse(args.extra_body) : null,
      },
    }));
    requestMutationMock.mockRejectedValueOnce(new Error("Could not save. Try again."));
    renderSettingsView({ initialSection: "image", initialSettings: payload });
    expect(screen.getByRole("combobox", { name: "SenseNova" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Provider" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Advanced options" }));
    fireEvent.click(screen.getByRole("button", { name: "Body parameters Use provider settings Edit" }));
    const editor = screen.getByRole("dialog", { name: "Body parameters" });
    fireEvent.change(within(editor).getByRole("textbox", { name: "Body parameters" }), { target: { value: '{"watermark":false}' } });
    fireEvent.click(within(editor).getByRole("button", { name: "Save" }));
    expect(await within(editor).findByRole("alert")).toHaveTextContent("Could not save. Try again.");
    expect(within(editor).getByRole("textbox")).toHaveValue('{"watermark":false}');
    fireEvent.click(within(editor).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.image_generation.update",
      expect.objectContaining({ provider: "custom-sensenova", extra_body: '{"watermark":false}' }),
      20_000,
    ));
    expect(await screen.findByRole("button", { name: "Body parameters Entries: 1 Edit" })).toBeEnabled();
  });

  it("does not display a different image connection when the saved one is missing", () => {
    const payload = settingsPayload();
    payload.image_generation = {
      ...payload.image_generation, enabled: true, provider: "missing-connection",
      providers: [{ name: "openai", label: "OpenAI", configured: true, api_base: "https://unrelated.test" }],
    };
    renderSettingsView({ initialSection: "image", initialSettings: payload });
    expect(screen.queryByText("https://unrelated.test")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Configure this provider");
  });

  it("opens configuration for disabled features without enabling them", () => {
    const payload = settingsPayload();
    payload.image_generation.enabled = false;
    payload.transcription = { ...DEFAULT_TRANSCRIPTION_SETTINGS, enabled: false };
    payload.runtime_config = { "tools.web.enable": false };
    renderSettingsView({ initialSection: "capabilities", initialSettings: payload });
    for (const name of ["Image generation", "Transcription", "Web access"]) {
      expect(screen.getByRole("switch", { name })).not.toBeChecked();
      fireEvent.click(within(screen.getByRole("region", { name })).getByRole("button", { name: "Configure" }));
      const dialog = screen.getByRole("dialog", { name });
      expect(within(dialog).getAllByRole("combobox").length).toBeGreaterThan(0);
      fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
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
    expect(memory).toHaveClass("h-5", "w-9", "bg-foreground");
    expect(web).toHaveClass("h-5", "w-9", "bg-foreground");
    const webStyle = web.className;
    fireEvent.click(memory);
    await waitFor(() => expect(memory).toBeDisabled());
    expect(web).toBeEnabled();
    expect(web).toBeChecked();
    expect(web.className).toBe(webStyle);
    fireEvent.click(web);
    expect(web).not.toBeChecked();
    expect(web).toHaveClass("bg-muted-foreground/25");
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
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("retains an invalid capability draft while navigating to repair its provider", () => {
    renderSettingsView({ initialSection: "capabilities", initialSettings: settingsPayload() });
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Image generation" })).getByRole("button", { name: "Configure provider" }));
    expect(screen.getByRole("button", { name: "Models" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: "Capabilities" }));
    expect(screen.getByRole("switch", { name: "Image generation" })).toBeChecked();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("keeps a rejected image draft in its editor until retry succeeds", async () => {
    const payload = settingsPayload();
    payload.image_generation.providers = [{ name: "openrouter", label: "OpenRouter", configured: true }];
    requestMutationMock.mockRejectedValue(new Error("image generation provider is not configured"));
    renderSettingsView({ initialSection: "capabilities", initialSettings: payload });
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    const image = within(screen.getByRole("dialog", { name: "Image generation" }));
    await waitFor(() => expect(image.getByRole("alert")).toHaveTextContent("Configure this provider before enabling image generation."));
    fireEvent.click(image.getByRole("button", { name: "Close" }));
    await act(async () => {});
    expect(screen.getByRole("dialog", { name: "Image generation" })).toContainElement(screen.getByRole("alert"));
    requestMutationMock.mockResolvedValue({ ...payload, image_generation: { ...payload.image_generation, enabled: true } });
    fireEvent.click(image.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps capabilities together and separates expanding settings from enabling a feature", () => {
    const payload = settingsPayload();
    payload.image_generation.enabled = true;
    payload.image_generation.providers = [{ name: "openrouter", label: "OpenRouter", configured: true }];
    payload.runtime_config = { "tools.web.enable": true, "agents.defaults.dream.enabled": true };
    renderSettingsView({ initialSection: "capabilities", initialSettings: payload });
    expect(screen.getAllByRole("switch")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Capabilities" })).toHaveAttribute("aria-current", "page");
    const editor = screen.getByRole("button", { name: "Image generation" });
    expect(editor).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(editor);
    expect(editor).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("combobox", { name: "OpenRouter" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
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

    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    expect(screen.getByRole("combobox", { name: "OpenRouter" })).toBeVisible();
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.image_generation.update", expect.objectContaining({ enabled: true }), 20_000,
    ));
    expect(await screen.findByText("Saved. Restart to apply changes.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.image_generation.update", expect.objectContaining({
        enabled: false, provider: "openrouter", model: payload.image_generation.model,
      }), 20_000,
    ));
    expect(await screen.findByText("Saved. Restart to apply changes.")).toBeVisible();
  });

  it("reveals web search settings when web tools are enabled", async () => {
    const payload = { ...settingsPayload(), runtime_config: { "tools.web.enable": false } };
    requestMutationMock.mockResolvedValue({
      ...payload, runtime_config: { "tools.web.enable": true },
    });
    renderSettingsView({ initialSection: "browser", initialSettings: payload });
    fireEvent.click(screen.getByRole("switch", { name: "Web access" }));
    expect(screen.getByRole("combobox", { name: "DuckDuckGo" })).toBeVisible();
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.web.enable": true } }, 20_000,
    ));
  });

  it("reveals the configured transcription provider and model when enabled", () => {
    const payload: SettingsPayload = { ...settingsPayload(), transcription: {
      enabled: false, provider: "groq", provider_configured: true, model: "whisper-large-v3",
      language: null, max_duration_sec: 120, max_upload_mb: 25,
      providers: [{ name: "groq", label: "Groq", configured: true }],
    } };
    renderSettingsView({ initialSection: "voice", initialSettings: payload });
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

    requestMutationMock.mockImplementation(async (_action, args) => {
      payload.image_generation = { ...payload.image_generation, provider: args.provider, model: args.model };
      return { ...payload };
    });
    renderSettingsView({ initialSection: "image", initialSettings: payload });

    fireEvent.keyDown(screen.getByRole("combobox", { name: "OpenRouter" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: "Gemini" }));

    const modelInput = screen.getByRole("combobox", { name: "Select image model" });
    await waitFor(() => expect(modelInput).toHaveValue("gemini-2.5-flash-image"));
    await openPopover(modelInput);
    fireEvent.click(await screen.findByRole("option", { name: "imagen-4.0-generate-001" }));
    await waitFor(() => expect(modelInput).toHaveValue("imagen-4.0-generate-001"));

    await openPopover(modelInput);
    fireEvent.change(modelInput, { target: { value: "imagen-5-preview" } });
    fireEvent.click(await screen.findByRole("option", { name: "Use “imagen-5-preview”" }));
    await waitFor(() => expect(modelInput).toHaveValue("imagen-5-preview"));

    fireEvent.keyDown(screen.getByRole("combobox", { name: "Gemini" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: "Custom" }));
    const customProviderInput = screen.getByRole("combobox", { name: "Select image model" });
    expect(customProviderInput).toHaveValue("imagen-5-preview");

    await openPopover(customProviderInput);
    fireEvent.change(customProviderInput, { target: { value: "private/image-v2" } });
    fireEvent.keyDown(customProviderInput, { key: "Enter" });
    await waitFor(() => expect(customProviderInput).toHaveValue("private/image-v2"));
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
    expect(screen.getByText("Default access")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Default Permission" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Full Access" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Local services" }));

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

  it("saves the web proxy switch separately from the shared address in Advanced", async () => {
    let payload = { ...settingsPayload(), runtime_config: {
      "tools.web.enable": false, "tools.web.use_proxy": false,
      "network.proxy": "http://old-proxy.example:8080", "tools.web.user_agent": null,
    } } as SettingsPayload;
    requestMutationMock.mockImplementation(async (_method, update) => {
      payload = { ...payload, runtime_config: { ...payload.runtime_config, ...update.values },
        requires_restart: true, restart_required_sections: ["runtime"] };
      return payload;
    });
    renderSettingsView({ initialSection: "capabilities", initialSettings: payload });
    fireEvent.click(within(screen.getByRole("region", { name: "Web access" })).getByRole("button", { name: "Configure" }));
    fireEvent.click(screen.getByRole("button", { name: "Advanced options" }));
    const useProxy = screen.getByRole("switch", { name: "Use proxy" });
    expect(useProxy).not.toBeChecked();
    expect(screen.queryByRole("textbox", { name: /proxy/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Shared proxy")).not.toBeInTheDocument();
    fireEvent.click(useProxy);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.web.use_proxy": true } }, 20_000,
    ));
    await waitFor(() => expect(useProxy).toBeEnabled());
    expect(useProxy).toBeChecked();
    fireEvent.click(useProxy);
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.runtime_config.update", { values: { "tools.web.use_proxy": false } }, 20_000,
    ));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Web access" })).getByRole("button", { name: "Close" }));
    expect(screen.getByRole("switch", { name: "Web access" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    const proxy = screen.getByRole("textbox", { name: "Shared proxy" });
    expect(proxy).toHaveAttribute("type", "text");
    expect(proxy).toHaveValue("http://old-proxy.example:8080");
    expect(screen.queryByRole("switch", { name: "Use proxy" })).not.toBeInTheDocument();
    const address = "http://user:secret@new-proxy.example:7890";
    fireEvent.change(proxy, { target: { value: address } });
    expect(proxy).toHaveValue("http://new-proxy.example:7890");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    fireEvent.click(within(screen.getByRole("region", { name: "Shared proxy" })).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.runtime_config.update", { values: { "network.proxy": address } }, 20_000,
    ));
    fireEvent.click(screen.getByRole("button", { name: "System" }));
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByLabelText("Shared proxy", { selector: "input" })).toHaveValue("http://new-proxy.example:7890");
    expect(screen.getByLabelText("Username")).toHaveValue("user");
    expect(screen.getByLabelText("Password")).toHaveValue("secret");
    expect(document.body).not.toHaveTextContent(address);
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

  it("requires an explicit DeepSeek search key before saving and preserves it on later edits", async () => {
    let payload: SettingsPayload = settingsPayload();
    payload.web_search.providers.push({
      name: "deepseek", label: "DeepSeek", credential: "api_key",
    });
    requestMutationMock.mockImplementation(async (_method, update) => {
      payload = { ...payload, web_search: {
        ...payload.web_search, provider: update.provider, timeout: update.timeout,
        api_key_hint: "sk-d...key",
      } };
      return payload;
    });
    renderSettingsView({ initialSection: "browser", initialSettings: payload });

    fireEvent.keyDown(screen.getByRole("combobox", { name: "DuckDuckGo" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: "DeepSeek" }));
    expect(await screen.findByText("Add the required credential before saving.")).toBeVisible();
    expect(requestMutationMock).not.toHaveBeenCalled();
    const key = screen.getByPlaceholderText("Enter API key");
    fireEvent.change(key, { target: { value: "sk-deepseek-search-key" } });
    fireEvent.blur(key);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.web_search.update",
      { provider: "deepseek", api_key: "sk-deepseek-search-key", max_results: 5, timeout: 30, use_jina_reader: true },
      20_000,
    ));
    expect(await screen.findByText("sk-d...key")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Advanced options" }));
    const timeout = screen.getAllByRole("spinbutton").find((input) => (input as HTMLInputElement).value === "30")!;
    fireEvent.change(timeout, { target: { value: "45" } });
    fireEvent.blur(timeout);
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.web_search.update",
      { provider: "deepseek", max_results: 5, timeout: 45, use_jina_reader: true },
      20_000,
    ));
  });

  it("keeps a newer credential draft visible when an older save response arrives", async () => {
    const payload = settingsPayload();
    payload.web_search = { ...payload.web_search, provider: "deepseek", api_key_hint: "old-key",
      providers: [...payload.web_search.providers, { name: "deepseek", label: "DeepSeek", credential: "api_key" }] };
    let finish!: (value: SettingsPayload) => void;
    requestMutationMock.mockImplementationOnce(() => new Promise<SettingsPayload>((resolve) => { finish = resolve; }))
      .mockResolvedValue({ ...payload, web_search: { ...payload.web_search, api_key_hint: "latest-key" } });
    renderSettingsView({ initialSection: "browser", initialSettings: payload });
    const credential = screen.getByText("old-key").parentElement!;
    fireEvent.click(within(credential).getByRole("button", { name: "Edit" }));
    const key = credential.querySelector("input")!;
    fireEvent.focus(key);
    fireEvent.change(key, { target: { value: "first-key" } });
    fireEvent.blur(key);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(1));
    fireEvent.focus(key);
    fireEvent.change(key, { target: { value: "latest-key" } });
    await act(async () => finish({ ...payload, web_search: { ...payload.web_search, api_key_hint: "first-key" } }));
    expect(key).toBeVisible();
    expect(key).toHaveValue("latest-key");
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    fireEvent.blur(key);
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.web_search.update", expect.objectContaining({ api_key: "latest-key" }), 20_000,
    ));
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
    fireEvent.click(screen.getByRole("button", { name: "Local services" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Allow Full Access shell commands to reach services on this Mac.");
  });

  it("keeps a newer focused transcription draft through automatic native restart", async () => {
    const payload = {
      ...settingsPayload(), surface: "native" as const, runtime_surface: "native" as const,
      runtime_capabilities: { can_restart_engine: true, can_open_logs: true, can_export_diagnostics: true },
      transcription: { ...DEFAULT_TRANSCRIPTION_SETTINGS, enabled: true, language: "en" },
    };
    const saved = { ...payload, requires_restart: true, transcription: { ...payload.transcription, language: "zh" } };
    let finishRestart!: (token: string) => void;
    const restart = vi.fn(() => new Promise<string>((resolve) => { finishRestart = resolve; }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/settings") return jsonResponse(
        (init?.headers as Record<string, string> | undefined)?.Authorization === "Bearer fresh-token"
          ? { ...saved, requires_restart: false } : payload,
      );
      return jsonResponse({ apps: [], presets: [], installed_count: 0 });
    }));
    requestMutationMock.mockResolvedValueOnce(saved);
    let refreshParent!: (snapshot: SettingsPayload) => void;
    let parentSnapshot: SettingsPayload = payload;
    function Parent() {
      const [snapshot, setSnapshot] = useState<SettingsPayload>(payload);
      parentSnapshot = snapshot;
      refreshParent = setSnapshot;
      return <ClientProvider client={{ requestMutation: requestMutationMock, status: "open",
        onStatus: (handler: (status: "open") => void) => { handler("open"); return () => {}; },
      } as never} token="tok">
        <SettingsView themePreference="light" initialSection="voice" initialSettings={snapshot}
          onSettingsChange={setSnapshot} onNativeEngineRestart={restart}
          onChangeTheme={() => {}} onBackToChat={() => {}} onModelNameChange={() => {}} />
      </ClientProvider>;
    }
    render(<Parent />);
    await act(async () => {});
    const language = screen.getByPlaceholderText("Auto");
    fireEvent.focus(language);
    fireEvent.change(language, { target: { value: "zh" } });
    fireEvent.blur(language);
    await waitFor(() => expect(restart).toHaveBeenCalledTimes(1));
    fireEvent.focus(language);
    fireEvent.change(language, { target: { value: "ja" } });
    expect(parentSnapshot.requires_restart).toBe(true);
    await act(async () => refreshParent({ ...saved, requires_restart: false }));
    expect(language).toHaveValue("ja");
    await act(async () => finishRestart("fresh-token"));
    expect(language).toHaveValue("ja");
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
  });

  it("refreshes settings with a fresh token after native engine restart", async () => {
    const payload = {
      ...settingsPayload(),
      surface: "native" as const,
      runtime_surface: "native" as const,
      runtime_capabilities: {
        can_restart_engine: true,
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
