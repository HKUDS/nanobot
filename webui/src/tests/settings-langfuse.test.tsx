import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { NanobotFeatureInfo, ObservabilitySettingsPayload, ObservabilityTestResult, SettingsPayload } from "@/lib/types";
import { act, fireEvent, installSettingsViewTestHooks, jsonResponse, renderSettingsView, requestMutationMock, screen, settingsPayload, waitFor, within } from "@/tests/settings-test-utils";

const capability = "webui.langfuse-settings.v1";
const success = "Connection verified.";
const stale = "Values changed. Test again.";

function langfuseSettings(observability: Partial<ObservabilitySettingsPayload> = {}): SettingsPayload {
  return {
    ...settingsPayload(),
    observability: {
      provider: "langfuse", configured: true, base_url: "https://cloud.langfuse.com",
      enabled: false, public_key_hint: "pk-••••", secret_key_hint: "sk-••••",
      source: "config", uses_environment: false, active_enabled: false, requires_restart: false,
      ...observability,
    },
  };
}

function langfuseFeature(overrides: Partial<NanobotFeatureInfo> = {}): NanobotFeatureInfo {
  return {
    name: "langfuse", display_name: "Langfuse", type: "feature", enabled: false,
    installed: true, ready: true, status: "not_enabled", install_supported: true, requires_restart: false,
    ...overrides,
  };
}

function stubHost(payload: SettingsPayload | (() => SettingsPayload), feature = langfuseFeature()) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/settings") return jsonResponse(typeof payload === "function" ? payload() : payload);
    if (url === "/api/settings/nanobot-features") return jsonResponse({ features: [feature], enabled_count: 0 });
    if (url === "/api/settings/api-service") return jsonResponse({
      installed: true, running: false, managed: false, host: "127.0.0.1", port: 8900,
      timeout: 120, endpoint: "http://127.0.0.1:8900/v1", command: "nanobot serve", api_key_hint: null,
    });
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderLangfuse(options: Parameters<typeof renderSettingsView>[0] = {}) {
  renderSettingsView({ initialSection: "runtime", webuiCapabilities: [capability], ...options });
}

async function openEditor(advanced = true) {
  fireEvent.click(await screen.findByRole("button", { name: "Configure Langfuse" }));
  const dialog = within(screen.getByRole("dialog", { name: "Langfuse" }));
  await waitFor(() => expect(dialog.queryByRole("status", { name: "Checking" })).not.toBeInTheDocument());
  if (advanced) fireEvent.click(dialog.getByRole("button", { name: "Advanced options" }));
  return dialog;
}

function replaceKey(dialog: ReturnType<typeof within>, key: "Public Key" | "Secret Key", value: string) {
  const replace = dialog.queryByRole("button", { name: `Replace ${key}` });
  if (replace) fireEvent.click(replace);
  fireEvent.change(dialog.getByLabelText(key, { exact: true }), { target: { value } });
}

function saveResult(payload: SettingsPayload, observability: Partial<ObservabilitySettingsPayload>): SettingsPayload {
  return {
    ...payload, requires_restart: true, restart_required_sections: ["runtime"],
    observability: { ...payload.observability!, ...observability, requires_restart: true },
  };
}

