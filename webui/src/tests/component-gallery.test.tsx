import { resolve } from "node:path";
import { cwd } from "node:process";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { Gallery, examples } from "@/dev/gallery/Gallery";
import { componentInventory } from "@/dev/gallery/inventory-plugin";
import { foundationPath } from "@/dev/gallery/inventory";

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
    "nanobot/channels/linear/webui/LinearMemberAccess.tsx",
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
