import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { McpPresetInfo } from "@/lib/types";
import { installSettingsViewTestHooks, jsonResponse, renderSettingsView, requestMutationMock, settingsPayload } from "@/tests/settings-test-utils";

const preset: McpPresetInfo = {
  name: "docs", display_name: "Docs MCP", category: "productivity", description: "Docs",
  docs_url: "https://example.com", transport: "streamableHttp", auth: null, requires: "", note: "",
  install_supported: true, installed: true, configured: true, available: true, status: "configured",
  runtime_status: "connected", required_fields: [], connection_summary: "https://example.com/mcp",
  tool_count: 2, tool_names: ["search_docs", "write_note"], enabled_tools: ["*"], source: "custom",
};

function installProxySettings() {
  const settings = { ...settingsPayload(), runtime_config: { "network.proxy": null } };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/settings") return jsonResponse(settings);
    if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
    if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [preset], installed_count: 1 });
    return jsonResponse({});
  }));
  return { settings, saved: { ...settings, runtime_config: { "network.proxy": "http://127.0.0.1:7890" }, requires_restart: true } };
}

async function openMcpSetup() {
  fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
  fireEvent.click(await screen.findByRole("button", { name: "Manage Docs MCP" }));
  const parent = await screen.findByRole("dialog", { name: "Docs MCP" });
  fireEvent.click(within(parent).getByRole("tab", { name: "Connection" }));
  fireEvent.click(within(parent).getByRole("button", { name: "Configure proxy" }));
  return { parent, setup: await screen.findByRole("dialog", { name: "Shared proxy" }) };
}

