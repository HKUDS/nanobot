import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SettingsPayload } from "@/lib/types";
import { requestMutationMock, jsonResponse, settingsPayload, renderSettingsView, openPopover, installSettingsViewTestHooks } from "@/tests/settings-test-utils";


function settingsPayloadWithBackup(): {
  payload: SettingsPayload;
  backupPreset: SettingsPayload["model_presets"][number];
} {
  const base = settingsPayload();
  const backupPreset = {
    ...base.model_presets[0],
    name: "backup",
    label: "Backup",
    active: false,
    model: "anthropic/claude-sonnet-4",
    provider: "anthropic",
    resolved_provider: "anthropic",
  };
  return {
    backupPreset,
    payload: {
      ...base,
      model_presets: [base.model_presets[0], backupPreset],
      model_call_order: ["primary", "backup"],
      providers: [
        {
          name: "openai",
          label: "OpenAI",
          configured: true,
        },
        {
          name: "anthropic",
          label: "Anthropic",
          configured: true,
        },
      ],
    },
  };
}

function autoDynamicProviderPayload(
  options: {
    configured: boolean;
    hasApiKey: boolean;
    apiBase: string | null;
    apiKeyHint: string | null;
  },
): SettingsPayload {
  const base = settingsPayload();
  return {
    ...base,
    agent: {
      ...base.agent,
      model: "companyProxy/gpt-4o",
      provider: "companyProxy",
      resolved_provider: "companyProxy",
      has_api_key: options.hasApiKey,
    },
    model_presets: [
      {
        ...base.model_presets[0],
        model: "companyProxy/gpt-4o",
        provider: "auto",
        resolved_provider: "companyProxy",
      },
    ],
    providers: [
      {
        name: "companyProxy",
        label: "Company Proxy",
        configured: options.configured,
        auth_type: "api_key",
        api_key_required: false,
        api_key_hint: options.apiKeyHint,
        api_base: options.apiBase,
        default_api_base: null,
      },
    ],
  };
}

async function togglePresetEditor(name = "primary") {
  const row = await screen.findByTestId(`model-call-order-row-${name}`);
  fireEvent.click(within(row).getAllByRole("button")[0]);
}

