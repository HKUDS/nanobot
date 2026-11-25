import { expect, test, type Page } from "@playwright/test";
import { localeDirection, supportedLocales } from "../src/i18n/config";

async function selectRadio(page: Page, group: string, name: string) {
  const radio = page.getByRole("radiogroup", { name: group }).getByRole("radio", { name, exact: true });
  await radio.locator("..").click();
  await expect(radio).toBeChecked();
  await expect(radio).toBeFocused();
}

async function selectToolType(page: Page, name: string) {
  await selectRadio(page, "Tool type", name);
}

async function showAllTools(page: Page) {
  const readyOnly = page.getByRole("switch", { name: "Ready only" });
  if (await readyOnly.isChecked()) await readyOnly.click();
  await expect(readyOnly).not.toBeChecked();
}

test("settings reentry reuses tools immediately and refreshes expired catalogs without hiding rows", async ({ page }) => {
  const clockStart = Date.now();
  await page.clock.setFixedTime(clockStart);
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
  await expect(page.getByRole("switch", { name: "Ready only" })).toBeChecked();
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toHaveCount(0);
  await selectToolType(page, "CLI Apps");
  await expect(page.getByRole("heading", { name: "Fixture CLI", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toHaveCount(0);
  await selectToolType(page, "Agent Plugins");
  await showAllTools(page);
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Fixture CLI", exact: true })).toHaveCount(0);
  expect(counts).toEqual({ cli: 1, mcp: 1 });
  await page.getByRole("button", { name: "Leave settings", exact: true }).click();
  await page.getByRole("button", { name: "Open settings", exact: true }).click();
  await selectToolType(page, "Agent Plugins");
  await showAllTools(page);
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toBeVisible();
  expect(counts).toEqual({ cli: 1, mcp: 1 });
  await page.getByRole("button", { name: "Leave settings", exact: true }).click();
  refresh = true;
  await page.clock.setFixedTime(clockStart + 31_000);
  await page.getByRole("button", { name: "Open settings", exact: true }).click();
  await selectToolType(page, "Agent Plugins");
  await showAllTools(page);
  await expect.poll(() => counts).toEqual({ cli: 2, mcp: 2 });
  await expect(page.getByRole("heading", { name: "Fixture plugin", exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "Loading apps…", exact: true })).toHaveCount(0);
  release();
  await expect(page.getByRole("heading", { name: "Updated plugin", exact: true })).toBeVisible();
  await selectToolType(page, "CLI Apps");
  await expect(page.getByRole("heading", { name: "Updated CLI", exact: true })).toBeVisible();
});


test("reveals MCP tools hidden by Ready only without switching tool type", async ({ page }) => {
  await page.route("**/api/settings/cli-apps", route => route.fulfill({ json: { apps: [{
    name: "fixture-cli", display_name: "Fixture CLI", category: "tools", description: "Fixture app",
    requires: "", source: "catalog", entry_point: "fixture-cli", install_supported: true,
    installed: true, available: true, status: "installed", skill_installed: false,
  }], installed_count: 1 } }));
  await page.route("**/api/settings/mcp-presets", route => route.fulfill({ json: { presets: [{
    name: "fixture-mcp", display_name: "Fixture MCP", category: "tools", description: "Fixture MCP tool",
    requires: "", transport: "stdio", source: "builtin", install_supported: true,
    installed: true, configured: true, enabled: false, available: false, status: "disabled",
    required_fields: [], docs_url: "", note: "", connection_summary: "",
  }], installed_count: 1 } }));
  await page.goto("/browser/fixture.html?case=tools-catalog&layout&lang=zh-CN");
  await expect(page.getByRole("heading", { name: "Fixture CLI", exact: true })).toBeVisible();
  const ready = page.getByRole("switch", { name: "仅显示就绪" });
  await expect(ready).toBeChecked();
  await selectRadio(page, "工具类型", "MCP");
  await expect(page.getByText("还没有就绪的工具", { exact: true })).toBeVisible();
  const search = page.getByRole("textbox", { name: "搜索工具" });
  await search.fill("fixture");
  await ready.click();
  await expect(search).toHaveValue("fixture");
  await expect(ready).not.toBeChecked();
  await expect(page.getByRole("radio", { name: "MCP", exact: true })).toBeChecked();
  await expect(page.getByRole("heading", { name: "Fixture MCP", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Fixture CLI", exact: true })).toHaveCount(0);
});


for (const { code: locale } of supportedLocales) {
  test(`keeps Apps section controls usable on narrow screens in ${locale}`, async ({ page }) => {
    const width = 320;
    await page.setViewportSize({ width, height: 800 });
    await page.route("**/api/settings/cli-apps", route => route.fulfill({ json: { apps: [], installed_count: 0 } }));
    await page.route("**/api/settings/mcp-presets", route => route.fulfill({ json: { presets: [], installed_count: 0 } }));
    await page.route("**/api/settings/nanobot-features", route => route.fulfill({ json: { features: [], enabled_count: 0 } }));
    await page.route("**/api/webui/skills/trending?**", route => route.fulfill({ json: { skills: [] } }));
    const controls = page.locator(".catalog-controls");
    async function expectControlsFit(count: number) {
      const targets = page.locator(".catalog-tabs > button, .catalog-controls label");
      await expect(targets).toHaveCount(count);
      const geometry = await targets.evaluateAll(elements => elements.map(element => {
        const bounds = element.getBoundingClientRect();
        return {
          label: element.textContent,
          left: bounds.left,
          right: bounds.right,
          fits: element.scrollWidth <= element.clientWidth
            && (!element.matches("button") || element.scrollHeight <= element.clientHeight),
        };
      }));
      expect(geometry.filter(item => item.left < 0 || item.right > width || !item.fits)).toEqual([]);
    }

    await page.goto(`/browser/fixture.html?case=tools-catalog&lang=${locale}`);
    const types = page.getByRole("radiogroup").getByRole("radio");
    const status = controls.getByRole("switch");
    await expect(types).toHaveCount(4);
    await expect(status).not.toBeChecked();
    await expectControlsFit(8);
    const cli = types.nth(1);
    await cli.locator("..").click();
    await expect(cli).toBeChecked();
    await expect(cli).toBeFocused();
    await page.keyboard.press(localeDirection(locale) === "rtl" ? "ArrowLeft" : "ArrowRight");
    await expect(types.nth(2)).toBeChecked();
    await expect(types.nth(2)).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(status).toBeFocused();
    await page.keyboard.press("Space");
    await expect(status).toBeChecked();
    await status.locator("..").locator(":scope > span").click();
    await expect(status).not.toBeChecked();
    await expect(status).toBeFocused();

    const sections = page.locator(".catalog-tabs").getByRole("button");
    await sections.nth(1).click();
    await expectControlsFit(8);
    const marketplace = controls.getByRole("radio").nth(1);
    await marketplace.locator("..").click();
    await expect(marketplace).toBeFocused();
    await expect(marketplace).toBeChecked();
    await expectControlsFit(8);

    await sections.nth(2).click();
    await expectControlsFit(4);
    await status.locator("..").locator(":scope > span").click();
    await expect(status).toBeChecked();
    await expect(status).toBeFocused();
  });
}


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


test("keeps navigation, control slots and full-width search stable when switching Apps sections", async ({ page }) => {
  await page.route("**/api/settings/cli-apps", route => route.fulfill({ json: { apps: [], installed_count: 0 } }));
  await page.route("**/api/settings/mcp-presets", route => route.fulfill({ json: { presets: [], installed_count: 0 } }));
  await page.route("**/api/settings/nanobot-features", route => route.fulfill({ json: { features: [], enabled_count: 0 } }));
  await page.goto("/browser/fixture.html?case=tools-catalog");
  await page.route("**/api/webui/skills/trending?**", route => route.fulfill({ json: { skills: [] } }));
  const sections = page.getByRole("group", { name: "Apps" });
  const selected = sections.getByRole("button", { pressed: true });
  const tools = sections.getByRole("button", { name: "Tools" });
  await tools.focus();
  for (const key of ["ArrowRight", "ArrowLeft"]) {
    await page.keyboard.press(key);
    await expect(tools).toBeFocused();
    await expect(tools).toHaveAttribute("aria-pressed", "true");
  }
  const field = page.locator(".catalog-search input");
  await expect(field).toBeVisible();
  const searchNode = (await field.elementHandle())!;
  for (const width of [1440, 800, 375, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await tools.click();
    const wide = width >= 800;
    let toolsSearch: Awaited<ReturnType<typeof catalogGeometry>>[0] | undefined;
    const names = ["Tools", "Skills", "Channels"];
    for (const [index, name] of names.entries()) {
      await expect(selected).toHaveText(name);
      await expect(selected).toBeFocused();
      await expect(field).toBeVisible();
      expect(await searchNode.evaluate(element => element === document.querySelector(".catalog-search input"))).toBe(true);
      await page.locator("[data-testid=settings-section-transition]").evaluate(async element => {
        await Promise.all(element.getAnimations().map(animation => animation.finished));
      });
      const geometry = await catalogGeometry(page);
      const [search, controls] = geometry;
      const navigation = (await sections.boundingBox())!;
      expect(search.x).toBe(navigation.x);
      expect(search.x + search.width).toBe(controls.x + controls.width);
      expect(search.y).toBe(controls.y + controls.height + (wide ? 12 : 8));
      if (name === "Tools") toolsSearch = search;
      else if (wide || name === "Skills") expect(search, `${width}px ${name}`).toEqual(toolsSearch);
      else {
        expect(controls.height).toBe(36);
        expect(search.y).toBeLessThan(toolsSearch!.y);
      }
      if (wide) expect(controls.y).toBe(navigation.y);
      else expect(navigation.width).toBe(search.width);
      expect(search.height).toBe(36);
      expect(search.radius).toBe("12px");
      expect(geometry.every(control => control.x >= 0 && control.x + control.width <= width)).toBe(true);
      if (name === "Skills") {
        await selectRadio(page, "Skills views", "Marketplace");
        const sources = page.getByRole("radiogroup", { name: "Skill source" });
        await expect(sources.getByRole("radio", { name: "All", exact: true })).toBeChecked();
        await page.keyboard.press("Tab");
        await expect(sources.getByRole("radio", { name: "All", exact: true })).toBeFocused();
        await page.keyboard.press("ArrowRight");
        await expect(sources.getByRole("radio", { name: "skills.sh" })).toBeFocused();
        await expect(sources.getByRole("radio", { name: "skills.sh" })).toBeChecked();
        await selectRadio(page, "Skill source", "All");
        expect(await catalogGeometry(page)).toEqual(geometry);
        expect(await searchNode.evaluate(element => element === document.querySelector(".catalog-search input"))).toBe(true);
        await selectRadio(page, "Skills views", "Installed");
        await selected.focus();
      }
      const next = names[index + 1];
      if (next) {
        await page.keyboard.press("Tab");
        await expect(sections.getByRole("button", { name: next })).toBeFocused();
        await page.keyboard.press("Enter");
      }
    }
  }
});

test("keeps channel names, local marks and click focus on a narrow viewport", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  const origin = new URL(baseURL!).origin;
  const externalImages: string[] = [];
  await page.route(url => url.origin !== origin, route => {
    if (route.request().resourceType() === "image") externalImages.push(route.request().url());
    return route.abort();
  });
  await page.route("**/api/settings/nanobot-features", route => route.fulfill({ json: {
    enabled_count: 1,
    features: [{
      name: "whatsapp_agent", display_name: "WhatsApp Agent Platform", type: "channel",
      enabled: true, installed: true, runtime_status: "failed", status: "enabled",
      install_supported: false, requires_restart: false,
    }, {
      name: "telegram", display_name: "Telegram", type: "channel",
      enabled: false, installed: false, status: "not_installed",
      install_supported: true, requires_dependencies: true, requires_restart: false,
    }, {
      name: "email", display_name: "Email", type: "channel",
      enabled: false, installed: true, configured: false, status: "not_enabled",
      install_supported: false, requires_restart: false,
    }, ...[
      ["linear", "Linear"], ["mattermost", "Mattermost"], ["qq", "QQ"], ["slack", "Slack"],
    ].map(([name, display_name]) => ({
      name, display_name, type: "channel",
      enabled: false, installed: true, status: "not_enabled",
      install_supported: false, requires_restart: false,
    }))],
  } }));
  await page.goto("/browser/fixture.html?case=tools-catalog&layout&section=channels");
  const name = page.getByRole("heading", { name: "WhatsApp Agent Platform", exact: true });
  await expect(name).toBeVisible();
  const settings = page.getByRole("button", { name: /View WhatsApp Agent Platform/ });
  await expect(settings).toHaveAccessibleDescription("Failed");
  expect(await name.evaluate(element => element.scrollWidth <= element.clientWidth && element.scrollHeight <= element.clientHeight)).toBe(true);
  const mark = page.locator("[data-testid=channel-logo-whatsapp_agent] img");
  await expect.poll(() => mark.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);

  const dialog = page.getByRole("dialog", { name: "Channels" });
  await settings.click();
  await expect(dialog).toBeFocused();
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(settings).toBeFocused();

  const enabledOnly = page.getByRole("switch", { name: "Enabled only" });
  await expect(enabledOnly).toBeChecked();
  await enabledOnly.click();
  await expect(enabledOnly).not.toBeChecked();
  await expect(enabledOnly).toBeFocused();
  for (const channel of ["linear", "mattermost", "qq"]) {
    const image = page.getByTestId(`channel-logo-${channel}`).locator("img");
    await image.scrollIntoViewIfNeeded();
    await expect(image).toHaveAttribute("src", `/brand/channels/${channel}.svg`);
    await expect.poll(() => image.evaluate(element => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  }
  const slackMark = page.getByTestId("channel-logo-slack");
  await slackMark.scrollIntoViewIfNeeded();
  await expect(slackMark).toHaveText("SL");
  const emailSwitch = page.getByRole("switch", { name: /Email/ });
  await emailSwitch.click();
  await expect(dialog).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(emailSwitch).toBeFocused();

  const telegram = page.getByRole("button", { name: /View Telegram/ });
  const install = page.getByRole("button", { name: "Install Telegram" });
  await telegram.click();
  await expect(telegram).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(install).toBeFocused();

  const skills = page.getByRole("group", { name: "Apps" }).getByRole("button", { name: "Skills" });
  await skills.click();
  await expect(page.getByLabel("Search installed skills")).toBeVisible();
  await expect(skills).toBeFocused();
  expect(externalImages).toEqual([]);
});

async function catalogGeometry(page: Page, startup = false) {
  const selectors = startup
    ? [".startup-search", ".startup-controls"]
    : [".catalog-search input", ".catalog-controls"];
  return Promise.all(selectors.map(selector => page.locator(selector).evaluate(element => {
    const rect = element.getBoundingClientRect();
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, radius: getComputedStyle(element).borderRadius };
  })));
}

for (const width of [390, 1440]) test(`Apps startup skeleton shares the loaded toolbar geometry at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/api/settings/cli-apps", route => route.fulfill({ json: { apps: [], installed_count: 0 } }));
  await page.route("**/api/settings/mcp-presets", route => route.fulfill({ json: { presets: [], installed_count: 0 } }));
  await page.route("**/api/settings/nanobot-features", route => route.fulfill({ json: { features: [], enabled_count: 0 } }));
  for (const section of ["apps", "skills", "channels"]) {
    const url = `/browser/fixture.html?case=tools-catalog&layout&section=${section}`;
    await page.goto(url);
    await expect(page.locator(".catalog-search input")).toBeVisible();
    const loaded = await catalogGeometry(page);
    await page.goto(`${url}&startup`);
    await expect(page.locator(".startup-search")).toBeVisible();
    expect(await catalogGeometry(page, true), section).toEqual(loaded);
  }
});

for (const width of [390, 1440]) test(`Apps and Automations share the conversation column at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/api/settings/cli-apps", route => route.fulfill({ json: { apps: [], installed_count: 0 } }));
  await page.route("**/api/settings/mcp-presets", route => route.fulfill({ json: { presets: [], installed_count: 0 } }));
  await page.route("**/api/webui/automations", route => route.fulfill({ json: { jobs: [] } }));

  const bounds = async (selector: string) => {
    const target = page.locator(selector);
    await expect(target).toBeVisible();
    const { x, width } = (await target.boundingBox())!;
    return { x, width };
  };
  const fixture = "/browser/fixture.html?case=tools-catalog&layout";
  await page.goto(fixture);
  const apps = await bounds(".catalog-search input");
  await page.goto(`${fixture}&section=automations`);
  expect(await bounds(".automation-panel")).toEqual(apps);
  expect(await bounds(".automation-create-composer .thread-composer-surface")).toEqual(apps);
  await expect(page.locator(width === 1440 ? ".automation-calendar-grid" : ".automation-calendar-agenda")).toBeVisible();
  await page.goto(`${fixture}&section=automations&startup`);
  expect(await bounds(".startup-calendar")).toEqual(apps);

  if (width === 1440) {
    await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
    await page.route("**/api/sessions/*/webui-thread?*", route => route.fulfill({ json: {
      schemaVersion: 3, projection: "events", events: [], has_more: false,
    } }));
    await page.routeWebSocket("**/answer-order-socket", route => route.onMessage(raw => {
      const frame = JSON.parse(String(raw));
      if (frame.type !== "attach") return;
      route.send(JSON.stringify({ event: "attached", chat_id: frame.chat_id }));
      route.send(JSON.stringify({ event: "user_message", chat_id: frame.chat_id,
        turn_id: "layout-turn", text: "An existing conversation", starts_turn: true,
      }));
    }));
    await page.goto("/browser/fixture.html?case=answer-order");
    expect(await bounds('[data-layout="thread"] .thread-composer-surface')).toEqual(apps);
  }
});
