import { expect, test } from "@playwright/test";

test("settings reentry reuses tools immediately and refreshes expired catalogs without hiding rows", async ({ page }) => {
  const counts = { cli: 0, mcp: 0 };
  let refresh = false;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/settings/cli-apps", async route => {
    counts.cli++;
    if (refresh) await gate;
    await route.fulfill({ json: { apps: [{
      name: "fixture-cli", display_name: refresh ? "Updated CLI" : "Fixture CLI", category: "tools",
      description: "Fixture app", requires: "", source: "catalog", entry_point: "fixture-cli",
      install_supported: true, installed: true, available: true, status: "installed", skill_installed: false,
    }], installed_count: 1 } });
  });
  await page.route("**/api/settings/mcp-presets", async route => {
    counts.mcp++;
    if (refresh) await gate;
    await route.fulfill({ json: { presets: [{
      name: "fixture-plugin", display_name: refresh ? "Updated plugin" : "Fixture plugin", category: "Plugin",
      description: "Fixture plugin", requires: "", transport: "stdio", source: "agent-plugin",
      install_supported: false, installed: true, configured: true, enabled: false, available: false,
      status: "disabled", required_fields: [], docs_url: "", note: "", connection_summary: "",
    }], installed_count: 1 } });
  });
  await page.goto("/browser/fixture.html?case=tools-catalog");
  await expect(page.getByRole("heading", { name: "Fixture CLI", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Ready", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "CLI Apps", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fixture CLI", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Agent Plugins", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Fixture CLI", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Leave settings", exact: true }).click();
  await page.getByRole("button", { name: "Open settings", exact: true }).click();
  await page.getByRole("button", { name: "Agent Plugins", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toBeVisible();
  expect(counts).toEqual({ cli: 1, mcp: 1 });
  await page.getByRole("button", { name: "Leave settings", exact: true }).click();
  refresh = true;
  await page.clock.setFixedTime(new Date(Date.now() + 31_000));
  await page.getByRole("button", { name: "Open settings", exact: true }).click();
  await page.getByRole("button", { name: "Agent Plugins", exact: true }).click();
  await expect.poll(() => counts).toEqual({ cli: 2, mcp: 2 });
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "Loading apps…", exact: true })).toHaveCount(0);
  release();
  await expect(page.getByRole("heading", { name: "Updated plugin", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "CLI Apps", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Updated CLI", exact: true })).toBeVisible();
});


test("shows all category labels on narrow screens in each locale", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.route("**/api/settings/cli-apps", route => route.fulfill({ json: { apps: [], installed_count: 0 } }));
  await page.route("**/api/settings/mcp-presets", route => route.fulfill({ json: { presets: [], installed_count: 0 } }));
  for (const locale of ["en", "es", "fr", "id", "ja", "ko", "pt-BR", "vi", "zh-CN", "zh-TW"]) {
    await page.goto(`/browser/fixture.html?case=tools-catalog&lang=${locale}`);
    const control = page.locator(".segmented-control").filter({ has: page.getByRole("button", { name: "CLI Apps", exact: true }) });
    await expect(control).toBeVisible();
    const geometry = await control.evaluate(element => {
      const bounds = element.getBoundingClientRect();
      return {
        left: bounds.left,
        right: bounds.right,
        buttons: Array.from(element.querySelectorAll("button"), button => ({
          text: button.textContent,
          fits: button.scrollWidth <= button.clientWidth,
        })),
      };
    });
    expect(geometry.left, locale).toBeGreaterThanOrEqual(0);
    expect(geometry.right, locale).toBeLessThanOrEqual(320);
    expect(geometry.buttons, locale).toHaveLength(4);
    expect(geometry.buttons.every(button => button.fits), locale).toBe(true);
  }
});


test("opens the generated plugin from its CLI app", async ({ page }) => {
  await page.route("**/api/settings/cli-apps", route => route.fulfill({ json: { apps: [{
    name: "fixture-cli", display_name: "Fixture CLI", category: "tools", description: "Fixture app",
    requires: "", source: "catalog", entry_point: "fixture-cli", install_supported: true,
    installed: true, available: true, status: "installed", skill_installed: true,
  }], installed_count: 1 } }));
  await page.route("**/api/settings/mcp-presets", route => route.fulfill({ json: { presets: [{
    name: "plugin-cli-app-fixture-cli", display_name: "Generated plugin", category: "Plugin",
    description: "Generated skill", requires: "", transport: "stdio", source: "agent-plugin",
    managed_by_cli: "fixture-cli", install_supported: false, installed: true, configured: true,
    enabled: true, available: true, status: "enabled", required_fields: [], docs_url: "", note: "", connection_summary: "",
  }], installed_count: 1 } }));
  await page.goto("/browser/fixture.html?case=tools-catalog");
  await expect(page.getByRole("heading", { name: "Fixture CLI", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "App ready", exact: true }).click();
  await page.getByRole("menuitem", { name: "Agent Plugin", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Generated plugin" })).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Disable" })).toBeVisible();
});
