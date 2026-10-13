import { resolve } from "node:path";
import { cwd } from "node:process";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { Gallery, examples } from "@/dev/gallery/Gallery";
import { componentInventory } from "@/dev/gallery/inventory-plugin";
import { foundationPath } from "@/dev/gallery/inventory";
import { registeredChannelUiContributions } from "@/channel-plugins/registry";

const inventory = componentInventory(resolve(cwd(), ".."));

beforeEach(() => {
  window.history.replaceState({}, "", "/gallery.html");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("indexes shared component exports and their application and channel consumers", () => {
  const toggle = inventory.find((item) => item.path === `${foundationPath}toggle-button.tsx`);
  expect(toggle?.exports).toContain("ToggleButton");
  expect(toggle?.usedBy).toEqual(expect.arrayContaining([
    "webui/src/components/thread/WorkspaceControls.tsx",
    "nanobot/channels/linear/webui/LinearMemberAccessView.tsx",
  ]));
  expect(inventory.find((item) => item.path === "nanobot/channels/linear/webui/LinearMemberAccess.tsx")?.group)
    .toBe("Channels / linear");
  expect(inventory.find((item) => item.path === "nanobot/channels/linear/webui/index.tsx")?.exports).toContain("default");
  expect(inventory.find((item) => item.path === "webui/src/components/MarkdownTextRenderer.tsx")?.exports).toContain("default");
});

it("provides a live example for every foundation source and resolves every documented example source", () => {
  const previewed = new Set(examples.flatMap((example) => example.files));
  for (const item of inventory.filter((source) => source.group === "Foundations")) {
    expect(previewed.has(item.path), `Missing foundation example: ${item.path}`).toBe(true);
  }
  const known = new Set(inventory.map((source) => source.path));
  for (const file of previewed) expect(known.has(file), `Unknown example source: ${file}`).toBe(true);
});

it("finds a shared component by its name and renders its working variants", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => inventory }));
  render(<Gallery />);
  await screen.findByRole("heading", { name: "Button · 按钮" });
  await userEvent.type(screen.getByRole("searchbox", { name: "Search components" }), "toggle-button");
  expect(screen.getByRole("link", { name: /toggle-button/ })).toHaveAttribute("href", expect.stringContaining("toggle-button"));
  await userEvent.click(screen.getByRole("button", { name: "destructive", exact: true }));
  expect(screen.getByText("Button clicks: 1")).toBeVisible();
  expect(screen.getByRole("button", { name: "Unavailable", exact: true })).toBeDisabled();
});

it("lets the developer retry a failed inventory request", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: false })
    .mockResolvedValueOnce({ ok: true, json: async () => inventory }));
  render(<Gallery />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the inventory");
  await userEvent.click(screen.getByRole("button", { name: "Refresh inventory" }));
  expect(await screen.findByRole("heading", { name: "Button · 按钮" })).toBeVisible();
});

it("covers every registered channel and its presentation components", () => {
  const previewed = new Set(examples.flatMap((example) => example.files));
  for (const { channel, webui } of registeredChannelUiContributions()) {
    const entry = `nanobot/channels/${channel}/${webui}`;
    expect(inventory.find((source) => source.path === entry)?.exports).toContain("default");
    expect(previewed.has(entry), `Missing channel entry preview: ${channel}`).toBe(true);
  }
  for (const source of inventory.filter((item) => item.path.startsWith("nanobot/channels/"))) {
    const hasView = inventory.some((view) => previewed.has(view.path) && view.usedBy.includes(source.path));
    expect(previewed.has(source.path) || hasView, `Missing channel component preview: ${source.path}`).toBe(true);
  }
});

it("starts with working previews and lets the developer inspect source-only modules", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => inventory }));
  render(<Gallery />);
  await screen.findByRole("heading", { name: "Button · 按钮" });
  expect(screen.queryByRole("link", { name: /SettingsPage/ })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "All source · 源码" }));
  const sourceLink = screen.getByRole("link", { name: /SettingsPage Source only/ });
  // happy-dom does not follow anchor navigation or emit the browser's hashchange.
  act(() => {
    window.location.hash = sourceLink.getAttribute("href")!;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  expect(await screen.findByRole("heading", { name: "Source only · 暂无独立预览" })).toBeVisible();
  expect(screen.getByRole("link", { name: /Settings composition/ })).toBeVisible();

  await userEvent.click(screen.getByRole("button", { name: "Previews · 预览" }));
  expect(await screen.findByRole("region", { name: "Component preview" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Source only · 暂无独立预览" })).not.toBeInTheDocument();
});

it("opens bookmarked source entries and offers all source when a preview search has no match", async () => {
  const source = "webui/src/components/settings/SettingsView.tsx";
  window.history.replaceState({}, "", `/gallery.html#${new URLSearchParams({ component: source })}`);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => inventory }));
  render(<Gallery />);
  expect(await screen.findByRole("heading", { name: "SettingsView" })).toBeVisible();
  expect(screen.getByRole("link", { name: /^SettingsView Source only/ })).toHaveAttribute("aria-current", "page");

  await userEvent.click(screen.getByRole("button", { name: "Previews · 预览" }));
  await userEvent.type(screen.getByRole("searchbox", { name: "Search components" }), source);
  expect(screen.getByText("No matching previews.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Search all source" }));
  expect(screen.getByRole("link", { name: /^SettingsView Source only/ })).toBeVisible();
});