describe("Settings models", () => {
  installSettingsViewTestHooks();

  it("uses the preset name as the canonical identity", async () => {
    const payload = settingsPayload();
    payload.model_presets[0] = {
      ...payload.model_presets[0],
      name: "openai",
      label: "minimax",
    };
    payload.model_call_order = ["openai"];
    payload.agent.model_preset = "openai";
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await togglePresetEditor("openai");

    const editor = screen.getByTestId("model-preset-editor");
    expect(within(editor).getByText("Preset name")).toBeInTheDocument();
    expect(within(editor).getByRole("textbox", { name: "Preset name" })).toHaveValue(
      "openai",
    );
    expect(within(editor).queryByText("minimax")).not.toBeInTheDocument();
  });

  it("edits a legacy case-conflicting preset without treating its own name as a rename", async () => {
    const payload = settingsPayload();
    const primary = {
      ...payload.model_presets[0],
      name: "Fast",
      label: "Fast",
      active: true,
    };
    const legacyConflict = {
      ...primary,
      name: "fast",
      label: "fast",
      active: false,
    };
    const legacyPayload: SettingsPayload = {
      ...payload,
      agent: { ...payload.agent, model_preset: "Fast" },
      model_presets: [primary, legacyConflict],
      model_call_order: ["Fast", "fast"],
    };
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    requestMutationMock.mockResolvedValueOnce(legacyPayload);

    renderSettingsView({ initialSection: "models", initialSettings: legacyPayload });
    await togglePresetEditor("Fast");
    fireEvent.click(screen.getByRole("button", { name: /Advanced options/ }));
    fireEvent.change(screen.getByLabelText("Temperature"), {
      target: { value: "0.4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.model_configuration.update",
        { name: "Fast", temperature: 0.4 },
        20_000,
      );
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renames an existing preset without losing the editor selection", async () => {
    const payload = settingsPayload();
    const renamedPayload: SettingsPayload = {
      ...payload,
      agent: { ...payload.agent, model_preset: "Codex" },
      model_presets: payload.model_presets.map((preset) => ({
        ...preset,
        name: "Codex",
        label: "Codex",
      })),
      model_call_order: ["Codex"],
    };
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    requestMutationMock.mockResolvedValueOnce(renamedPayload);

    renderSettingsView({ initialSection: "models", initialSettings: payload });
    await togglePresetEditor();

    const nameInput = screen.getByRole("textbox", { name: "Preset name" });
    fireEvent.change(nameInput, { target: { value: "Codex" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.model_configuration.update",
        { name: "primary", new_name: "Codex" },
        20_000,
      );
    });
    expect(await screen.findByTestId("model-call-order-row-Codex")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Preset name" })).toHaveValue("Codex");
  });

  it("maps a server-side name conflict back to the preset name field", async () => {
    const payload = settingsPayload();
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    requestMutationMock.mockRejectedValueOnce({ status: 409 });

    renderSettingsView({ initialSection: "models", initialSettings: payload });
    await togglePresetEditor();

    const nameInput = screen.getByRole("textbox", { name: "Preset name" });
    fireEvent.change(nameInput, { target: { value: "Codex" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A preset with this name already exists.",
    );
    expect(nameInput).toHaveAttribute("aria-invalid", "true");
    expect(nameInput).toHaveFocus();
  });

  it("keeps generation parameters collapsed until advanced options are opened", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "models" });

    expect(screen.queryByText("Edit preset")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Advanced options/ })).not.toBeInTheDocument();
    await togglePresetEditor();
    const advanced = await screen.findByRole("button", { name: /Advanced options/ });
    expect(screen.queryByText("Context window")).not.toBeInTheDocument();
    expect(screen.queryByText("Temperature")).not.toBeInTheDocument();

    fireEvent.click(advanced);

    expect(await screen.findByText("Context window")).toBeInTheDocument();
    expect(screen.getByText("Temperature")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "64K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "200K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "256K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "500K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1M" })).toBeInTheDocument();
    const reasoningEffort = screen.getByLabelText("Reasoning effort");
    expect(reasoningEffort).toHaveProperty("type", "text");
    fireEvent.change(reasoningEffort, { target: { value: "provider-native-mode" } });
    expect(reasoningEffort).toHaveValue("provider-native-mode");
  });

  it("expands the model preset editor directly below the selected row", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "models" });

    const row = await screen.findByTestId("model-call-order-row-primary");
    const trigger = within(row).getAllByRole("button")[0];
    expect(screen.queryByTestId("model-preset-editor")).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);

    const editor = screen.getByTestId("model-preset-editor");
    expect(trigger).toHaveAttribute("aria-pressed", "true");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", "model-preset-editor");
    expect(row.parentElement).toHaveAttribute("role", "listitem");
    expect(row.parentElement?.parentElement).toHaveAttribute("role", "list");
    expect(row.nextElementSibling).toBe(editor);
    expect(editor).toHaveClass(
      "slide-in-from-top-1",
      "lg:max-w-6xl",
      "rounded-floating",
    );
    expect(within(editor).getByRole("textbox", { name: "Preset name" })).toHaveValue(
      "primary",
    );
    const deleteButton = within(editor).getByRole("button", { name: "Delete" });
    expect(deleteButton).toBeDisabled();
    expect(deleteButton).toHaveAttribute("aria-describedby", "model-preset-delete-hint");
    expect(
      within(editor).getByText("Remove this preset from the call order before deleting it."),
    ).toBeInTheDocument();

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("model-preset-editor")).not.toBeInTheDocument();
  });

  it("drags model presets to reorder and saves the model call order immediately", async () => {
    const { payload, backupPreset } = settingsPayloadWithBackup();
    const updatedPayload: SettingsPayload = {
      ...payload,
      agent: {
        ...payload.agent,
        model: backupPreset.model,
        provider: backupPreset.provider,
        resolved_provider: backupPreset.resolved_provider,
        model_preset: backupPreset.name,
      },
      model_presets: payload.model_presets.map((preset) => ({
        ...preset,
        active: preset.name === backupPreset.name,
      })),
      model_call_order: ["backup", "primary"],
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
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce(updatedPayload);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    await togglePresetEditor();
    fireEvent.click(screen.getByRole("button", { name: /Advanced options/ }));
    fireEvent.change(screen.getByLabelText("Temperature"), {
      target: { value: "0.4" },
    });
    const primaryRow = screen.getByTestId("model-call-order-row-primary");
    const backupRow = screen.getByTestId("model-call-order-row-backup");
    expect(backupRow).toHaveAttribute("draggable", "true");
    expect(screen.queryByRole("button", { name: "Move up" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move down" })).not.toBeInTheDocument();
    const dataTransfer = {
      dropEffect: "move",
      effectAllowed: "move",
      setData: vi.fn(),
    };
    fireEvent.dragStart(backupRow, { dataTransfer });
    fireEvent.dragEnter(primaryRow, { dataTransfer });
    fireEvent.drop(primaryRow, { dataTransfer });

    await waitFor(() => {
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.model_call_order.update",
        { order: ["backup", "primary"] },
        20_000,
      );
    });

    expect(screen.queryByRole("button", { name: "Save order" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Temperature")).toHaveValue(0.4);
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("keeps repeated fallback preset rows stable when changing the primary preset", async () => {
    const { payload, backupPreset } = settingsPayloadWithBackup();
    const initialPayload: SettingsPayload = {
      ...payload,
      agent: {
        ...payload.agent,
        model: backupPreset.model,
        provider: backupPreset.provider,
        resolved_provider: backupPreset.resolved_provider,
        model_preset: backupPreset.name,
      },
      model_presets: payload.model_presets.map((preset) => ({
        ...preset,
        active: preset.name === backupPreset.name,
      })),
      model_call_order: ["backup", "primary", "backup"],
    };
    const updatedPayload: SettingsPayload = {
      ...initialPayload,
      agent: {
        ...payload.agent,
        model_preset: "primary",
      },
      model_presets: payload.model_presets.map((preset) => ({
        ...preset,
        active: preset.name === "primary",
      })),
      model_call_order: ["primary", "backup", "backup"],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(initialPayload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce(updatedPayload);

    renderSettingsView({ initialSection: "models", initialSettings: initialPayload });

    const primaryRow = screen.getByTestId("model-call-order-row-primary");
    const backupRows = screen.getAllByTestId("model-call-order-row-backup");
    const firstBackupRow = backupRows[0];
    const secondBackupRow = backupRows[1];
    const secondBackupTrigger = within(secondBackupRow).getAllByRole("button")[0];
    fireEvent.click(secondBackupTrigger);
    expect(screen.getAllByTestId("model-preset-editor")).toHaveLength(1);
    expect(secondBackupRow.nextElementSibling).toBe(
      screen.getByTestId("model-preset-editor"),
    );
    fireEvent.click(secondBackupTrigger);

    const dataTransfer = {
      dropEffect: "move",
      effectAllowed: "move",
      setData: vi.fn(),
    };
    fireEvent.dragStart(primaryRow, { dataTransfer });
    fireEvent.dragEnter(firstBackupRow, { dataTransfer });
    fireEvent.drop(firstBackupRow, { dataTransfer });

    await waitFor(() =>
      expect(
        screen
          .getAllByTestId(/^model-call-order-row-/)
          .map((row) => row.getAttribute("data-testid")),
      ).toEqual([
        "model-call-order-row-primary",
        "model-call-order-row-backup",
        "model-call-order-row-backup",
      ]),
    );
  });

  it("restores the model call order when immediate persistence fails", async () => {
    const { payload } = settingsPayloadWithBackup();
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
    requestMutationMock.mockRejectedValueOnce(new Error("Order update failed"));

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    fireEvent.keyDown(screen.getByTestId("model-call-order-row-backup"), {
      key: "ArrowUp",
    });

    expect(await screen.findByText("Order update failed")).toBeInTheDocument();
    expect(
      screen
        .getAllByTestId(/^model-call-order-row-/)
        .map((row) => row.getAttribute("data-testid")),
    ).toEqual([
      "model-call-order-row-primary",
      "model-call-order-row-backup",
    ]);
  });

  it("shows presets outside the call order in the unified list and adds them directly", async () => {
    const { payload } = settingsPayloadWithBackup();
    const codexPreset = {
      ...payload.model_presets[0],
      name: "codex",
      label: "Codex",
      active: false,
      model: "openai-codex/gpt-5.5",
      provider: "openai",
      resolved_provider: "openai",
    };
    const payloadWithCodex: SettingsPayload = {
      ...payload,
      model_presets: [...payload.model_presets, codexPreset],
    };
    const orderedPayload: SettingsPayload = {
      ...payloadWithCodex,
      model_call_order: ["primary", "backup", "codex"],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payloadWithCodex);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce(orderedPayload);

    renderSettingsView({ initialSection: "models", initialSettings: payloadWithCodex });

    const codexRow = await screen.findByTestId("model-call-order-row-codex");
    expect(codexRow).toHaveTextContent("codex");
    expect(codexRow).not.toHaveTextContent("Codex");
    expect(codexRow).toHaveTextContent("openai-codex/gpt-5.5");
    expect(codexRow).toHaveTextContent("Disabled");
    expect(codexRow).toHaveAttribute("draggable", "false");
    expect(screen.queryByRole("button", { name: "Add preset" })).not.toBeInTheDocument();

    const enableSwitch = within(codexRow).getByRole("switch", { name: "Enable preset" });
    expect(enableSwitch).not.toBeChecked();
    fireEvent.click(enableSwitch);

    await waitFor(() => {
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.model_call_order.update",
        { order: ["primary", "backup", "codex"] },
        20_000,
      );
    });
    const enabledCodexRow = await screen.findByTestId("model-call-order-row-codex");
    expect(enabledCodexRow).not.toHaveTextContent("Disabled");
    expect(enabledCodexRow).not.toHaveTextContent(/Fallback/);
    expect(enabledCodexRow).toHaveAttribute("draggable", "true");
    expect(
      within(enabledCodexRow).getByRole("switch", { name: "Disable preset" }),
    ).toBeChecked();
    expect(screen.queryByText("Up to date.")).not.toBeInTheDocument();
  });

  it("appends a new model preset to the call order immediately", async () => {
    const { payload } = settingsPayloadWithBackup();
    const writerPreset = {
      ...payload.model_presets[0],
      name: "Writer",
      label: "Writer",
      active: false,
      model: "openai/gpt-4o-mini",
      provider: "openai",
      resolved_provider: "openai",
    };
    const createdPayload: SettingsPayload = {
      ...payload,
      model_presets: [...payload.model_presets, writerPreset],
      created_model_preset: writerPreset.name,
    };
    const orderedPayload: SettingsPayload = {
      ...createdPayload,
      model_call_order: ["primary", "backup", "Writer"],
      created_model_preset: undefined,
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
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock
      .mockResolvedValueOnce(createdPayload)
      .mockResolvedValueOnce(orderedPayload);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "New model preset" }));
    expect(screen.queryByRole("dialog", { name: "New model preset" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(
      screen.queryByText("Complete the preset before saving."),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Preset name" }), {
      target: { value: "Writer" },
    });
    await openPopover(screen.getByRole("button", { name: "Select model" }));
    const modelSearch = await screen.findByRole("combobox", {
      name: "Search or type model ID",
    });
    fireEvent.change(modelSearch, {
      target: { value: "openai/gpt-4o-mini" },
    });
    fireEvent.keyDown(modelSearch, { key: "Enter" });
    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(requestMutationMock).toHaveBeenLastCalledWith(
        "settings.model_call_order.update",
        { order: ["primary", "backup", "Writer"] },
        20_000,
      );
    });
    const writerRow = await screen.findByTestId("model-call-order-row-Writer");
    expect(writerRow).not.toHaveTextContent("Disabled");
    expect(writerRow).not.toHaveTextContent(/Fallback/);
    expect(within(writerRow).getByRole("switch", { name: "Disable preset" })).toBeChecked();
    expect(screen.getAllByText("Writer").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Save order" })).not.toBeInTheDocument();
  });

  it("shows an inline error when a new preset name already exists", async () => {
    const { payload } = settingsPayloadWithBackup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }) as Response),
    );

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    fireEvent.click(screen.getByRole("button", { name: "New model preset" }));
    const nameInput = screen.getByRole("textbox", { name: "Preset name" });
    fireEvent.change(nameInput, { target: { value: "PRIMARY" } });
    await openPopover(screen.getByRole("button", { name: "Select model" }));
    const modelSearch = await screen.findByRole("combobox", {
      name: "Search or type model ID",
    });
    fireEvent.change(modelSearch, { target: { value: "openai/gpt-4o-mini" } });
    fireEvent.keyDown(modelSearch, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(requestMutationMock).not.toHaveBeenCalled();
    expect(nameInput).toHaveAttribute("aria-invalid", "true");
    expect(nameInput).toHaveAttribute("aria-describedby", "model-preset-name-error");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "A preset with this name already exists.",
    );
    expect(nameInput.parentElement).toHaveClass(
      "animate-[preset-name-shake_180ms_ease-in-out]",
    );

    fireEvent.change(nameInput, { target: { value: "Writer" } });
    expect(nameInput).toHaveAttribute("aria-invalid", "false");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("converts legacy model settings into presets before editing call order", async () => {
    const migratedPayload = settingsPayload();
    const defaultPreset = {
      ...migratedPayload.model_presets[0],
      name: "default",
      label: "Default",
      is_default: true,
    };
    const legacyPayload: SettingsPayload = {
      ...migratedPayload,
      agent: {
        ...migratedPayload.agent,
        model_preset: "default",
      },
      model_presets: [defaultPreset],
      model_call_order: [],
      model_call_order_editable: false,
      model_configuration_migratable: true,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(legacyPayload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce(migratedPayload);

    renderSettingsView({ initialSection: "models", initialSettings: legacyPayload });

    fireEvent.click(
      await screen.findByRole("button", { name: "Convert to presets" }),
    );

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.model_configuration.migrate",
        {},
        20_000,
      ),
    );
    expect(
      screen.queryByRole("button", { name: "Convert to presets" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save order" })).not.toBeInTheDocument();
    expect(screen.queryByText("Default")).not.toBeInTheDocument();
  });

  it("starts fresh users with an empty preset list instead of legacy conversion", async () => {
    const base = settingsPayload();
    const freshPayload: SettingsPayload = {
      ...base,
      agent: {
        ...base.agent,
        model: "anthropic/claude-opus-4-5",
        provider: "auto",
        resolved_provider: null,
        has_api_key: false,
        model_preset: "default",
      },
      model_presets: [
        {
          ...base.model_presets[0],
          name: "default",
          label: "Default",
          active: true,
          is_default: true,
          model: "anthropic/claude-opus-4-5",
          provider: "auto",
          resolved_provider: null,
        },
      ],
      model_call_order: [],
      model_call_order_editable: false,
      model_configuration_migratable: false,
      providers: [],
    };
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({ initialSection: "models", initialSettings: freshPayload });

    expect(
      await screen.findByRole("button", { name: "New model preset" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Convert to presets" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("claude-opus-4-5")).not.toBeInTheDocument();
  });

  it("does not expose the synthetic default configuration as a WebUI preset", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      agent: {
        ...base.agent,
        model: "MiniMax-M3",
        provider: "minimax_anthropic",
        resolved_provider: "minimax_anthropic",
        model_preset: "fast",
      },
      model_presets: [
        {
          ...base.model_presets[0],
          name: "default",
          label: "Default",
          active: false,
          is_default: true,
          model: "openai-codex/gpt-5.5",
          provider: "openai_codex",
          resolved_provider: "openai_codex",
        },
        {
          ...base.model_presets[0],
          name: "fast",
          label: "fast",
          active: true,
          is_default: false,
          model: "MiniMax-M3",
          provider: "minimax_anthropic",
          resolved_provider: "minimax_anthropic",
        },
      ],
      model_call_order: ["fast"],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: true,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: "acct-test",
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
        {
          name: "minimax_anthropic",
          label: "MiniMax (Anthropic)",
          configured: true,
          auth_type: "api_key",
          api_key_required: true,
          api_key_hint: "sk-...",
          api_base: "https://api.minimax.io/anthropic",
          default_api_base: "https://api.minimax.io/anthropic",
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    expect((await screen.findAllByText("MiniMax-M3")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("fast").length).toBeGreaterThan(0);
    expect(screen.queryByText("Default")).not.toBeInTheDocument();
    expect(screen.queryByText("openai-codex/gpt-5.5")).not.toBeInTheDocument();
  });

  it("does not expose the synthetic default preset in the overview summary", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      agent: {
        ...base.agent,
        model_preset: "default",
      },
      model_presets: [
        {
          ...base.model_presets[0],
          name: "default",
          label: "Default",
          is_default: true,
        },
      ],
      model_call_order: [],
      model_call_order_editable: false,
    };
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({ initialSection: "overview", initialSettings: payload });

    expect(await screen.findByText("openai/gpt-4o")).toBeInTheDocument();
    expect(screen.queryByText("openai · default")).not.toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
  });

  it("uses the resolved provider row for auto dynamic providers without api keys", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({
      initialSection: "models",
      initialSettings: autoDynamicProviderPayload({
        configured: true,
        hasApiKey: false,
        apiBase: "https://proxy.example.test/v1",
        apiKeyHint: null,
      }),
    });

    expect((await screen.findAllByText("companyProxy/gpt-4o")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Company Proxy").length).toBeGreaterThan(0);
    expect(screen.queryByText("Provider setup required")).not.toBeInTheDocument();
  });

  it("does not treat auto dynamic provider api keys as configured without apiBase", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({
      initialSection: "models",
      initialSettings: autoDynamicProviderPayload({
        configured: false,
        hasApiKey: true,
        apiBase: null,
        apiKeyHint: "sk-...",
      }),
    });

    expect((await screen.findAllByText("companyProxy/gpt-4o")).length).toBeGreaterThan(0);
    expect(screen.getByText("Provider setup required")).toBeInTheDocument();
    expect(
      screen.queryByText("Configure this provider before saving the preset."),
    ).not.toBeInTheDocument();
  });

  it("marks the current model as unconfigured when its provider needs setup", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "openai-codex/gpt-5.1-codex",
        provider: "openai_codex",
        resolved_provider: "openai_codex",
        has_api_key: false,
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "openai-codex/gpt-5.1-codex",
          provider: "openai_codex",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
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

    renderSettingsView({ initialSection: "models" });

    expect(await screen.findByText("Provider setup required")).toBeInTheDocument();
    await togglePresetEditor();
    expect(screen.getAllByText(/Sign in before saving/).length).toBeGreaterThan(0);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("keeps unsigned OAuth providers out of the active provider picker", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "deepseek-chat",
        provider: "deepseek",
        resolved_provider: "deepseek",
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "deepseek-chat",
          provider: "deepseek",
        },
      ],
      providers: [
        {
          name: "deepseek",
          label: "DeepSeek",
          configured: true,
          auth_type: "api_key",
          api_key_required: true,
          api_key_hint: "sk-...",
          api_base: "https://api.deepseek.com",
          default_api_base: "https://api.deepseek.com",
        },
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
        {
          name: "github_copilot",
          label: "GitHub Copilot",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: "https://api.githubcopilot.com",
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
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

    renderSettingsView({ initialSection: "models" });

    await togglePresetEditor();
    const deepseekButtons = await screen.findAllByRole("button", { name: /DeepSeek/ });
    const providerPicker = deepseekButtons.find(
      (button) => button.getAttribute("aria-haspopup") === "menu",
    );
    if (!providerPicker) throw new Error("provider picker was not found");
    fireEvent.pointerDown(providerPicker);

    expect(await screen.findByRole("menuitem", { name: /DeepSeek/ })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /OpenAI Codex/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /GitHub Copilot/ })).not.toBeInTheDocument();
  });

  it("does not fetch model lists for unsigned OAuth providers", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "",
        provider: "openai_codex",
        resolved_provider: "openai_codex",
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "",
          provider: "openai_codex",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
        {
          name: "github_copilot",
          label: "GitHub Copilot",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: "https://api.githubcopilot.com",
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
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
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models" });

    await togglePresetEditor();
    await openPopover(await screen.findByRole("button", { name: /Select model/i }));
    expect(
      await screen.findByText("Configure this provider before loading models."),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/api/settings/provider-models"),
      ),
    ).toBe(false);
  });

  it("prefills manual model ids for configured OAuth providers", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "open-codex/gpt-5.5",
        provider: "openai_codex",
        resolved_provider: "openai_codex",
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "open-codex/gpt-5.5",
          provider: "openai_codex",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: true,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: "acct-test",
          oauth_expires_at: null,
          oauth_login_supported: true,
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
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models" });

    await togglePresetEditor();
    const modelButtons = await screen.findAllByRole("button", { name: /open-codex\/gpt-5\.5/i });
    await openPopover(modelButtons[modelButtons.length - 1]);
    const input = (await screen.findByPlaceholderText("Search or type model ID")) as HTMLInputElement;
    expect(input.value).toBe("open-codex/gpt-5.5");

    fireEvent.change(input, { target: { value: "openai-codex/gpt-5.5" } });
    expect(await screen.findByText("“openai-codex/gpt-5.5”")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/api/settings/provider-models"),
      ),
    ).toBe(false);
  });

  it("defers the OrcaRouter catalog until the user searches", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      agent: {
        ...base.agent,
        model: "orcarouter/auto",
        provider: "orcarouter",
        resolved_provider: "orcarouter",
      },
      model_presets: [
        {
          ...base.model_presets[0],
          model: "orcarouter/auto",
          provider: "orcarouter",
          resolved_provider: "orcarouter",
        },
      ],
      providers: [
        {
          name: "orcarouter",
          label: "OrcaRouter",
          configured: true,
          auth_type: "api_key",
          api_key_required: true,
          api_key_hint: "sk-o••••test",
          api_base: null,
          default_api_base: "https://api.orcarouter.ai/v1",
          model_catalog: "catalog",
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
      if (url === "/api/settings/provider-models?provider=orcarouter") {
        return jsonResponse({
          provider: "orcarouter",
          label: "OrcaRouter",
          status: "available",
          catalog_kind: "catalog",
          models: [
            { id: "orcarouter/auto", owned_by: "orcarouter" },
            { id: "anthropic/claude-sonnet-4.6", owned_by: "anthropic" },
          ],
          model_count: 2,
          fetched_at: 1,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models" });

    await togglePresetEditor();
    const modelButtons = await screen.findAllByRole("button", { name: /orcarouter\/auto/i });
    await openPopover(modelButtons[modelButtons.length - 1]);
    expect(await screen.findByText("Search provider catalog to choose a model.")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/api/settings/provider-models"),
      ),
    ).toBe(false);

    fireEvent.change(screen.getByPlaceholderText("Search or type model ID"), {
      target: { value: "cl" },
    });

    await screen.findByText("anthropic/claude-sonnet-4.6");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/provider-models?provider=orcarouter",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("loads curated models for configured OAuth providers", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      agent: {
        ...base.agent,
        model: "openai-codex/gpt-5.5",
        provider: "openai_codex",
        resolved_provider: "openai_codex",
      },
      model_presets: [
        {
          ...base.model_presets[0],
          model: "openai-codex/gpt-5.5",
          provider: "openai_codex",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: true,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: "https://chatgpt.com/backend-api",
          model_catalog: "builtin",
          oauth_account: "acct-test",
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings/provider-models?provider=openai_codex") {
        return jsonResponse({
          provider: "openai_codex",
          label: "OpenAI Codex",
          status: "available",
          catalog_kind: "builtin",
          models: [
            {
              id: "openai-codex/gpt-5.6-sol",
              label: "GPT-5.6-Sol",
              description: "Latest frontier agentic coding model.",
              owned_by: "OpenAI Codex",
              context_window: 372000,
            },
          ],
          model_count: 1,
          fetched_at: 1,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await togglePresetEditor();
    const modelButtons = await screen.findAllByRole("button", {
      name: /openai-codex\/gpt-5\.5/i,
    });
    await openPopover(modelButtons[modelButtons.length - 1]);

    expect(await screen.findByText("GPT-5.6-Sol")).toBeInTheDocument();
    expect(screen.getByText(/Latest frontier agentic coding model\./)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/provider-models?provider=openai_codex",
      expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
    );
  });

  it("loads hybrid online models for configured OAuth providers", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      agent: {
        ...base.agent,
        model: "xai-grok/grok-4.5",
        provider: "xai_grok",
        resolved_provider: "xai_grok",
      },
      model_presets: [
        {
          ...base.model_presets[0],
          model: "xai-grok/grok-4.5",
          provider: "xai_grok",
        },
      ],
      providers: [
        {
          name: "xai_grok",
          label: "xAI Grok",
          configured: true,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: "https://cli-chat-proxy.grok.com/v1",
          model_catalog: "hybrid",
          oauth_account: "acct-test",
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings/provider-models?provider=xai_grok") {
        return jsonResponse({
          provider: "xai_grok",
          label: "xAI Grok",
          status: "available",
          catalog_kind: "hybrid",
          source: "remote",
          models: [
            {
              id: "xai-grok/grok-4.6",
              label: "Grok 4.6",
              description: "Latest frontier model",
              owned_by: "xAI",
              context_window: 500_000,
            },
            {
              id: "xai-grok/grok-4.5",
              label: "Grok 4.5",
              owned_by: "xAI",
              context_window: 500_000,
            },
          ],
          model_count: 2,
          fetched_at: 1,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    await togglePresetEditor();
    const modelButtons = await screen.findAllByRole("button", {
      name: /xai-grok\/grok-4\.5/i,
    });
    await openPopover(modelButtons[modelButtons.length - 1]);

    expect(await screen.findByText("Grok 4.6")).toBeInTheDocument();
    expect(screen.getByText(/Latest frontier model/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/provider-models?provider=xai_grok",
      expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
    );
  });

  it("creates presets in the inline editor and can cancel without opening a dialog", async () => {
    const payload = settingsPayload();
    payload.providers = [{ name: "openai", label: "OpenAI", configured: true }];
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

    renderSettingsView({ initialSection: "models" });

    const createButton = await screen.findByRole("button", { name: "New model preset" });
    expect(createButton).toHaveClass("w-full");
    fireEvent.click(createButton);

    expect(screen.queryByRole("dialog", { name: "New model preset" })).not.toBeInTheDocument();
    expect(screen.getByTestId("model-preset-editor")).toHaveClass("mt-3", "mb-3");
    expect(screen.getByRole("textbox", { name: "Preset name" })).toHaveValue("");
    expect(screen.queryByText("Temperature")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Advanced options/ }));
    expect(screen.getByText("Temperature")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByDisplayValue("Primary")).not.toBeInTheDocument();
    expect(screen.queryByText("Edit preset")).not.toBeInTheDocument();
    expect(document.body.style.pointerEvents).not.toBe("none");

    fireEvent.click(screen.getByRole("button", { name: "New model preset" }));
    const nameInput = await screen.findByRole("textbox", { name: "Preset name" });
    expect(nameInput).toHaveValue("");
    expect(nameInput).toHaveAttribute("placeholder", "e.g. Fast writing");

    await openPopover(screen.getByRole("button", { name: "Select model" }));
    const modelSearch = await screen.findByRole("combobox", {
      name: "Search or type model ID",
    });
    fireEvent.change(modelSearch, { target: { value: "openai/gpt-4o-mini" } });
    fireEvent.keyDown(modelSearch, { key: "Enter" });

    expect(nameInput).toHaveValue("gpt-4o-mini");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();

    fireEvent.change(nameInput, { target: { value: "Writer" } });
    await openPopover(screen.getByRole("button", { name: /openai\/gpt-4o-mini/ }));
    const nextModelSearch = await screen.findByRole("combobox", {
      name: "Search or type model ID",
    });
    fireEvent.change(nextModelSearch, { target: { value: "openai/gpt-4.1-mini" } });
    fireEvent.keyDown(nextModelSearch, { key: "Enter" });
    expect(nameInput).toHaveValue("Writer");
  });

  it("loads provider models and lets users choose one without typing the id manually", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "deepseek-chat",
        provider: "deepseek",
        resolved_provider: "deepseek",
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "deepseek-chat",
          provider: "deepseek",
        },
      ],
      providers: [
        {
          name: "deepseek",
          label: "DeepSeek",
          configured: true,
          auth_type: "api_key",
          api_key_required: true,
          api_key_hint: "sk-...",
          api_base: "https://api.deepseek.com",
          default_api_base: "https://api.deepseek.com",
        },
      ],
    };
    const updatedPayload: SettingsPayload = {
      ...payload,
      agent: {
        ...payload.agent,
        model: "deepseek-reasoner",
        temperature: 0.4,
      },
      model_presets: [
        {
        ...payload.model_presets[0],
        model: "deepseek-reasoner",
        temperature: 0.4,
        reasoning_effort: "provider-native-mode",
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
      if (url === "/api/settings/provider-models?provider=deepseek") {
        return jsonResponse({
          provider: "deepseek",
          label: "DeepSeek",
          status: "available",
          catalog_kind: "official",
          models: [
            { id: "deepseek-chat", owned_by: "deepseek", context_window: 65536 },
            { id: "deepseek-reasoner", owned_by: "deepseek", context_window: 65536 },
          ],
          model_count: 2,
          fetched_at: 1,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce(updatedPayload);

    renderSettingsView({ initialSection: "models" });

    await togglePresetEditor();
    const modelButtons = await screen.findAllByRole("button", { name: /deepseek-chat/i });
    await openPopover(modelButtons[modelButtons.length - 1]);
    await screen.findByText("deepseek-reasoner");
    fireEvent.click(screen.getAllByText("deepseek-reasoner")[0]);
    fireEvent.click(screen.getByRole("button", { name: /Advanced options/ }));
    fireEvent.change(screen.getByLabelText("Temperature"), {
      target: { value: "0.4" },
    });
    fireEvent.change(screen.getByLabelText("Reasoning effort"), {
      target: { value: "provider-native-mode" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/provider-models?provider=deepseek",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    await waitFor(() => {
      const saveCall = requestMutationMock.mock.calls.find(([action]) =>
        action === "settings.model_configuration.update",
      );
      expect(saveCall).toBeDefined();
      expect(saveCall?.[1]).toEqual({
        name: "primary",
        model: "deepseek-reasoner",
        reasoning_effort: "provider-native-mode",
        temperature: 0.4,
      });
    });
  });
});
