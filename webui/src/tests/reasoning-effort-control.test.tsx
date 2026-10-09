import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ReasoningEffortControl } from "@/components/settings/models/ReasoningEffortControl";
import type { ProviderModelsPayload, SettingsPayload } from "@/lib/types";
import { installSettingsViewTestHooks, jsonResponse, settingsPayload } from "@/tests/settings-test-utils";

function hybridSettings(overrides: Partial<SettingsPayload["providers"][number]> = {}): SettingsPayload {
  return {
    ...settingsPayload(),
    providers: [{
      name: "openai_codex",
      label: "OpenAI Codex",
      configured: true,
      auth_type: "oauth",
      model_catalog: "hybrid",
      oauth_login_supported: true,
      ...overrides,
    }],
  };
}

function preset(overrides: Partial<SettingsPayload["model_presets"][number]> = {}) {
  return {
    ...settingsPayload().model_presets[0],
    model: "openai-codex/gpt-5.5",
    provider: "openai_codex",
    resolved_provider: "openai_codex",
    ...overrides,
  };
}

function catalogPayload(
  overrides: Partial<ProviderModelsPayload> = {},
  models: ProviderModelsPayload["models"] = [{
    id: "openai-codex/gpt-5.5",
    reasoning_efforts: ["low", "high", "xhigh"],
    reasoning_efforts_from_provider: true,
  }],
): ProviderModelsPayload {
  return {
    provider: "openai_codex",
    label: "OpenAI Codex",
    status: "available",
    catalog_kind: "hybrid",
    source: "remote",
    error_kind: null,
    models,
    model_count: models.length,
    ...overrides,
  };
}

function renderControl(options: {
  settings?: SettingsPayload;
  selectedPreset?: ReturnType<typeof preset> | null;
  provider?: string;
  model?: string;
  value?: string;
  onChange?: (value: string) => void;
  onProviderOAuthLogin?: (provider: string) => void;
} = {}) {
  const onChange = options.onChange ?? vi.fn();
  const view = render(
    <ReasoningEffortControl
      token="tok"
      settings={options.settings ?? hybridSettings()}
      selectedPreset={options.selectedPreset === undefined ? preset() : options.selectedPreset}
      provider={options.provider ?? "openai_codex"}
      model={options.model ?? "openai-codex/gpt-5.5"}
      value={options.value ?? ""}
      onProviderOAuthLogin={options.onProviderOAuthLogin}
      onChange={onChange}
    />,
  );
  return { ...view, onChange };
}

async function openSelect() {
  fireEvent.keyDown(screen.getByRole("combobox", { name: "Reasoning effort" }), {
    key: "ArrowDown",
  });
}