it("submits a message through the actual composer using only local preview state", async () => {
  const source = "webui/src/components/thread/ThreadComposer.tsx";
  window.history.replaceState({}, "", `/gallery.html#${new URLSearchParams({ component: source })}`);
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => inventory });
  vi.stubGlobal("fetch", fetch);
  render(<Gallery />);
  const input = await screen.findByRole("textbox", { name: "示例消息" });
  await userEvent.type(input, "Try the real composer{Enter}");
  expect(await screen.findByText("提交内容：Try the real composer")).toBeVisible();
  expect(input).toHaveValue("");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/__nanobot_components");
});

it("edits a pairing route without mounting a client or making a gateway mutation", async () => {
  const source = "webui/src/components/remote/PairRouteSettingsView.tsx";
  window.history.replaceState({}, "", `/gallery.html#${new URLSearchParams({ component: source })}`);
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => inventory });
  vi.stubGlobal("fetch", fetch);
  render(<Gallery />);
  await screen.findByRole("heading", { name: "PairRouteSettingsView · 配对路由" });
  const preview = within(screen.getByRole("region", { name: "Component preview" }));
  expect(preview.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await userEvent.click(preview.getByRole("combobox", { name: "Network route" }));
  await userEvent.click(screen.getByRole("option", { name: "VPN 路由" }));
  await userEvent.click(preview.getByRole("button", { name: "Save changes" }));
  expect(preview.getByRole("status")).toHaveTextContent("Saved");
  expect(preview.getByRole("button", { name: "Save changes" })).toBeDisabled();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/__nanobot_components");
});

it("uses the real provider manager and saves a new provider entirely in preview state", async () => {
  const source = "webui/src/components/settings/models/ProviderSettings.tsx";
  window.history.replaceState({}, "", `/gallery.html#${new URLSearchParams({ component: source })}`);
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => inventory });
  vi.stubGlobal("fetch", fetch);
  render(<Gallery />);
  await screen.findByRole("heading", { name: "ProvidersSettings · 管理提供商" });
  const preview = within(screen.getByRole("region", { name: "Component preview" }));
  await userEvent.click(preview.getByRole("button", { name: "Manage providers" }));
  let dialog = within(screen.getByRole("dialog", { name: "Manage providers" }));
  expect(dialog.getByRole("button", { name: "Anthropic", exact: true })).toBeVisible();
  expect(dialog.getByTestId("provider-logo-anthropic")).toBeVisible();
  expect(dialog.queryByRole("button", { name: "OpenAI", exact: true })).not.toBeInTheDocument();

  await userEvent.click(dialog.getByRole("button", { name: "Add provider", exact: true }));
  await userEvent.click(screen.getByRole("option", { name: "OpenAI", exact: true }));
  dialog = within(screen.getByRole("dialog", { name: "OpenAI" }));
  await userEvent.type(dialog.getByLabelText("API key", { selector: "input" }), "gallery-example-key");
  const apiURL = dialog.getByLabelText("API URL");
  await userEvent.clear(apiURL);
  await userEvent.type(apiURL, "https://preview.example/v1");
  await userEvent.click(dialog.getByRole("button", { name: "Add provider", exact: true }));

  dialog = within(await screen.findByRole("dialog", { name: "Manage providers" }));
  await userEvent.click(dialog.getByRole("button", { name: "OpenAI", exact: true }));
  expect(screen.getByLabelText("API URL")).toHaveValue("https://preview.example/v1");
  await userEvent.keyboard("{Escape}{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(preview.getByRole("button", { name: "Manage providers" })).toHaveFocus();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/__nanobot_components");
});

it("renders a registered channel's real secret fields and enable action without a gateway", async () => {
  const source = "nanobot/channels/telegram/webui/index.ts";
  window.history.replaceState({}, "", `/gallery.html#${new URLSearchParams({ component: source })}`);
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => inventory });
  vi.stubGlobal("fetch", fetch);
  render(<Gallery />);
  await screen.findByRole("heading", { name: "Telegram · 频道配置" });
  const preview = within(screen.getByRole("region", { name: "Component preview" }));
  const token = preview.getByLabelText("Bot token", { selector: "input" });
  expect(token).toHaveAttribute("type", "password");
  await userEvent.click(preview.getByRole("switch", { name: "Enable channel", exact: true }));
  expect(token).toHaveAttribute("aria-invalid", "true");
  expect(preview.getByRole("switch", { name: "Enable channel", exact: true })).not.toBeChecked();
  await userEvent.type(token, "gallery-example-token");
  await userEvent.click(preview.getByRole("switch", { name: "Enable channel", exact: true }));
  expect(preview.getByRole("switch", { name: "Enable channel", exact: true })).toBeChecked();
  await userEvent.click(preview.getByRole("button", { name: "Advanced", exact: true }));
  expect(preview.getByRole("group", { name: "Connection mode" })).toBeVisible();
  expect(preview.getByRole("radio", { name: "Long polling" })).toBeChecked();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/__nanobot_components");
});
