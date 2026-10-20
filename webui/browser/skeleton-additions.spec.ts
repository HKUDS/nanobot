import { expect, test, type Locator, type Page } from "@playwright/test";

const fixture = (surface: string, state = "loaded", extra = "") => `/browser/fixture.html?case=skeleton-additions&surface=${surface}&state=${state}${extra}`;
const status = (page: Page) => page.locator('[role="status"][aria-busy="true"]');

async function settle(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(document.getAnimations().filter((animation) => animation.effect?.getTiming().iterations !== Infinity)
      .map((animation) => animation.finished.catch(() => {})));
  });
}

async function boxes(locator: Locator) {
  await expect(locator.first()).toBeVisible();
  return locator.evaluateAll((elements) => elements.map((element) => {
    const { x, y, width, height } = element.getBoundingClientRect();
    return { x, y, width, height };
  }));
}

function sameBoxes(actual: Awaited<ReturnType<typeof boxes>>, expected: typeof actual) {
  expect(actual).toHaveLength(expected.length);
  for (let index = 0; index < actual.length; index++) for (const key of ["x", "y", "width", "height"] as const) {
    expect(Math.abs(actual[index][key] - expected[index][key]), `row ${index} ${key}`).toBeLessThan(0.5);
  }
}

async function accessibleSkeleton(page: Page) {
  await expect(status(page).first()).toBeVisible();
  expect(await status(page).first().getAttribute("aria-label")).toBeTruthy();
  await expect(status(page).first().locator(".animate-pulse")).toHaveAttribute("aria-hidden", "true");
  expect(await status(page).first().locator(".animate-pulse").evaluate((element) => getComputedStyle(element).animationName)).toBe("none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
}

for (const width of [390, 1440]) for (const locale of ["en", "zh-CN"]) {
  test.describe(`${width}px ${locale} new first-load skeletons`, () => {
    test.use({ viewport: { width, height: 1000 }, reducedMotion: "reduce", hasTouch: width === 390 });
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((language) => localStorage.setItem("nanobot.locale", language), locale);
      await page.clock.setFixedTime(new Date("2026-10-19T12:00:00Z"));
    });

    test("sidebar rows preserve comfortable, compact and touch density", async ({ page }) => {
      for (const extra of ["", "&compact"]) {
        await page.goto(fixture("chats", "loaded", extra));
        await settle(page);
        const loaded = await boxes(page.locator("[data-chat-row]"));
        await page.goto(fixture("chats", "loading", extra));
        await settle(page);
        sameBoxes((await boxes(page.locator("[data-chat-skeleton-row]"))).slice(0, loaded.length), loaded);
        await accessibleSkeleton(page);
      }
    });

    test("settings sections preserve their loaded row layout", async ({ page }, testInfo) => {
      for (const section of ["appearance", "notifications", "capabilities", "runtime", "advanced", "overview", "models", "about"]) {
        const extra = `&section=${section}${section === "notifications" ? "&notificationPermission=granted" : ""}`;
        await page.goto(fixture("settings", "loaded", extra));
        const target = page.locator("[data-settings-section]");
        if (section === "notifications") {
          await page.context().grantPermissions(["notifications"]);
          await page.evaluate(async () => {
            await navigator.serviceWorker.register("/sw.js", { scope: "/browser/" });
            await navigator.serviceWorker.ready;
            window.dispatchEvent(new Event("focus"));
          });
          await expect(target.getByRole("status")).toBeEmpty();
          await expect(target.getByRole("switch")).toHaveCount(2);
          await expect(target.getByRole("switch").first()).toBeEnabled();
        }
        if (section === "runtime") await expect(page.locator('[data-settings-section] button').filter({ hasText: locale === "en" ? "Start API server" : "启动 API 服务" })).toBeVisible();
        await settle(page);
        const selector = section === "overview" ? "section button.group" : section === "models" ? '[data-testid^="model-call-order-row"], .settings-footer' : section === "about" ? ".settings-list-row" : ".settings-row";
        const notificationDetails = section === "notifications" ? ", .settings-list-inset > .border-t, section > p" : "";
        const loaded = await boxes(target.locator(selector + notificationDetails));
        const loadedControls = section === "notifications" ? await boxes(target.getByRole("switch")) : null;
        await page.goto(fixture("settings", "loading", extra));
        await settle(page);
        const skeletonSelector = section === "overview" ? "[data-overview-skeleton-row]" : section === "models" ? "[data-model-preset-skeleton], .settings-footer" : section === "about" ? ".settings-list-row" : "[data-settings-skeleton-row]";
        const skeleton = await boxes(target.locator(skeletonSelector + notificationDetails));
        sameBoxes(skeleton, loaded);
        if (loadedControls) {
          const skeletonControls = await boxes(target.locator("[data-skeleton-switch]"));
          sameBoxes(skeletonControls, loadedControls);
          await testInfo.attach("notifications-layout", { body: JSON.stringify({ loaded, skeleton, loadedControls, skeletonControls }, null, 2), contentType: "application/json" });
        }
        await accessibleSkeleton(page);
      }
    });

    test("calendar and task skeletons retain their toolbar and real date grid", async ({ page }) => {
      for (const nextMonth of [false, true]) {
        const open = async (state: string) => {
          await page.goto(fixture("automations", state));
          if (nextMonth) await page.getByRole("button", { name: locale === "en" ? "Next month" : "下个月" }).click();
          await settle(page);
        };
        await open("loaded");
        const toolbar = await boxes(page.locator(".automation-panel-toolbar"));
        const nav = await boxes(page.locator(".automation-calendar-navigation"));
        const grid = width === 1440 ? await boxes(page.locator(".automation-calendar-day")) : null;
        if (grid) expect(grid).toHaveLength(nextMonth ? 42 : 35);
        const agenda = !nextMonth && width === 390 ? await boxes(page.locator(".automation-calendar-agenda li")) : null;
        await open("loading");
        sameBoxes(await boxes(page.locator(".automation-panel-toolbar")), toolbar);
        sameBoxes(await boxes(page.locator(".automation-calendar-navigation")), nav);
        if (grid) sameBoxes(await boxes(page.locator(".automation-calendar-day")), grid);
        if (agenda) sameBoxes(await boxes(page.locator("[data-agenda-skeleton-row]")), agenda);
        await accessibleSkeleton(page);
      }
      await page.goto(fixture("automations"));
      await page.locator(".automation-view-switch button").first().click();
      await settle(page);
      const rows = await boxes(page.locator('section[aria-label] button[aria-haspopup="dialog"]'));
      await page.goto(fixture("automations", "loading"));
      await page.locator(".automation-view-switch button").first().click();
      await settle(page);
      sameBoxes(await boxes(page.locator("[data-automation-task-skeleton]")), rows);
    });

    test("skill detail keeps the known summary and matches the toggle and instructions disclosure", async ({ page }) => {
      const open = async (state: string) => {
        await page.goto(fixture("skill-detail", state));
        await page.getByRole("button", { name: locale === "en" ? "Open details for project-review" : "查看 project-review 详情" }).click();
        await settle(page);
      };
      await open("loaded");
      await expect(page.getByRole("dialog").getByRole("switch")).toBeEnabled();
      const toggle = await boxes(page.getByRole("dialog").getByRole("switch").locator(".."));
      const instructions = await boxes(page.getByRole("dialog").getByRole("button", { name: /SKILL.md/ }).locator(".."));
      const title = await boxes(page.getByRole("dialog").getByRole("heading", { name: "project-review" }));
      await open("loading");
      await expect(page.getByRole("dialog").getByText("Review the repository and summarize actionable changes.")).toBeVisible();
      sameBoxes(await boxes(page.locator("[data-skill-toggle-skeleton]")), toggle);
      sameBoxes(await boxes(page.locator("[data-skill-instructions-skeleton]")), instructions);
      sameBoxes(await boxes(page.getByRole("dialog").getByRole("heading", { name: "project-review" })), title);
      await accessibleSkeleton(page);
    });

    test("session automation and Linear members keep row and action alignment", async ({ page }) => {
      for (const surface of ["session-jobs", "linear-members"]) {
        const open = async (state: string) => {
          await page.goto(fixture(surface, state));
          if (surface === "session-jobs") await page.getByRole("button", { name: locale === "en" ? "Session details" : "会话详情" }).click();
          else await page.locator("button[aria-expanded]").first().click();
          await settle(page);
        };
        await open("loaded");
        const rows = await boxes(surface === "session-jobs" ? page.getByRole("dialog").locator('button[aria-haspopup="dialog"]') : page.locator(".settings-row"));
        await open("loading");
        sameBoxes(await boxes(page.locator(surface === "session-jobs" ? "[data-session-job-skeleton]" : "[data-member-skeleton-row]")), rows);
        await accessibleSkeleton(page);
      }
    });

    test("cached settings and lists stay visible during background refresh", async ({ page }) => {
      for (const surface of ["settings", "chats", "automations", "session-jobs", "linear-members"]) {
        await page.goto(fixture(surface, "refresh"));
        if (surface === "session-jobs") await page.getByRole("button", { name: locale === "en" ? "Session details" : "会话详情" }).click();
        if (surface === "linear-members") await page.locator("button[aria-expanded]").first().click();
        await settle(page);
        await expect(status(page)).toHaveCount(0);
        await expect(surface === "settings" || surface === "linear-members" ? page.getByRole("switch").first() : page.getByText("Project summary", { exact: true }).first()).toBeVisible();
      }
    });
  });
}
