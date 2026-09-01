import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SettingsPayload } from "@/lib/types";
import { requestMutationMock, jsonResponse, settingsPayload, renderSettingsView, installSettingsViewTestHooks } from "@/tests/settings-test-utils";


async function chooseProviderToConfigure(label: string) {
  fireEvent.pointerDown(
    await screen.findByRole("button", { name: "Add your own model provider" }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: label }));
}

describe("Settings providers", () => {
  installSettingsViewTestHooks();


  it("signs in to the xAI Grok provider", async () => {
    const base = settingsPayload();
    const xaiProvider = {
      name: "xai_grok",
      label: "xAI Grok",
      configured: false,
      auth_type: "oauth" as const,
      api_key_required: false,
      api_key_hint: null,
      api_base: null,
      default_api_base: "https://cli-chat-proxy.grok.com/v1",
      model_catalog: "builtin",
      oauth_account: null,
      oauth_expires_at: null,
      oauth_login_supported: true,
    };
    const payload: SettingsPayload = { ...base, providers: [xaiProvider] };
    const signedIn: SettingsPayload = {
      ...payload,
      providers: [{ ...xaiProvider, configured: true, oauth_account: "user@example.com" }],
    };
    const authorization = {
      status: "authorization_required",
      provider: "xai_grok",
      flow_id: "flow-123",
      authorization_url: "https://auth.x.ai/oauth2/authorize?state=test",
      expires_in: 600,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock
      .mockResolvedValueOnce(authorization)
      .mockResolvedValueOnce(signedIn);
    const popup = {
      opener: window,
      location: { href: "about:blank" },
      close: vi.fn(),
    };
    vi.stubGlobal("open", vi.fn(() => popup));

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await chooseProviderToConfigure("xAI Grok");

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.provider.oauth_login",
        { provider: "xai_grok" },
        20_000,
      ),
    );
    expect(popup.opener).toBeNull();
    expect(popup.location.href).toBe(authorization.authorization_url);

    expect(
      screen.getByText(
        "Complete sign-in in your browser. Nanobot usually finishes automatically; if it does not, paste the authorization code below.",
      ),
    ).toBeInTheDocument();
    const callbackInput = await screen.findByRole("textbox", {
      name: "Authorization code",
    });
    fireEvent.change(callbackInput, {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Finish sign-in" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.provider.oauth_complete",
        {
          provider: "xai_grok",
          flow_id: "flow-123",
          authorization_response: "secret",
        },
        20_000,
      ),
    );
    expect(await screen.findByText("Signed in as user@example.com")).toBeInTheDocument();
  });

  it("recognizes remote access before starting xAI Grok sign-in", async () => {
    const happyWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void };
    };
    const originalUrl = window.location.href;
    happyWindow.happyDOM.setURL("http://203.0.113.10:18887/#/settings?section=models");

    try {
      const base = settingsPayload();
      const xaiProvider = {
        name: "xai_grok",
        label: "xAI Grok",
        configured: false,
        auth_type: "oauth" as const,
        api_key_required: false,
        api_key_hint: null,
        api_base: null,
        default_api_base: "https://cli-chat-proxy.grok.com/v1",
        model_catalog: "builtin",
        oauth_account: null,
        oauth_expires_at: null,
        oauth_login_supported: true,
      };
      const payload: SettingsPayload = { ...base, providers: [xaiProvider] };
      const authorization = {
        status: "authorization_required",
        provider: "xai_grok",
        flow_id: "flow-remote",
        authorization_url: "https://auth.x.ai/oauth2/authorize?state=remote",
        expires_in: 600,
      };
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return jsonResponse({});
      });
      vi.stubGlobal("fetch", fetchMock);
      requestMutationMock.mockResolvedValueOnce(authorization);
      const popup = {
        opener: window,
        location: { href: "about:blank" },
        close: vi.fn(),
      };
      const openMock = vi.fn(() => popup);
      vi.stubGlobal("open", openMock);

      renderSettingsView({ initialSection: "models", initialSettings: payload });

      await chooseProviderToConfigure("xAI Grok");
      expect(
        screen.getByText(
          "Select Sign in to open xAI on your computer, then paste the authorization code shown after login.",
        ),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      const dialog = await screen.findByRole("dialog");

      expect(openMock).not.toHaveBeenCalled();
      expect(
        within(dialog).getByText(
          "Select Sign in to open xAI on your computer. After signing in, paste the authorization code shown by xAI below.",
        ),
      ).toBeInTheDocument();
      expect(
        within(dialog).queryByRole("textbox", { name: "xAI sign-in URL" }),
      ).not.toBeInTheDocument();
      expect(
        within(dialog).queryByRole("button", { name: "Copy" }),
      ).not.toBeInTheDocument();
      expect(
        within(dialog).getByRole("textbox", { name: "Authorization code" }),
      ).toBeInTheDocument();

      fireEvent.click(within(dialog).getByRole("button", { name: "Sign in" }));
      expect(openMock).toHaveBeenCalledWith(
        authorization.authorization_url,
        "_blank",
        "noopener,noreferrer",
      );
      expect(popup.opener).toBeNull();
    } finally {
      happyWindow.happyDOM.setURL(originalUrl);
    }
  });

  it("polls local OpenAI Codex sign-in until the loopback callback completes", async () => {
    const base = settingsPayload();
    const codexProvider = {
      name: "openai_codex",
      label: "OpenAI Codex",
      configured: false,
      auth_type: "oauth" as const,
      api_key_required: false,
      api_key_hint: null,
      api_base: null,
      default_api_base: "https://chatgpt.com/backend-api",
      model_catalog: "builtin",
      oauth_account: null,
      oauth_expires_at: null,
      oauth_login_supported: true,
    };
    const payload: SettingsPayload = { ...base, providers: [codexProvider] };
    const signedIn: SettingsPayload = {
      ...payload,
      providers: [{ ...codexProvider, configured: true, oauth_account: "acct-codex" }],
    };
    const authorization = {
      status: "authorization_required",
      provider: "openai_codex",
      flow_id: "flow-codex-local",
      authorization_url: "https://auth.openai.com/oauth/authorize?state=local",
      expires_in: 600,
      completion_input: "callback_url",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock
      .mockResolvedValueOnce(authorization)
      .mockResolvedValueOnce(signedIn);
    const openMock = vi.fn();
    vi.stubGlobal("open", openMock);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await chooseProviderToConfigure("OpenAI Codex");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const dialog = await screen.findByRole("dialog");

    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.provider.oauth_login",
      { provider: "openai_codex" },
      20_000,
    );
    expect(openMock).not.toHaveBeenCalled();
    expect(
      within(dialog).getByText(
        "Complete sign-in in your browser. Nanobot usually finishes automatically; if it does not, copy the full localhost callback URL from the address bar and paste it below.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Waiting for the browser callback…")).toBeInTheDocument();
    expect(
      within(dialog).queryByText("Paste the callback URL to continue."),
    ).not.toBeInTheDocument();

    expect(
      await screen.findByText("Signed in as acct-codex", {}, { timeout: 2500 }),
    ).toBeInTheDocument();
  });

  it("completes remote OpenAI Codex sign-in with the full callback URL", async () => {
    const happyWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void };
    };
    const originalUrl = window.location.href;
    happyWindow.happyDOM.setURL("http://203.0.113.10:18887/#/settings?section=models");

    try {
      const base = settingsPayload();
      const codexProvider = {
        name: "openai_codex",
        label: "OpenAI Codex",
        configured: false,
        auth_type: "oauth" as const,
        api_key_required: false,
        api_key_hint: null,
        api_base: null,
        default_api_base: "https://chatgpt.com/backend-api",
        model_catalog: "builtin",
        oauth_account: null,
        oauth_expires_at: null,
        oauth_login_supported: true,
      };
      const payload: SettingsPayload = { ...base, providers: [codexProvider] };
      const signedIn: SettingsPayload = {
        ...payload,
        providers: [{ ...codexProvider, configured: true, oauth_account: "acct-codex" }],
      };
      const authorization = {
        status: "authorization_required",
        provider: "openai_codex",
        flow_id: "flow-codex",
        authorization_url: "https://auth.openai.com/oauth/authorize?state=test",
        expires_in: 600,
        completion_input: "callback_url",
      };
      const callbackUrl =
        "http://localhost:1455/auth/callback?code=secret&state=test";
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return jsonResponse({});
      });
      vi.stubGlobal("fetch", fetchMock);
      requestMutationMock.mockImplementation(async (
        action: string,
        mutationPayload: Record<string, unknown>,
      ) => {
        if (action === "settings.provider.oauth_login") return authorization;
        if (mutationPayload.authorization_response === callbackUrl) return signedIn;
        return {
          status: "pending",
          provider: "openai_codex",
          flow_id: "flow-codex",
        };
      });
      const popup = {
        opener: window,
        location: { href: "about:blank" },
        close: vi.fn(),
      };
      const openMock = vi.fn(() => popup);
      vi.stubGlobal("open", openMock);

      renderSettingsView({ initialSection: "models", initialSettings: payload });

      await chooseProviderToConfigure("OpenAI Codex");
      expect(
        screen.getByText(
          "Sign in through this browser, then paste the full localhost callback URL back into nanobot.",
        ),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      const dialog = await screen.findByRole("dialog");

      expect(openMock).not.toHaveBeenCalled();
      expect(
        within(dialog).getByText(
          "Open ChatGPT in this browser and finish signing in. When the localhost page fails to load, copy the full URL from the address bar and paste it below.",
        ),
      ).toBeInTheDocument();
      expect(within(dialog).getByText("Paste the callback URL to continue.")).toBeInTheDocument();
      const callbackInput = within(dialog).getByRole("textbox", {
        name: "Full callback URL",
      });
      expect(callbackInput).toHaveAttribute(
        "placeholder",
        "http://localhost:1455/auth/callback?code=…&state=…",
      );

      fireEvent.click(within(dialog).getByRole("button", { name: "Open ChatGPT" }));
      expect(openMock).toHaveBeenCalledWith(
        authorization.authorization_url,
        "_blank",
        "noopener,noreferrer",
      );
      expect(popup.opener).toBeNull();

      fireEvent.change(callbackInput, { target: { value: callbackUrl } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Finish sign-in" }));

      await waitFor(() =>
        expect(requestMutationMock).toHaveBeenCalledWith(
          "settings.provider.oauth_complete",
          {
            provider: "openai_codex",
            flow_id: "flow-codex",
            authorization_response: callbackUrl,
          },
          20_000,
        ),
      );
      expect(await screen.findByText("Signed in as acct-codex")).toBeInTheDocument();
    } finally {
      happyWindow.happyDOM.setURL(originalUrl);
    }
  });

  it("saves scoped proxies for xAI and OpenAI Codex OAuth providers", async () => {
    const base = settingsPayload();
    const providers: SettingsPayload["providers"] = [
      {
        name: "xai_grok",
        label: "xAI Grok",
        configured: false,
        auth_type: "oauth",
        api_key_required: false,
        api_key_hint: null,
        api_base: null,
        default_api_base: "https://cli-chat-proxy.grok.com/v1",
        model_catalog: "builtin",
        oauth_account: null,
        oauth_expires_at: null,
        oauth_login_supported: true,
        proxy: "http://127.0.0.1:7000",
        advanced_fields: ["extra_body", "proxy"],
        extra_body: null,
      },
      {
        name: "openai_codex",
        label: "OpenAI Codex",
        configured: false,
        auth_type: "oauth",
        api_key_required: false,
        api_key_hint: null,
        api_base: null,
        default_api_base: "https://chatgpt.com/backend-api",
        model_catalog: "builtin",
        oauth_account: null,
        oauth_expires_at: null,
        oauth_login_supported: true,
        proxy: null,
        advanced_fields: ["extra_body", "proxy"],
        extra_body: null,
      },
    ];
    let payload: SettingsPayload = { ...base, providers };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (
      _action: string,
      values: { provider?: string; proxy?: string; extraBody?: string },
    ) => {
      payload = {
        ...payload,
        providers: payload.providers.map((provider) =>
          provider.name === values.provider
            ? {
                ...provider,
                proxy: values.proxy || null,
                extra_body: values.extraBody ? JSON.parse(values.extraBody) : null,
              }
            : provider,
        ),
      };
      return payload;
    });

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await chooseProviderToConfigure("xAI Grok");
    fireEvent.click(screen.getByRole("button", { name: "Advanced options" }));
    const xaiProxy = screen.getByLabelText("Network proxy");
    expect(xaiProxy).toHaveValue("http://127.0.0.1:7000");
    fireEvent.change(xaiProxy, { target: { value: "http://127.0.0.1:7890" } });
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute(
      "title",
      "Save advanced changes before signing in.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.provider.update",
        {
          provider: "xai_grok",
          extraBody: "",
          proxy: "http://127.0.0.1:7890",
        },
        20_000,
      ),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "xAI Grok" }));
    await chooseProviderToConfigure("OpenAI Codex");
    fireEvent.click(screen.getByRole("button", { name: "Advanced options" }));
    const codexProxy = screen.getByLabelText("Network proxy");
    expect(codexProxy).toHaveValue("");
    fireEvent.change(codexProxy, { target: { value: "http://proxy.example:8080" } });
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.provider.update",
        {
          provider: "openai_codex",
          extraBody: "",
          proxy: "http://proxy.example:8080",
        },
        20_000,
      ),
    );
  });

  it("maps provider request switches to raw extraBody fields", async () => {
    const base = settingsPayload();
    const providers: SettingsPayload["providers"] = [
      {
        name: "xai_grok",
        label: "xAI Grok",
        configured: true,
        auth_type: "oauth",
        api_key_required: false,
        oauth_account: "grok@example.com",
        oauth_login_supported: true,
        advanced_fields: ["extra_body", "proxy"],
        extra_body: null,
      },
      {
        name: "openai_codex",
        label: "OpenAI Codex",
        configured: true,
        auth_type: "oauth",
        api_key_required: false,
        oauth_account: "codex@example.com",
        oauth_login_supported: true,
        advanced_fields: ["extra_body", "proxy"],
        extra_body: null,
      },
      {
        name: "deepseek",
        label: "DeepSeek",
        configured: true,
        api_key_required: true,
        api_key_hint: "deep••••test",
        api_base: "https://api.deepseek.com",
        advanced_fields: ["extra_body"],
        extra_body: null,
      },
      {
        name: "openai",
        label: "OpenAI",
        configured: true,
        api_key_required: true,
        api_key_hint: "sk-••••test",
        api_base: "https://api.openai.com/v1",
        api_type: "auto",
        advanced_fields: ["api_type", "extra_body"],
        extra_body: null,
      },
    ];
    const payload: SettingsPayload = { ...base, providers };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValue(payload);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    fireEvent.click(screen.getByRole("button", { name: "xAI Grok" }));
    const xSearch = screen.getByRole("switch", { name: "X Search" });
    expect(xSearch).toHaveAttribute("aria-checked", "true");
    fireEvent.click(xSearch);
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.provider.update",
      expect.objectContaining({ provider: "xai_grok" }),
      20_000,
    ));
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Save provider" }),
    ).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "xAI Grok" }));
    fireEvent.click(screen.getByRole("button", { name: "OpenAI Codex" }));
    fireEvent.click(screen.getByRole("switch", { name: "Fast mode" }));
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.provider.update",
      expect.objectContaining({ provider: "openai_codex" }),
      20_000,
    ));
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Save provider" }),
    ).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "OpenAI Codex" }));
    fireEvent.click(screen.getByRole("button", { name: /^DeepSeek/ }));
    expect(screen.getByText(/DeepSeek V4 Flash/)).toBeInTheDocument();
    const deepSeekSearch = screen.getByRole("switch", { name: "DeepSeek web search" });
    expect(deepSeekSearch).toHaveAttribute("aria-checked", "true");
    fireEvent.click(deepSeekSearch);
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(
      screen.queryByRole("switch", { name: "DeepSeek web search" }),
    ).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /^OpenAI https:/ }));
    fireEvent.click(screen.getByRole("switch", { name: "OpenAI web search" }));
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(
      screen.queryByRole("switch", { name: "OpenAI web search" }),
    ).not.toBeInTheDocument());

    await waitFor(() => {
      const requestUpdates = requestMutationMock.mock.calls
        .filter(([action]) => action === "settings.provider.update")
        .map(([, values]) => {
          const update = values as {
            provider: string;
            apiType?: string;
            extraBody?: string;
          };
          return [update.provider, {
            ...(update.apiType ? { apiType: update.apiType } : {}),
            extraBody: JSON.parse(update.extraBody ?? "{}"),
          }] as const;
        });
      expect(requestUpdates).toEqual([
        ["xai_grok", { extraBody: { tools: [] } }],
        ["openai_codex", { extraBody: { service_tier: "priority" } }],
        ["deepseek", { extraBody: { tools: [] } }],
        ["openai", {
          apiType: "responses",
          extraBody: { tools: [{ type: "web_search" }] },
        }],
      ]);
    });
  });

  it("recognizes and removes versioned web search tools without losing raw settings", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      providers: [{
        name: "openai",
        label: "OpenAI",
        configured: true,
        api_key_required: true,
        api_key_hint: "sk-••••test",
        api_base: "https://api.openai.com/v1",
        api_type: "auto",
        advanced_fields: ["api_type", "extra_body"],
        extra_body: {
          metadata: { owner: "legacy-config" },
          tools: [
            { type: "web_search_preview", search_context_size: "medium" },
            { type: "file_search", vector_store_ids: ["vs_legacy"] },
          ],
        },
      }],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce(payload);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    fireEvent.click(await screen.findByRole("button", { name: /^OpenAI https:/ }));
    const searchSwitch = screen.getByRole("switch", { name: "OpenAI web search" });
    expect(searchSwitch).toHaveAttribute("aria-checked", "true");
    fireEvent.click(searchSwitch);
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));

    await waitFor(() => {
      const updateCall = requestMutationMock.mock.calls.find(
        ([action]) => action === "settings.provider.update",
      );
      expect(updateCall).toBeTruthy();
      const values = updateCall?.[1] as { extraBody: string };
      expect(JSON.parse(values.extraBody)).toEqual({
        metadata: { owner: "legacy-config" },
        tools: [{ type: "file_search", vector_store_ids: ["vs_legacy"] }],
      });
    });
  });

  it("creates a custom provider with folded advanced request settings", async () => {
    const base = settingsPayload();
    let payload: SettingsPayload = {
      ...base,
      providers: [
        {
          name: "deepseek",
          label: "DeepSeek",
          configured: true,
          api_key_required: true,
          api_key_hint: "deep••••test",
          api_base: "https://api.deepseek.com",
        },
        {
          name: "openrouter",
          label: "OpenRouter",
          configured: false,
          api_key_required: true,
          api_key_hint: null,
          api_base: null,
          default_api_base: "https://openrouter.ai/api/v1",
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementationOnce(async (
      _action: string,
      values: Record<string, string>,
    ) => {
        payload = {
          ...payload,
          created_provider: "custom-company-gateway",
          providers: [
            ...payload.providers,
            {
              name: "custom-company-gateway",
              label: values.name,
              is_custom: true,
              configured: true,
              api_key_required: false,
              api_key_hint: "sk-c••••pany",
              api_base: values.apiBase,
              default_api_base: null,
              advanced_fields: [
                "extra_headers",
                "extra_body",
                "extra_query",
                "proxy",
                "thinking_style",
              ],
              extra_headers: JSON.parse(values.extraHeaders),
              extra_body: JSON.parse(values.extraBody),
              extra_query: JSON.parse(values.extraQuery),
              proxy: values.proxy,
              thinking_style: values.thinkingStyle,
            },
          ],
        };
        return payload;
    });

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    fireEvent.pointerDown(
      screen.getByRole("button", { name: "Add your own model provider" }),
    );
    const customOption = await screen.findByRole("menuitem", { name: "Custom provider" });
    const openRouterOption = screen.getByRole("menuitem", { name: "OpenRouter" });
    expect(customOption.querySelector("svg, img")).not.toBeNull();
    expect(openRouterOption.querySelector("svg, img")).not.toBeNull();
    fireEvent.click(customOption);

    expect(
      screen.queryByRole("button", { name: "Add your own model provider" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Extra headers")).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("My model provider"), {
      target: { value: "Company Gateway" },
    });
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "https://gateway.example/v1" },
    });
    fireEvent.change(screen.getByPlaceholderText("Enter API key"), {
      target: { value: "sk-company" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Advanced options" }));
    fireEvent.change(screen.getByLabelText("Extra headers"), {
      target: { value: '{"X-Tenant":"engineering"}' },
    });
    fireEvent.change(screen.getByLabelText("Extra body"), {
      target: { value: '{"service_tier":"priority"}' },
    });
    fireEvent.change(screen.getByLabelText("Extra query"), {
      target: { value: '{"api-version":"2026-01-01"}' },
    });
    fireEvent.change(screen.getByLabelText("Network proxy"), {
      target: { value: "http://127.0.0.1:7890" },
    });
    fireEvent.pointerDown(screen.getByRole("button", { name: "Thinking style" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "enable_thinking" }));
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));

    await waitFor(() => {
      const createCall = requestMutationMock.mock.calls.find(
        ([action]) => action === "settings.provider.create",
      );
      expect(createCall).toBeTruthy();
      expect(createCall?.[1]).toEqual({
        name: "Company Gateway",
        apiKey: "sk-company",
        apiBase: "https://gateway.example/v1",
        proxy: "http://127.0.0.1:7890",
        extraHeaders: '{"X-Tenant":"engineering"}',
        extraBody: '{"service_tier":"priority"}',
        extraQuery: '{"api-version":"2026-01-01"}',
        thinkingStyle: "enable_thinking",
      });
    });
    expect(
      await screen.findByRole("button", { name: /Company Gateway/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add your own model provider" }),
    ).toBeInTheDocument();
  });
});
