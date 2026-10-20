import { resolve } from "node:path";
import { cwd } from "node:process";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

import { Gallery } from "@/dev/gallery/Gallery";
import { initializeGalleryI18n } from "@/dev/gallery/i18n";
import { setAppLanguage } from "@/i18n";
import { componentInventory } from "@/dev/gallery/inventory-plugin";

const inventory = componentInventory(resolve(cwd(), ".."));

beforeAll(initializeGalleryI18n);
beforeEach(() => {
  window.history.replaceState({}, "", "/gallery.html#component=webui%2Fsrc%2Fcomponents%2Fui%2Finput.tsx");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function chooseChinese() {
  await act(async () => { await setAppLanguage("zh-CN"); });
}

it("switches the gallery interface and sample controls without replacing the active draft", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => inventory });
  vi.stubGlobal("fetch", fetch);
  render(<Gallery />);
  expect(await screen.findByRole("heading", { name: "Component gallery" })).toBeVisible();
  const preview = within(await screen.findByRole("region", { name: "Component preview" }));
  const input = preview.getAllByRole("textbox")[0];
  await userEvent.type(input, "Keep this draft 中文");
  const hash = window.location.hash;

  await chooseChinese();

  expect(await screen.findByRole("heading", { name: "组件图鉴" })).toBeVisible();
  expect(screen.getByRole("searchbox", { name: "搜索组件" })).toBeVisible();
  expect(screen.getByRole("button", { name: "刷新目录" })).toBeVisible();
  expect(input).toBeInTheDocument();
  expect(input).toHaveValue("Keep this draft 中文");
  expect(input).toHaveAccessibleName(/[\u4e00-\u9fff]/);
  expect(window.location.hash).toBe(hash);
  expect(document.documentElement.lang).toBe("zh-CN");
  expect(localStorage.getItem("nanobot.locale")).toBe("zh-CN");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("translates a visible inventory failure without retrying or losing search input", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: false });
  vi.stubGlobal("fetch", fetch);
  render(<Gallery />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the inventory");
  const search = screen.getByRole("searchbox", { name: "Search components" });
  await userEvent.type(search, "ThreadComposer");

  await chooseChinese();

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("无法加载组件目录"));
  expect(search).toHaveValue("ThreadComposer");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("keeps the visible assistant identity when translating existing interaction feedback", async () => {
  const source = "nanobot/channels/feishu/webui/FeishuAssistantsPanelView.tsx";
  window.history.replaceState({}, "", `/gallery.html#${new URLSearchParams({ component: source })}`);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => inventory }));
  render(<Gallery />);
  const preview = within(await screen.findByRole("region", { name: "Component preview" }));
  await userEvent.click(preview.getByRole("switch", { name: "Support assistant assistant" }));
  expect(await preview.findByText("Support assistant: off")).toBeVisible();

  await chooseChinese();

  expect(preview.getByText("Support assistant：已关闭")).toBeVisible();
});
