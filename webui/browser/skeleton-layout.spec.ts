import { expect, test, type Locator, type Page } from "@playwright/test";

const fixture = (surface: string, loading = false) => `/browser/fixture.html?case=skeleton&surface=${surface}${loading ? "&loading" : ""}`;
const status = (page: Page) => page.locator('[role="status"][aria-busy="true"]');
const catalogRows = {
  channels: [".settings-list-row", ".settings-list-row"],
  apps: ["article > .group", ".px-3.py-3"],
  cli: [".apps-catalog-row", ".px-3.py-3"],
  skills: ["button:has(h3)", ".px-2.py-3"],
};

async function settle(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(document.getAnimations()
      .filter((animation) => animation.effect?.getTiming().iterations !== Infinity)
      .map((animation) => animation.finished.catch(() => {})));
  });
}

async function box(locator: Locator) {
  await expect(locator).toBeVisible();
  return (await locator.boundingBox())!;
}

function sameBox(actual: { x: number; y: number; width: number; height: number }, expected: typeof actual) {
  for (const key of ["x", "y", "width", "height"] as const) {
    expect(Math.abs(actual[key] - expected[key]), key).toBeLessThan(0.5);
  }
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
}

const marketplaceSkills = ["skills_sh", "skillhub"].flatMap((provider) => Array.from({ length: 5 }, (_, index) => ({
  id: `${provider}:project-${index}`, skill_id: `project-${index}`, name: `Project Skill ${index + 1}`,
  source: "team/project-skills", provider, installs: 200, url: "https://example.com/skill",
  installed: false, install_supported: true, metric: "installs_total", rank: index + 1,
})));