describe("Inline shared proxy setup", () => {
  installSettingsViewTestHooks();

  it("keeps custom Provider fields across cancel and successful setup without enabling proxy", async () => {
    const user = userEvent.setup();
    const { settings, saved } = installProxySettings();
    renderSettingsView({ initialSection: "models", initialSettings: settings });
    await user.click(await screen.findByRole("button", { name: "Manage providers" }));
    await user.click(screen.getByRole("button", { name: "Add provider" }));
    await user.click(await screen.findByRole("button", { name: "Custom" }));
    const parent = screen.getByRole("dialog", { name: "Custom" });
    const name = within(parent).getByPlaceholderText("My model provider");
    const url = within(parent).getByPlaceholderText("https://api.example.com/v1");
    const key = within(parent).getByPlaceholderText("Enter API key");
    await user.type(name, "Keep this draft");
    await user.click(url);
    await user.paste("https://gateway.example/v1");
    await user.click(key);
    await user.paste("draft-key");
    await user.click(within(parent).getByRole("button", { name: "Advanced options" }));
    await user.click(within(parent).getByRole("button", { name: "Configure proxy" }));
    let setup = await screen.findByRole("dialog", { name: "Shared proxy" });
    let proxy = within(setup).getByRole("textbox");
    await user.click(proxy);
    await user.paste("http://127.0.0.1:7890");
    expect(proxy).toHaveValue("http://127.0.0.1:7890");
    await user.click(within(setup).getByRole("button", { name: "Cancel" }));
    expect(name).toHaveValue("Keep this draft");
    expect(url).toHaveValue("https://gateway.example/v1");
    expect(key).toHaveValue("draft-key");
    expect(requestMutationMock).not.toHaveBeenCalled();
    await user.click(within(parent).getByRole("button", { name: "Configure proxy" }));
    setup = await screen.findByRole("dialog", { name: "Shared proxy" });
    proxy = within(setup).getByRole("textbox");
    expect(proxy).toHaveValue("");
    await user.click(proxy);
    await user.paste("http://127.0.0.1:7890");
    requestMutationMock.mockResolvedValueOnce(saved);
    await user.click(within(setup).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Shared proxy" })).not.toBeInTheDocument());
    expect(await screen.findByRole("dialog", { name: "Custom" })).toBe(parent);
    expect(name).toHaveValue("Keep this draft");
    expect(url).toHaveValue("https://gateway.example/v1");
    expect(key).toHaveValue("draft-key");
    expect(within(parent).getByRole("switch", { name: "Use proxy" })).not.toBeChecked();
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(requestMutationMock).toHaveBeenCalledWith("settings.runtime_config.update", { values: { "network.proxy": "http://127.0.0.1:7890" } }, 20_000);
  });

  it("saves optional credentials from inline setup without enabling the consumer", async () => {
    const { settings, saved } = installProxySettings();
    renderSettingsView({ initialSection: "apps", initialSettings: settings });
    const { parent, setup } = await openMcpSetup();
    fireEvent.change(within(setup).getByRole("textbox", { name: "Shared proxy" }), { target: { value: "socks5://proxy:1080" } });
    fireEvent.click(within(setup).getByRole("button", { name: "Authentication (optional)" }));
    fireEvent.change(within(setup).getByLabelText("Username"), { target: { value: "user@org" } });
    fireEvent.change(within(setup).getByLabelText("Password"), { target: { value: "p:a@ss" } });
    expect(within(setup).getByLabelText("Password")).toHaveAttribute("type", "password");
    const encoded = "socks5://user%40org:p%3Aa%40ss@proxy:1080";
    requestMutationMock.mockResolvedValueOnce({ ...saved, runtime_config: { "network.proxy": encoded } });
    fireEvent.click(within(setup).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Shared proxy" })).not.toBeInTheDocument());
    expect(requestMutationMock).toHaveBeenCalledWith("settings.runtime_config.update", { values: { "network.proxy": encoded } }, 20_000);
    expect(within(parent).getByRole("switch", { name: "Use proxy" })).not.toBeChecked();
  });

  it("retains MCP tool selections when setup is cancelled", async () => {
    const { settings } = installProxySettings();
    renderSettingsView({ initialSection: "apps", initialSettings: settings });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Manage Docs MCP" }));
    const parent = await screen.findByRole("dialog", { name: "Docs MCP" });
    fireEvent.click(within(parent).getByRole("tab", { name: "Tools" }));
    fireEvent.click(within(parent).getByRole("checkbox", { name: "write_note" }));
    expect(within(parent).getByRole("checkbox", { name: "write_note" })).not.toBeChecked();
    fireEvent.click(within(parent).getByRole("tab", { name: "Connection" }));
    fireEvent.click(within(parent).getByRole("button", { name: "Configure proxy" }));
    const setup = await screen.findByRole("dialog", { name: "Shared proxy" });
    fireEvent.click(within(setup).getByRole("button", { name: "Cancel" }));
    fireEvent.click(within(parent).getByRole("tab", { name: "Tools" }));
    expect(within(parent).getByRole("checkbox", { name: "write_note" })).not.toBeChecked();
    expect(within(parent).getByRole("button", { name: "Save changes" })).toBeEnabled();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("keeps failed input and inline errors, blocks dismissal while saving and retries", async () => {
    const { settings, saved } = installProxySettings();
    renderSettingsView({ initialSection: "apps", initialSettings: settings });
    const { parent, setup } = await openMcpSetup();
    const input = within(setup).getByRole("textbox");
    const save = within(setup).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(input, { target: { value: "bad-address" } });
    requestMutationMock.mockRejectedValueOnce(new Error("Unsupported proxy scheme"));
    fireEvent.click(save);
    expect(await within(setup).findByRole("alert")).toHaveTextContent("Unsupported proxy scheme");
    expect(input).toHaveValue("bad-address");
    await waitFor(() => expect(input).toHaveFocus());
    fireEvent.change(input, { target: { value: "http://127.0.0.1:7890" } });
    let resolveSave!: (value: typeof saved) => void;
    requestMutationMock.mockImplementationOnce(() => new Promise((resolve) => { resolveSave = resolve; }));
    fireEvent.click(save);
    expect(within(setup).getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(input).toBeDisabled();
    fireEvent.keyDown(setup, { key: "Escape" });
    expect(setup).toBeInTheDocument();
    await act(async () => { resolveSave(saved); });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Shared proxy" })).not.toBeInTheDocument());
    expect(screen.getByRole("dialog", { name: "Docs MCP" })).toBe(parent);
    expect(within(parent).getByRole("switch", { name: "Use proxy" })).not.toBeChecked();
    expect(requestMutationMock).toHaveBeenLastCalledWith("settings.runtime_config.update", { values: { "network.proxy": "http://127.0.0.1:7890" } }, 20_000);
  });
});
