import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { SettingsPayload } from "@/lib/types";
import { requestMutationMock, jsonResponse, settingsPayload, renderSettingsView, installSettingsViewTestHooks } from "@/tests/settings-test-utils";


async function chooseProviderToConfigure(label: string) {
  fireEvent.click(
    await screen.findByRole("button", { name: "Add provider" }),
  );
  fireEvent.click(await screen.findByRole("option", { name: label }));
}

describe("Settings providers", () => {
  installSettingsViewTestHooks();

  it("searches provider aliases and configures in the same dialog without adding an unsaved row", async () => {
    const user = userEvent.setup();
    const payload = settingsPayload();
    payload.providers = [
      { name: "deepseek", label: "DeepSeek", configured: true },
      { name: "volcengine", label: "VolcEngine", configured: false },
      { name: "volcengine_coding_plan", label: "VolcEngine Coding Plan", configured: false },
    ];
    renderSettingsView({ initialSection: "models", initialSettings: payload });
    const trigger = screen.getByRole("button", { name: "Add provider" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Add provider" });
    const search = within(dialog).getByRole("combobox", { name: "Search providers" });
    await waitFor(() => expect(search).toHaveFocus());
    expect(within(dialog).queryByRole("option", { name: "DeepSeek" })).not.toBeInTheDocument();
    await user.type(search, "火山");
    expect(within(dialog).getAllByRole("option")).toHaveLength(2);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(screen.getByRole("dialog", { name: "VolcEngine Coding Plan" })).toBe(dialog);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(within(dialog).getByLabelText("API key", { selector: "input" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "VolcEngine Coding Plan" })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Back to providers" }));
    expect(screen.getByRole("dialog", { name: "Add provider" })).toBe(dialog);
    expect(screen.getByRole("combobox")).toHaveValue("火山");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("keeps custom provider creation available for empty searches and discards cancelled drafts", async () => {
    const user = userEvent.setup();
    renderSettingsView({ initialSection: "models", initialSettings: settingsPayload() });
    await user.click(screen.getByRole("button", { name: "Add provider" }));
    await user.type(screen.getByRole("combobox"), "does-not-exist");
    expect(screen.getByRole("status")).toHaveTextContent("No providers match this search.");
    await user.click(screen.getByRole("button", { name: "Custom provider", exact: true }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await user.type(screen.getByPlaceholderText("My model provider"), "Unsaved gateway");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Add provider" }));
    expect(screen.getByRole("combobox")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Custom provider", exact: true }));
    expect(screen.getByPlaceholderText("My model provider")).toHaveValue("");
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("uses a bottom sheet on mobile without opening the keyboard immediately", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: query === "(max-width: 639px)", media: query,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
    renderSettingsView({ initialSection: "models", initialSettings: settingsPayload() });
    fireEvent.click(screen.getByRole("button", { name: "Add provider" }));
    const dialog = screen.getByRole("dialog", { name: "Add provider" });
    expect(dialog).toHaveClass("rounded-t-3xl", "bottom-0");
    expect(screen.getByRole("combobox")).not.toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Custom provider", exact: true }));
    expect(screen.getByRole("dialog", { name: "Custom provider" })).toBe(dialog);
  });

  it("adds a built-in provider only after saving and returns focus to Add", async () => {
    const user = userEvent.setup();
    const payload = settingsPayload();
    payload.providers = [{ name: "moonshot", label: "Moonshot", configured: false }];
    requestMutationMock.mockResolvedValueOnce({
      ...payload, providers: [{ ...payload.providers[0], configured: true, api_key_hint: "configured" }],
    });
    renderSettingsView({ initialSection: "models", initialSettings: payload });
    const trigger = screen.getByRole("button", { name: "Add provider" });
    await user.click(trigger);
    await user.click(screen.getByRole("option", { name: "Moonshot" }));
    await user.type(screen.getByPlaceholderText("Enter API key"), "test-key");
    await user.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Moonshot", exact: true })).toBeInTheDocument();
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    expect(screen.queryByRole("option", { name: "Moonshot" })).not.toBeInTheDocument();
  });

  it.each([false, true])("retains the add-provider draft after a failed save (custom: %s)", async (custom) => {
    const user = userEvent.setup();
    const payload = settingsPayload();
    payload.providers = [{ name: "moonshot", label: "Moonshot", configured: false }];
    requestMutationMock.mockRejectedValueOnce(new Error("Provider could not be saved"));
    renderSettingsView({ initialSection: "models", initialSettings: payload });
    await user.click(screen.getByRole("button", { name: "Add provider" }));
    await user.click(custom
      ? screen.getByRole("button", { name: "Custom provider", exact: true })
      : screen.getByRole("option", { name: "Moonshot" }));
    const dialog = screen.getByRole("dialog");
    if (custom) {
      await user.type(screen.getByPlaceholderText("My model provider"), "Company gateway");
      await user.type(screen.getByPlaceholderText("https://api.example.com/v1"), "https://gateway.example/v1");
    }
    await user.type(screen.getByPlaceholderText("Enter API key"), "test-key");
    await user.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Save provider" })).toBeEnabled());
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(within(dialog).getByPlaceholderText("Enter API key")).toHaveValue("test-key");
    await user.click(within(dialog).getByRole("button", { name: "Back to providers" }));
    expect(screen.getByRole("dialog", { name: "Add provider" })).toBe(dialog);
    await user.click(custom
      ? screen.getByRole("button", { name: "Custom provider", exact: true })
      : screen.getByRole("option", { name: "Moonshot" }));
    expect(screen.getByPlaceholderText("Enter API key")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Moonshot", exact: true })).not.toBeInTheDocument();
  });

  it("keeps provider labels and keyboard configuration accessible with decorative logos", async () => {
    const user = userEvent.setup();
    const payload: SettingsPayload = {
      ...settingsPayload(),
      providers: [{
        name: "openai_codex",
        label: "OpenAI Codex",
        configured: true,
        auth_type: "oauth",
        api_key_required: false,
        api_key_hint: null,
        api_base: null,
        model_catalog: "builtin",
        oauth_account: "test-account",
        oauth_login_supported: true,
      }],
    };
    renderSettingsView({ initialSection: "models", initialSettings: payload });

    const provider = await screen.findByRole("button", { name: "OpenAI Codex", exact: true });
    expect(within(provider).getByText("Configure")).toBeInTheDocument();
    expect(within(provider).queryByRole("img")).not.toBeInTheDocument();
    provider.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "OpenAI Codex" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(provider).toHaveFocus();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });


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
        "Complete sign-in in your browser. If nanobot does not connect automatically, paste the authorization code below.",
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
      const dialog = (await screen.findByText("Select Sign in to open xAI on your computer. After signing in, paste the authorization code shown by xAI below.")).closest('[role="dialog"]') as HTMLElement;

      expect(openMock).not.toHaveBeenCalled();
      expect(
        within(dialog).getByText(
          "Select Sign in to open xAI on your computer. After signing in, paste the authorization code shown by xAI below.",
        ),
      ).toBeInTheDocument();
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
    const dialog = (await screen.findByText("Complete sign-in in your browser. If nanobot does not connect automatically, copy the full localhost callback URL from the address bar and paste it below.")).closest('[role="dialog"]') as HTMLElement;

    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.provider.oauth_login",
      { provider: "openai_codex" },
      20_000,
    );
    expect(openMock).not.toHaveBeenCalled();
    expect(
      within(dialog).getByText(
        "Complete sign-in in your browser. If nanobot does not connect automatically, copy the full localhost callback URL from the address bar and paste it below.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Waiting for the browser callback…")).toBeInTheDocument();

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
      const dialog = (await screen.findByText("Open ChatGPT in this browser and finish signing in. When the localhost page fails to load, copy the full URL from the address bar and paste it below.")).closest('[role="dialog"]') as HTMLElement;

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

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
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

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
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

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: /^DeepSeek/ }));
    expect(screen.getByText(/DeepSeek V4 Flash/)).toBeInTheDocument();
    const deepSeekSearch = screen.getByRole("switch", { name: "DeepSeek web search" });
    expect(deepSeekSearch).toHaveAttribute("aria-checked", "true");
    fireEvent.click(deepSeekSearch);
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(
      screen.getByRole("button", { name: "DeepSeek", exact: true }),
    ).toBeVisible());

    fireEvent.click(screen.getByRole("button", { name: "OpenAI", exact: true }));
    fireEvent.click(screen.getByRole("switch", { name: "OpenAI web search" }));
    fireEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(
      screen.getByRole("button", { name: "OpenAI", exact: true }),
    ).toBeVisible());

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

    fireEvent.click(await screen.findByRole("button", { name: "OpenAI", exact: true }));
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

    fireEvent.click(
      screen.getByRole("button", { name: "Add provider" }),
    );
    const customOption = await screen.findByRole("button", { name: "Custom provider" });
    const openRouterOption = screen.getByRole("option", { name: "OpenRouter" });
    expect(customOption.querySelector("svg, img")).not.toBeNull();
    expect(openRouterOption.querySelector("svg, img")).not.toBeNull();
    fireEvent.click(customOption);

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
    for (const [title, value] of [
      ["Extra headers", '{"X-Tenant":"engineering"}'],
      ["Additional body parameters", '{"service_tier":"priority"}'],
      ["Additional query parameters", '{"api-version":"2026-01-01"}'],
    ]) {
      fireEvent.click(screen.getByRole("button", { name: title }));
      const editor = screen.getByRole("dialog", { name: title });
      fireEvent.change(within(editor).getByRole("textbox", { name: title }), { target: { value } });
      fireEvent.click(within(editor).getByRole("button", { name: "Save", exact: true }));
      await waitFor(() => expect(screen.queryByRole("dialog", { name: title })).not.toBeInTheDocument());
    }
    fireEvent.change(screen.getByLabelText("Network proxy"), {
      target: { value: "http://127.0.0.1:7890" },
    });
    fireEvent.pointerDown(screen.getByRole("button", { name: "Reasoning parameter format" }));
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
      screen.getByRole("button", { name: "Add provider" }),
    ).toBeInTheDocument();
  });
});