for (const width of [390, 1440]) {
  for (const locale of ["en", "zh-CN"]) {
    test.describe(`${width}px ${locale}`, () => {
      test.use({ viewport: { width, height: 900 }, reducedMotion: "reduce", hasTouch: width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((language) => localStorage.setItem("nanobot.locale", language), locale);
      });

      test("catalog skeletons preserve loaded row, icon, title and action geometry", async ({ page }) => {
        for (const [surface, [loadedSelector, loadingSelector]] of Object.entries(catalogRows)) {
          await page.goto(fixture(surface));
          const loaded = page.locator(loadedSelector).first();
          const row = await box(loaded);
          const icon = await box(surface === "channels" ? loaded.locator('[data-testid^="channel-logo"]') : loaded.locator(":scope > :first-child"));
          const title = await box(loaded.locator("h3"));
          const action = width === 1440 || surface !== "skills" ? await box(loaded.locator(":scope > :last-child")) : null;
          await page.goto(fixture(surface, true));
          const skeleton = status(page).locator(loadingSelector).first();
          sameBox(await box(skeleton), row);
          sameBox(await box(skeleton.locator(":scope > :first-child")), icon);
          const placeholder = await box(skeleton.locator(":scope > :nth-child(2) [class*='bg-muted-foreground']").first());
          expect(placeholder.x).toBe(title.x);
          expect(placeholder.y + placeholder.height / 2).toBe(title.y + title.height / 2);
          if (action) sameBox(await box(skeleton.locator(":scope > :last-child")), action);
          await noOverflow(page);
        }
      });

      test("marketplace skeletons preserve groups, ranks and provider-specific trend columns", async ({ page }) => {
        let release = () => {};
        let pending: Promise<void> | undefined;
        await page.route("**/api/webui/skills/trending?**", async (route) => {
          await pending;
          await route.fulfill({ json: { period: "mixed", provider: "all", install_supported: true, skills: marketplaceSkills } });
        });
        await page.route("**/api/webui/skills/search?**", async (route) => {
          await pending;
          await route.fulfill({ json: { query: "project", provider: "all", install_supported: true,
            skills: marketplaceSkills.map((skill) => ({ ...skill, rank: undefined })) } });
        });
        await page.route("**/api/webui/skills/trends?**", (route) => route.fulfill({ json: { trends: {} } }));
        for (const view of ["grouped", "single", "search"]) {
          const open = async () => {
            await page.goto(fixture("marketplace"));
            if (view === "single") await page.getByRole("tab", { name: "skills.sh", exact: true }).click();
            if (view === "search") await page.locator("input").fill("project");
          };
          await open();
          const loaded = page.locator(".group.py-3\\.5");
          await expect(loaded).toHaveCount(view === "single" ? 5 : 10);
          const rows = await loaded.evaluateAll((elements) => elements.map((element) => {
            const r = element.getBoundingClientRect();
            const text = element.querySelector("h3")!.parentElement!.parentElement!.getBoundingClientRect();
            return { row: { x: r.x, y: r.y, width: r.width, height: r.height }, text: { x: text.x, width: text.width } };
          }));
          pending = new Promise<void>((resolve) => { release = resolve; });
          try {
            await open();
            const skeletons = status(page).locator(".py-3\\.5");
            await expect(skeletons).toHaveCount(rows.length);
            for (let index = 0; index < rows.length; index++) {
              sameBox(await box(skeletons.nth(index)), rows[index].row);
              const text = await box(skeletons.nth(index).locator(".flex-1"));
              expect(text.x).toBe(rows[index].text.x);
              expect(text.width).toBe(rows[index].text.width);
            }
            await noOverflow(page);
          } finally { release(); pending = undefined; }
          await page.goto("about:blank");
        }
      });

      test("model catalog skeletons follow single-line official and two-line managed options", async ({ page }) => {
        let release = () => {};
        let pending: Promise<void> | undefined;
        await page.route("**/api/settings/provider-models?**", async (route) => {
          await pending;
          const provider = new URL(route.request().url()).searchParams.get("provider");
          await route.fulfill({ json: { provider, status: "available", source: "api", catalog_kind: "live",
            models: [0, 1, 2].map((index) => ({ id: `project-${index}`,
              ...(provider === "anthropic" ? { label: `Project ${index}`, description: "Code assistance" } : {}) })) } });
        });
        for (const surface of ["models", "models-compact"]) {
          await page.goto(fixture(surface));
          await page.getByRole("combobox").click();
          const loaded = page.getByRole("option").first();
          await expect(loaded).toBeVisible();
          await settle(page);
          const row = await box(loaded);
          const icon = await box(loaded.locator(":scope > :first-child > :first-child"));
          pending = new Promise<void>((resolve) => { release = resolve; });
          try {
            await page.goto(fixture(surface));
            await page.getByRole("combobox").click();
            await expect(status(page)).toBeVisible();
            await settle(page);
            const skeleton = status(page).locator(".px-2.py-1\\.5").first();
            sameBox(await box(skeleton), row);
            sameBox(await box(skeleton.locator(":scope > :first-child")), icon);
            await noOverflow(page);
          } finally { release(); pending = undefined; }
          await page.goto("about:blank");
        }
      });

      test("MCP tools preserve the localized toolbar and checkbox rows", async ({ page }) => {
        await page.goto(fixture("tools"));
        const loaded = page.getByRole("tabpanel");
        await expect(loaded.getByRole("checkbox")).toHaveCount(6);
        await settle(page);
        const row = await box(loaded.locator("label:has(input[type=checkbox])").first());
        const search = await box(loaded.locator("input:not([type=checkbox])"));
        await page.goto(fixture("tools", true));
        await expect(status(page)).toBeVisible();
        await settle(page);
        sameBox(await box(status(page).locator(".min-h-11").first()), row);
        sameBox(await box(status(page).locator("[aria-hidden] > .flex > :first-child")), search);
        await noOverflow(page);
      });

      test("directory loading preserves the centered whole-row viewport and scrollbar gutter", async ({ page }) => {
        let release = () => {};
        let blocked = false;
        const pending = new Promise<void>((resolve) => { release = resolve; });
        await page.route("**/api/workspaces/directories?**", async (route) => {
          if (blocked) await pending;
          const directory = new URL(route.request().url()).searchParams.get("path")!;
          await route.fulfill({ json: { path: directory, parent: "/srv", host: "dev-server", platform: "Linux", truncated: false,
            entries: Array.from({ length: 30 }, (_, index) => ({ name: `project-${index}`, path: `${directory}/project-${index}` })) } });
        });
        const open = async () => {
          await page.goto(fixture("workspace"));
          await page.getByTestId("skeleton-fixture").getByRole("button").first().click();
        };
        await open();
        await expect(page.getByRole("option").first()).toBeVisible();
        await settle(page);
        const row = await box(page.getByRole("option").first());
        blocked = true;
        try {
          await open();
          await expect(page.locator(".workspace-directory-loading")).toBeVisible();
          await settle(page);
          sameBox(await box(page.locator(".workspace-directory-loading [aria-hidden] > div").first()), row);
          await noOverflow(page);
        } finally { release(); }
      });

      test("file preview skeletons follow code gutters and Markdown controls", async ({ page }) => {
        await page.goto(fixture("file"));
        await expect(page.getByTestId("viewport-code-rows")).toBeVisible();
        const source = await box(page.locator("pre"));
        const code = await box(page.locator("[data-highlighted]"));
        await page.goto(fixture("file", true));
        sameBox(await box(status(page).locator(".font-mono")), source);
        const line = await box(status(page).locator(".font-mono > div > :last-child").first());
        expect(line.x).toBe(code.x);
        await noOverflow(page);
        await page.goto(fixture("markdown"));
        const heading = await box(page.getByRole("heading", { name: "Project overview" }));
        const controls = await box(page.getByTestId("file-preview-panel").locator(":scope > div").first());
        await page.goto(fixture("markdown", true));
        sameBox(await box(status(page).locator("[aria-hidden] > .flex").first()), controls);
        const title = await box(status(page).locator(".h-7 > div"));
        expect(title.x).toBe(heading.x);
        expect(title.y + title.height / 2).toBe(heading.y + heading.height / 2);
        await noOverflow(page);
        await page.goto(fixture("markdown"));
        await expect(page.getByRole("heading", { name: "Project overview" })).toBeVisible();
        await page.getByTestId("file-preview-panel").locator(".segmented-control button").nth(1).click();
        await expect(page.getByTestId("viewport-code-rows")).toBeVisible();
        const markdownSource = await box(page.locator("pre"));
        await page.getByTestId("reload-preview").click();
        const markdownLoading = await box(status(page).locator(".font-mono"));
        for (const key of ["x", "y", "width"] as const) expect(markdownLoading[key]).toBe(markdownSource[key]);
      });
    });
  }
}