describe("Langfuse settings", () => {
  installSettingsViewTestHooks();

  it.each([{ capabilities: [] }, { capabilities: ["webui.core.v1", "webui.future-feature.v1"] }])(
    "keeps environment setup on hosts without the named capability ($capabilities)", async ({ capabilities }) => {
    // An independent older-host shape: no editable observability fields.
    const payload = settingsPayload();
    const fetchMock = stubHost(payload);
    renderLangfuse({ webuiCapabilities: capabilities });
    expect(await screen.findByText("Needs setup")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Langfuse" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Set LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY, then restart nanobot.");
    expect(screen.queryByRole("button", { name: "Configure Langfuse" })).not.toBeInTheDocument();
    expect(requestMutationMock).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/observability/"))).toBe(false);
  });

  it.each(["Cancel", "Close", "Escape"])("discards the local draft on %s and returns focus without saving", async (close) => {
    const payload = langfuseSettings();
    stubHost(payload);
    renderLangfuse();
    let dialog = await openEditor();
    expect(dialog.queryByRole("button", { name: "Show new Secret Key" })).not.toBeInTheDocument();
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveValue("");
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveAttribute("placeholder", "••••••••");
    fireEvent.change(dialog.getByLabelText("Base URL"), { target: { value: "https://discarded.example" } });
    replaceKey(dialog, "Secret Key", "discarded-secret");
    fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    expect(dialog.getByText("Sends model inputs and outputs to Langfuse.")).toBeVisible();
    fireEvent.blur(dialog.getByLabelText("Secret Key", { exact: true }));
    if (close === "Escape") await userEvent.setup().keyboard("{Escape}");
    else fireEvent.click(dialog.getByRole("button", { name: close }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Configure Langfuse" })).toHaveFocus());
    expect(requestMutationMock).not.toHaveBeenCalled();
    dialog = await openEditor();
    expect(dialog.getByLabelText("Base URL")).toHaveValue(payload.observability!.base_url);
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveValue("");
    expect(dialog.getByRole("button", { name: "Replace Secret Key" })).toBeVisible();
    expect(dialog.getByRole("switch", { name: "Enable tracing" })).not.toBeChecked();
  });

  it("keeps the default form compact and preserves advanced drafts while folded", async () => {
    const payload = langfuseSettings({ configured: false, public_key_hint: null, secret_key_hint: null });
    stubHost(payload);
    renderLangfuse();
    const dialog = await openEditor(false);
    const advanced = dialog.getByRole("button", { name: "Advanced options" });
    expect(advanced).toHaveAttribute("aria-expanded", "false");
    expect(dialog.queryByRole("textbox", { name: "Base URL" })).not.toBeInTheDocument();
    expect(dialog.getByLabelText("Public Key", { exact: true })).toBeVisible();
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toBeVisible();
    expect(dialog.getByRole("button", { name: "Test connection" })).toBeDisabled();
    replaceKey(dialog, "Public Key", "new-public");
    replaceKey(dialog, "Secret Key", "new-secret");
    expect(dialog.getByRole("button", { name: "Test connection" })).toBeEnabled();
    fireEvent.click(advanced);
    fireEvent.change(dialog.getByRole("textbox", { name: "Base URL" }), { target: { value: "https://self-hosted.example" } });
    fireEvent.click(advanced);
    fireEvent.click(advanced);
    expect(dialog.getByRole("textbox", { name: "Base URL" })).toHaveValue("https://self-hosted.example");
    fireEvent.click(advanced);
    requestMutationMock.mockResolvedValueOnce(saveResult(payload, { base_url: "https://self-hosted.example" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.observability.update", {
      enabled: false, base_url: "https://self-hosted.example", public_key: "new-public", secret_key: "new-secret",
    }, 20_000));
  });

  it("preserves untouched environment credentials and displays the returned raw URL reference", async () => {
    const payload = langfuseSettings({ source: "environment", uses_environment: true, enabled: true, active_enabled: true });
    const saved = saveResult(payload, { source: "config", base_url: "${LANGFUSE_BASE_URL}" });
    stubHost(payload);
    requestMutationMock.mockResolvedValueOnce(saved);
    const onSettingsChange = vi.fn();
    renderLangfuse({ onSettingsChange });
    let dialog = await openEditor();
    fireEvent.focus(dialog.getByText("Environment references"));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("From environment. Saving keeps untouched fields as environment references.");
    // Opening replacement without typing must not erase the stored reference.
    fireEvent.click(dialog.getByRole("button", { name: "Replace Secret Key" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.observability.update", {
      enabled: true, base_url: "https://cloud.langfuse.com",
    }, 20_000));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onSettingsChange).toHaveBeenLastCalledWith(saved);
    dialog = await openEditor();
    expect(dialog.getByLabelText("Base URL")).toHaveValue("${LANGFUSE_BASE_URL}");
    expect(dialog.getByText("Environment references")).toBeVisible();
    expect(dialog.getByLabelText("Public Key", { exact: true })).toHaveValue("");
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveValue("");
  });

  it.each([
    ["Public Key", "Secret Key", { public_key: "${NEW_KEY}", secret_key: "" }],
    ["Secret Key", "Public Key", { public_key: "", secret_key: "${NEW_KEY}" }],
  ] as const)("replaces %s and explicitly clears %s without sending a mask", async (replace, clear, keys) => {
    const payload = langfuseSettings();
    stubHost(payload);
    requestMutationMock.mockResolvedValueOnce(saveResult(payload, {
      configured: false, uses_environment: true,
      public_key_hint: keys.public_key ? "pk-••••" : null,
      secret_key_hint: keys.secret_key ? "sk-••••" : null,
    }));
    renderLangfuse();
    const dialog = await openEditor();
    replaceKey(dialog, replace, "${NEW_KEY}");
    expect(dialog.getByLabelText(replace, { exact: true })).toHaveAttribute("type", "password");
    fireEvent.click(dialog.getByRole("button", { name: `Show new ${replace}` }));
    expect(dialog.getByLabelText(replace, { exact: true })).toHaveAttribute("type", "text");
    fireEvent.click(dialog.getByRole("button", { name: `Hide new ${replace}` }));
    fireEvent.click(dialog.getByRole("button", { name: `Clear ${clear}` }));
    expect(dialog.getByText("Will be cleared on save.")).toBeVisible();
    expect(dialog.getByLabelText(clear, { exact: true })).toHaveValue("");
    expect(dialog.queryByRole("button", { name: `Show new ${clear}` })).not.toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.observability.update", {
      enabled: false, base_url: "https://cloud.langfuse.com", ...keys,
    }, 20_000));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const reopened = await openEditor();
    expect(reopened.getByLabelText(clear, { exact: true })).not.toHaveAttribute("readonly");
    expect(reopened.getByLabelText(replace, { exact: true })).toHaveAttribute("readonly");
    expect(reopened.getByLabelText(replace, { exact: true })).toHaveValue("");
  });

  it("retains failed save values and only reveals newly typed credentials for retry", async () => {
    const payload = langfuseSettings();
    stubHost(payload);
    requestMutationMock.mockRejectedValueOnce(new Error("Untrusted server detail"));
    renderLangfuse();
    const dialog = await openEditor();
    fireEvent.change(dialog.getByLabelText("Base URL"), { target: { value: "${TRACE_URL}" } });
    replaceKey(dialog, "Secret Key", "new-secret");
    fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    expect(await dialog.findByRole("alert")).toHaveTextContent("Could not save. Check your settings and try again.");
    expect(dialog.getByLabelText("Base URL")).toHaveValue("${TRACE_URL}");
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveValue("new-secret");
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveAttribute("type", "password");
    expect(dialog.getByRole("switch", { name: "Enable tracing" })).toBeChecked();
    expect(dialog.queryByRole("button", { name: "Show new Public Key" })).not.toBeInTheDocument();
    requestMutationMock.mockResolvedValueOnce(saveResult(payload, { enabled: true, base_url: "${TRACE_URL}" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(requestMutationMock).toHaveBeenLastCalledWith("settings.observability.update", {
      enabled: true, base_url: "${TRACE_URL}", secret_key: "new-secret",
    }, 20_000);
  });

  it("allows disabled config and testing without SDK support, but blocks incomplete enabled saves", async () => {
    const payload = langfuseSettings({ configured: false, public_key_hint: null, secret_key_hint: null });
    stubHost(payload, langfuseFeature({ installed: false, install_supported: false }));
    renderLangfuse();
    const dialog = await openEditor();
    expect(await dialog.findByText("Install Langfuse support on the host to enable tracing.")).toBeVisible();
    expect(dialog.queryByRole("button", { name: "Install tracing support" })).not.toBeInTheDocument();
    fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    replaceKey(dialog, "Public Key", "new-public");
    replaceKey(dialog, "Secret Key", "new-secret");
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(requestMutationMock).not.toHaveBeenCalled();
    requestMutationMock.mockResolvedValueOnce({ ok: true });
    fireEvent.click(dialog.getByRole("button", { name: "Test connection" }));
    expect(await dialog.findByText(success)).toBeVisible();
    fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    fireEvent.click(dialog.getByRole("button", { name: "Clear Public Key" }));
    fireEvent.click(dialog.getByRole("button", { name: "Clear Secret Key" }));
    expect(dialog.getByRole("button", { name: "Save" })).toBeEnabled();
    requestMutationMock.mockResolvedValueOnce(saveResult(payload, {}));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith("settings.observability.update", {
      enabled: false, base_url: "https://cloud.langfuse.com", public_key: "", secret_key: "",
    }, 20_000));
  });

  it("requires a URL and both credentials even when support is installed", async () => {
    const payload = langfuseSettings({ configured: false, public_key_hint: null, secret_key_hint: null, base_url: "" });
    stubHost(payload);
    renderLangfuse();
    const dialog = await openEditor();
    fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    replaceKey(dialog, "Public Key", "new-public");
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    replaceKey(dialog, "Secret Key", "${SECRET_KEY}");
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(dialog.getByLabelText("Base URL"), { target: { value: "${TRACE_URL}" } });
    expect(dialog.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("installs support only after explicit confirmation, independently of the enabled draft", async () => {
    const payload = langfuseSettings();
    const feature = langfuseFeature({ installed: false });
    stubHost(payload, feature);
    renderLangfuse();
    const dialog = await openEditor();
    fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(dialog.getByRole("button", { name: "Install tracing support" }));
    let confirmation = within(screen.getByRole("dialog", { name: "Install support for Langfuse?" }));
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(confirmation.getByRole("button", { name: "Cancel" }));
    expect(dialog.getByRole("switch", { name: "Enable tracing" })).toBeChecked();
    fireEvent.click(dialog.getByRole("button", { name: "Install tracing support" }));
    confirmation = within(screen.getByRole("dialog", { name: "Install support for Langfuse?" }));
    requestMutationMock.mockResolvedValueOnce({ features: [{ ...feature, installed: true }], enabled_count: 0 });
    fireEvent.click(confirmation.getByRole("button", { name: "Install support" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.feature.enable", {
      name: "langfuse", install_only: true,
    }, 150_000));
    await waitFor(() => expect(dialog.getByRole("button", { name: "Save" })).toBeEnabled());
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
  });

  it.each(["Base URL", "Public Key", "Secret Key", "enabled"])("tests the unsaved draft and marks the result stale after changing %s", async (field) => {
    const payload = langfuseSettings();
    stubHost(payload);
    const onSettingsChange = vi.fn();
    const onRestart = vi.fn();
    renderLangfuse({ onSettingsChange, onRestart });
    const dialog = await openEditor();
    onSettingsChange.mockClear();
    fireEvent.change(dialog.getByLabelText("Base URL"), { target: { value: "https://langfuse.example" } });
    replaceKey(dialog, "Public Key", "draft-public");
    replaceKey(dialog, "Secret Key", "draft-secret");
    fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    requestMutationMock.mockResolvedValueOnce({ ok: true });
    fireEvent.click(dialog.getByRole("button", { name: "Test connection" }));
    expect(await dialog.findByText(success)).toBeVisible();
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(requestMutationMock).toHaveBeenCalledWith("settings.observability.test", {
      enabled: true, base_url: "https://langfuse.example", public_key: "draft-public", secret_key: "draft-secret",
    }, 20_000);
    expect(onSettingsChange).not.toHaveBeenCalled();
    expect(onRestart).not.toHaveBeenCalled();
    if (field === "enabled") fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    else fireEvent.change(dialog.getByLabelText(field, { exact: true }), { target: { value: "${CHANGED}" } });
    expect(dialog.getByText(stale)).toBeVisible();
    expect(dialog.queryByText(success)).not.toBeInTheDocument();
  });

  it("keeps a late probe result stale when the user edits while testing", async () => {
    stubHost(langfuseSettings());
    let finish!: (result: ObservabilityTestResult) => void;
    requestMutationMock.mockReturnValueOnce(new Promise<ObservabilityTestResult>((resolve) => { finish = resolve; }));
    renderLangfuse();
    const dialog = await openEditor();
    fireEvent.click(dialog.getByRole("button", { name: "Test connection" }));
    expect(dialog.getByRole("button", { name: "Testing…" })).toBeDisabled();
    fireEvent.click(dialog.getByRole("button", { name: "Clear Secret Key" }));
    await act(async () => finish({ ok: true }));
    expect(dialog.getByText(stale)).toBeVisible();
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveValue("");
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(requestMutationMock).toHaveBeenCalledWith("settings.observability.test", {
      enabled: false, base_url: "https://cloud.langfuse.com",
    }, 20_000);
  });

  it.each([
    ["missing_credentials", "Check both keys or their environment variables."],
    ["invalid_url", "Check the service URL or its environment variable."],
    ["blocked_url", "Use a URL allowed by the host's network policy."],
    ["invalid_credentials", "Check this Langfuse project's key pair."],
    ["unreachable", "Check the service URL and network connection."],
    ["timeout", "Connection timed out. Try again."],
  ])("explains the %s probe failure without discarding the draft", async (error, message) => {
    stubHost(langfuseSettings());
    requestMutationMock.mockResolvedValueOnce({ ok: false, error });
    renderLangfuse();
    const dialog = await openEditor();
    const url = error === "invalid_url" ? "not-a-url" : "https://langfuse.example";
    fireEvent.change(dialog.getByLabelText("Base URL"), { target: { value: url } });
    if (error === "missing_credentials") replaceKey(dialog, "Secret Key", "${MISSING_SECRET}");
    fireEvent.click(dialog.getByRole("button", { name: "Advanced options" }));
    fireEvent.click(dialog.getByRole("button", { name: "Test connection" }));
    expect(await dialog.findByText(message)).toBeVisible();
    if (["invalid_url", "blocked_url", "unreachable", "timeout"].includes(error)) {
      expect(dialog.getByRole("button", { name: "Advanced options" })).toHaveAttribute("aria-expanded", "true");
    }
    expect(dialog.getByLabelText("Base URL")).toHaveValue(url);
    expect(dialog.getByRole("button", { name: "Test connection" })).toBeEnabled();
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
  });

  it("allows retry after a probe transport error and discards results on close", async () => {
    stubHost(langfuseSettings());
    requestMutationMock.mockRejectedValueOnce(new Error("Connection lost"));
    renderLangfuse();
    let dialog = await openEditor();
    replaceKey(dialog, "Secret Key", "draft-secret");
    fireEvent.click(dialog.getByRole("button", { name: "Test connection" }));
    expect(await dialog.findByText("Could not run the test. Try again.")).toBeVisible();
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveValue("draft-secret");
    requestMutationMock.mockResolvedValueOnce({ ok: true });
    fireEvent.click(dialog.getByRole("button", { name: "Test connection" }));
    expect(await dialog.findByText(success)).toBeVisible();
    fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    dialog = await openEditor();
    expect(dialog.queryByText(success)).not.toBeInTheDocument();
    expect(dialog.getByLabelText("Secret Key", { exact: true })).toHaveValue("");
    expect(requestMutationMock.mock.calls.every(([action]) => action === "settings.observability.test")).toBe(true);
  });

  it("applies the full save response, keeps runtime state separate, and restarts native hosts only on request", async () => {
    const payload: SettingsPayload = {
      ...langfuseSettings({ enabled: true, active_enabled: true }), surface: "native",
      runtime_capabilities: { can_restart_engine: true, can_open_logs: false, can_export_diagnostics: false },
    };
    const saved = saveResult(payload, { enabled: false });
    let current = payload;
    const fetchMock = stubHost(() => current);
    const onNativeEngineRestart = vi.fn(async () => "fresh-token");
    const onSettingsChange = vi.fn();
    requestMutationMock.mockResolvedValueOnce(saved);
    renderLangfuse({ onNativeEngineRestart, onSettingsChange });
    const dialog = await openEditor();
    fireEvent.click(dialog.getByRole("switch", { name: "Enable tracing" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onSettingsChange).toHaveBeenLastCalledWith(saved);
    expect(screen.getByText("Enabled", { exact: true })).toBeVisible();
    const pending = await openEditor(false);
    expect(pending.getByRole("switch", { name: "Enable tracing" })).not.toBeChecked();
    expect(pending.getByRole("status")).toHaveTextContent("Running: enabled · Saved. Restart to apply changes.");
    fireEvent.click(pending.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const restart = screen.getByRole("button", { name: "Restart" });
    expect(restart).toHaveClass("settings-restart-pending");
    expect(restart).toHaveAccessibleDescription("Saved. Restart to apply changes.");
    expect(onNativeEngineRestart).not.toHaveBeenCalled();
    current = { ...saved, requires_restart: false, restart_required_sections: [],
      observability: { ...saved.observability!, active_enabled: false, requires_restart: false } };
    fireEvent.click(restart);
    await waitFor(() => expect(onNativeEngineRestart).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("Disabled", { exact: true })).toBeVisible());
    expect(onSettingsChange).toHaveBeenLastCalledWith(current);
    expect(screen.getByRole("button", { name: "Restart" })).not.toHaveClass("settings-restart-pending");
    expect(fetchMock).toHaveBeenCalledWith("/api/settings", expect.objectContaining({ headers: { Authorization: "Bearer fresh-token" } }));
  });
});