describe("ReasoningEffortControl", () => {
  installSettingsViewTestHooks();

  it("offers live provider-reported levels and selects one", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(catalogPayload()));
    vi.stubGlobal("fetch", fetchMock);
    const { onChange } = renderControl();

    expect(await screen.findByText("Levels reported by the provider for this model."))
      .toBeInTheDocument();
    await openSelect();
    fireEvent.click(await screen.findByRole("option", { name: "xhigh" }));
    expect(onChange).toHaveBeenCalledWith("xhigh");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/provider-models?provider=openai_codex",
      expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
    );
  });

  it.each([
    ["remote", false, "Built-in suggestions; not confirmed by the provider."],
    ["cache", true, "Levels reported by the provider (cached)."],
    ["stale", true, "Last provider-reported levels; may be out of date."],
    ["fallback", true, "Last provider-reported levels; may be out of date."],
    ["fallback", false, "Built-in suggestions; not confirmed by the provider."],
  ] as const)("labels %s catalog rows with provenance=%s accurately", async (source, provenance, note) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload(
      { source },
      [{ id: "openai-codex/gpt-5.5", reasoning_efforts: ["low", "high"], reasoning_efforts_from_provider: provenance }],
    ))));
    renderControl();
    expect(await screen.findByText(note)).toBeInTheDocument();
  });

  it("maps Default to an empty string", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    const { onChange } = renderControl({ value: "high" });
    await screen.findByText("Levels reported by the provider for this model.");
    await openSelect();
    fireEvent.click(await screen.findByRole("option", { name: "Default" }));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("keeps a nonlisted saved value as editable custom text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    const { onChange } = renderControl({ value: "xhigh-custom" });

    const input = await screen.findByRole("textbox", { name: "Custom" });
    expect(input).toHaveValue("xhigh-custom");
    expect(screen.getByText(/is not a listed level/)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "ultra" } });
    expect(onChange).toHaveBeenCalledWith("ultra");
  });

  it("selecting Custom alone does not mutate the value", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    const { onChange } = renderControl({ value: "high" });
    await screen.findByText("Levels reported by the provider for this model.");
    await openSelect();
    fireEvent.click(await screen.findByRole("option", { name: "Custom" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("high");
  });

  it("uses preset suggestion values when catalog metadata is missing", async () => {
    const fetchMock = vi.fn(async () => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    renderControl({
      settings: settingsPayload(),
      provider: "auto",
      model: "openai/gpt-4o",
      selectedPreset: preset({
        model: "openai/gpt-4o",
        provider: "auto",
        resolved_provider: "openai",
        reasoning_effort_values: ["", "minimal", "medium"],
      }),
    });

    expect(await screen.findByText("Suggested for this provider; not confirmed for this model."))
      .toBeInTheDocument();
    await openSelect();
    expect(await screen.findByRole("option", { name: "minimal" })).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("falls back to generic suggestions for unknown models", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Promise<Response>(() => {})));
    renderControl({
      settings: settingsPayload(),
      provider: "auto",
      model: "openai/gpt-4o",
      selectedPreset: preset({
        model: "openai/gpt-4o",
        provider: "auto",
        resolved_provider: "openai",
      }),
    });

    expect(await screen.findByText("Generic suggestions; supported levels for this model are unknown."))
      .toBeInTheDocument();
    await openSelect();
    for (const effort of ["low", "medium", "high"]) {
      expect(await screen.findByRole("option", { name: effort })).toBeVisible();
    }
  });

  it("matches catalog rows by wire id for unprefixed model values", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    renderControl({ model: "gpt-5.5" });
    expect(await screen.findByText("Levels reported by the provider for this model."))
      .toBeInTheDocument();
    await openSelect();
    expect(await screen.findByRole("option", { name: "xhigh" })).toBeVisible();
  });

  it("keeps the saved value and reports a failed discovery", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }) as Response));
    const { onChange } = renderControl({ value: "xhigh" });
    expect(await screen.findByText("Could not load model levels.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("xhigh");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("explains auth rejection without presenting levels as confirmed", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload(
      { source: "fallback", error_kind: "auth_required" },
    ))));
    const login = vi.fn();
    const { onChange } = renderControl({ value: "xhigh-custom", onProviderOAuthLogin: login });

    expect(await screen.findByText(/Sign in to load this provider’s model levels/))
      .toBeInTheDocument();
    expect(screen.queryByText(/Built-in suggestions/)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("xhigh-custom");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(login).toHaveBeenCalledWith("openai_codex");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("ignores an obsolete response after the provider changes", async () => {
    let finishOld!: (response: Response) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce(jsonResponse(catalogPayload()));
    vi.stubGlobal("fetch", fetchMock);
    const settingsA = hybridSettings();
    const settingsB: SettingsPayload = {
      ...settingsPayload(),
      providers: [{
        name: "xai_grok",
        label: "xAI Grok",
        configured: true,
        auth_type: "oauth",
        model_catalog: "hybrid",
      }],
    };
    const props = {
      token: "tok",
      model: "openai-codex/gpt-5.5",
      value: "",
      onChange: vi.fn(),
    };
    const view = render(
      <ReasoningEffortControl
        {...props}
        settings={settingsA}
        selectedPreset={preset()}
        provider="openai_codex"
      />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    view.rerender(
      <ReasoningEffortControl
        {...props}
        settings={settingsB}
        selectedPreset={preset({ provider: "xai_grok", resolved_provider: "xai_grok" })}
        provider="xai_grok"
      />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await act(async () => { finishOld(jsonResponse(catalogPayload())); });
    expect(screen.queryByText("Levels reported by the provider for this model."))
      .not.toBeInTheDocument();
    expect(props.onChange).not.toHaveBeenCalled();
  });

  it("drops previous options when the model changes and keeps the saved value", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    const onChange = vi.fn();
    const view = render(
      <ReasoningEffortControl
        token="tok"
        settings={hybridSettings()}
        selectedPreset={preset()}
        provider="openai_codex"
        model="openai-codex/gpt-5.5"
        value="saved-effort"
        onChange={onChange}
      />,
    );
    await screen.findByText("Levels reported by the provider for this model.");

    view.rerender(
      <ReasoningEffortControl
        token="tok"
        settings={hybridSettings()}
        selectedPreset={preset()}
        provider="openai_codex"
        model="openai-codex/other-model"
        value="saved-effort"
        onChange={onChange}
      />,
    );

    expect(await screen.findByText(
      "Generic suggestions; supported levels for this model are unknown.",
    )).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("saved-effort");
    await openSelect();
    expect(screen.queryByRole("option", { name: "xhigh" })).not.toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "medium" })).toBeVisible();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("drops previous options when the provider changes and keeps the saved value", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings/provider-models?provider=openai_codex") {
        return jsonResponse(catalogPayload());
      }
      if (url === "/api/settings/provider-models?provider=xai_grok") {
        return jsonResponse(catalogPayload(
          { provider: "xai_grok", label: "xAI Grok" },
          [{ id: "xai-grok/grok-4.5", reasoning_efforts: ["minimal", "max"], reasoning_efforts_from_provider: true }],
        ));
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const settingsB: SettingsPayload = {
      ...settingsPayload(),
      providers: [{
        name: "xai_grok",
        label: "xAI Grok",
        configured: true,
        auth_type: "oauth",
        model_catalog: "hybrid",
      }],
    };
    const onChange = vi.fn();
    const view = render(
      <ReasoningEffortControl
        token="tok"
        settings={hybridSettings()}
        selectedPreset={preset()}
        provider="openai_codex"
        model="openai-codex/gpt-5.5"
        value="saved-effort"
        onChange={onChange}
      />,
    );
    await screen.findByText("Levels reported by the provider for this model.");

    view.rerender(
      <ReasoningEffortControl
        token="tok"
        settings={settingsB}
        selectedPreset={preset({ provider: "xai_grok", resolved_provider: "xai_grok", model: "xai-grok/grok-4.5" })}
        provider="xai_grok"
        model="xai-grok/grok-4.5"
        value="saved-effort"
        onChange={onChange}
      />,
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/provider-models?provider=xai_grok",
        expect.anything(),
      ),
    );
    await screen.findByText("Levels reported by the provider for this model.");
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("saved-effort");
    await openSelect();
    expect(await screen.findByRole("option", { name: "minimal" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "xhigh" })).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("ignores preset suggestions when the draft model or provider differs", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload(
      {},
      [{ id: "openai-codex/unrelated", reasoning_efforts: ["ultra"], reasoning_efforts_from_provider: true }],
    ))));
    const suggestionPreset = preset({
      model: "openai-codex/gpt-5.5",
      provider: "openai_codex",
      reasoning_effort_values: ["", "minimal", "minimal", "max"],
    });
    const onChange = vi.fn();
    const props = {
      token: "tok",
      settings: hybridSettings(),
      provider: "openai_codex",
      model: "openai-codex/gpt-5.5",
      value: "",
      onChange,
    };
    const view = render(
      <ReasoningEffortControl {...props} selectedPreset={suggestionPreset} />,
    );
    expect(await screen.findByText("Suggested for this provider; not confirmed for this model."))
      .toBeInTheDocument();
    await openSelect();
    expect(await screen.findByRole("option", { name: "minimal" })).toBeVisible();
    expect(screen.getAllByRole("option", { name: "minimal" })).toHaveLength(1);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });

    view.rerender(
      <ReasoningEffortControl
        {...props}
        model="openai-codex/other-model"
        selectedPreset={suggestionPreset}
      />,
    );
    expect(await screen.findByText(
      "Generic suggestions; supported levels for this model are unknown.",
    )).toBeInTheDocument();

    view.rerender(
      <ReasoningEffortControl
        {...props}
        model="openai-codex/gpt-5.5"
        selectedPreset={{ ...suggestionPreset, resolved_provider: "anthropic" }}
      />,
    );
    expect(await screen.findByText(
      "Generic suggestions; supported levels for this model are unknown.",
    )).toBeInTheDocument();
    expect(screen.queryByText("Suggested for this provider; not confirmed for this model."))
      .not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("refetches and clears the auth note after the provider row is replaced by sign-in", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(catalogPayload(
        { source: "fallback", error_kind: "auth_required" },
      )))
      .mockResolvedValueOnce(jsonResponse(catalogPayload()));
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();
    const login = vi.fn();
    const props = {
      token: "tok",
      provider: "openai_codex",
      model: "openai-codex/gpt-5.5",
      value: "xhigh-custom",
      onProviderOAuthLogin: login,
      onChange,
    };
    const view = render(
      <ReasoningEffortControl {...props} settings={hybridSettings()} selectedPreset={preset()} />,
    );
    expect(await screen.findByText(/Sign in to load this provider’s model levels/))
      .toBeInTheDocument();

    view.rerender(
      <ReasoningEffortControl {...props} settings={hybridSettings()} selectedPreset={preset()} />,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Levels reported by the provider for this model."))
      .toBeInTheDocument();
    expect(screen.queryByText(/Sign in to load this provider’s model levels/))
      .not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("xhigh-custom");
    expect(onChange).not.toHaveBeenCalled();
    expect(login).not.toHaveBeenCalled();
  });

  it("keeps the custom input focused while typing through a listed value", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    const settings = hybridSettings();
    const selectedPreset = preset();
    function Harness() {
      const [v, setV] = useState("saved-unknown");
      return (
        <ReasoningEffortControl
          token="tok"
          settings={settings}
          selectedPreset={selectedPreset}
          provider="openai_codex"
          model="openai-codex/gpt-5.5"
          value={v}
          onChange={setV}
        />
      );
    }
    render(<Harness />);
    await screen.findByText("Levels reported by the provider for this model.");

    const input = await screen.findByRole("textbox", { name: "Custom" });
    act(() => input.focus());
    fireEvent.change(input, { target: { value: "high" } });

    const listed = screen.getByRole("textbox", { name: "Custom" });
    expect(listed).toHaveValue("high");
    expect(listed).toHaveFocus();
    fireEvent.change(listed, { target: { value: "high-custom" } });
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("high-custom");
  });

  it("keeps a focused unknown value editable when the catalog later lists it", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const settings = hybridSettings();
    const selectedPreset = preset();
    function Harness() {
      const [v, setV] = useState("xhigh");
      return (
        <ReasoningEffortControl
          token="tok"
          settings={settings}
          selectedPreset={selectedPreset}
          provider="openai_codex"
          model="openai-codex/gpt-5.5"
          value={v}
          onChange={setV}
        />
      );
    }
    render(<Harness />);
    const input = await screen.findByRole("textbox", { name: "Custom" });
    act(() => input.focus());
    await act(async () => { finish(jsonResponse(catalogPayload())); });
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("xhigh");
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveFocus();
  });

  it("closes custom editing after an explicit listed choice", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    const { onChange } = renderControl({ value: "high" });
    await screen.findByText("Levels reported by the provider for this model.");
    await openSelect();
    fireEvent.click(await screen.findByRole("option", { name: "Custom" }));
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("high");

    await openSelect();
    fireEvent.click(await screen.findByRole("option", { name: "low" }));
    expect(onChange).toHaveBeenCalledWith("low");
    expect(screen.queryByRole("textbox", { name: "Custom" })).not.toBeInTheDocument();
  });

  it("treats an empty-only suggestion list as default-only", async () => {
    const fetchMock = vi.fn(async () => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    const settings: SettingsPayload = {
      ...settingsPayload(),
      providers: [{ name: "mistral", label: "Mistral", configured: true }],
    };
    renderControl({
      settings,
      provider: "mistral",
      model: "magistral-medium",
      value: "saved-effort",
      selectedPreset: preset({
        provider: "mistral",
        resolved_provider: "mistral",
        model: "magistral-medium",
        reasoning_effort_values: ["", ""],
      }),
    });

    expect(await screen.findByText(
      "This model uses automatic reasoning; no effort levels are configurable.",
    )).toBeInTheDocument();
    await openSelect();
    expect(await screen.findByRole("option", { name: "Default" })).toBeVisible();
    expect(await screen.findByRole("option", { name: "Custom" })).toBeVisible();
    for (const effort of ["low", "medium", "high"]) {
      expect(screen.queryByRole("option", { name: effort })).not.toBeInTheDocument();
    }
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.getByRole("textbox", { name: "Custom" })).toHaveValue("saved-effort");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["openai_codex", "openai_codex/gpt-5.5"],
    ["openai_codex", "gpt-5.5"],
  ] as const)("matches codex catalog rows through the %s alias %s", async (provider, model) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    renderControl({ provider, model, selectedPreset: preset({ model }) });
    expect(await screen.findByText("Levels reported by the provider for this model."))
      .toBeInTheDocument();
  });

  it.each(["xai_grok", "github_copilot"] as const)(
    "labels remote %s levels as provider-reported", async (provider) => {
      const idPrefix = provider === "xai_grok" ? "xai-grok" : "github-copilot";
      const settings: SettingsPayload = {
        ...settingsPayload(),
        providers: [{
          name: provider,
          label: provider,
          configured: true,
          auth_type: "oauth",
          model_catalog: "hybrid",
        }],
      };
      vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload(
        { provider, label: provider },
        [{
          id: `${idPrefix}/remote-model`,
          reasoning_efforts: ["low", "max"],
          reasoning_efforts_from_provider: true,
        }],
      ))));
      renderControl({
        settings,
        provider,
        model: `${provider}/remote-model`,
        selectedPreset: preset({ provider, resolved_provider: provider, model: `${idPrefix}/remote-model` }),
      });
      expect(await screen.findByText("Levels reported by the provider for this model."))
        .toBeInTheDocument();
      await openSelect();
      expect(await screen.findByRole("option", { name: "max" })).toBeVisible();
    },
  );

  it("does not match a foreign provider prefix sharing the same leaf id", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(catalogPayload())));
    renderControl({
      provider: "openai_codex",
      model: "openai/gpt-5.5",
      selectedPreset: preset(),
    });
    expect(await screen.findByText(
      "Generic suggestions; supported levels for this model are unknown.",
    )).toBeInTheDocument();
    await openSelect();
    expect(screen.queryByRole("option", { name: "xhigh" })).not.toBeInTheDocument();
  });

  it("does not mutate the value while discovery is loading", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    const { onChange } = renderControl({ value: "xhigh" });
    expect(await screen.findByText("Loading model levels...")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not fetch catalogs for non-hybrid providers", async () => {
    const fetchMock = vi.fn(async () => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    renderControl({
      settings: {
        ...settingsPayload(),
        providers: [{ name: "deepseek", label: "DeepSeek", configured: true }],
      },
      provider: "deepseek",
      selectedPreset: preset({ provider: "deepseek", resolved_provider: "deepseek" }),
    });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Reasoning effort" })).toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("provider-models"))).toHaveLength(0);
  });
});
