import { expect, test, type Page } from "@playwright/test";

async function installPreview(page: Page) {
  await page.addInitScript(() => { localStorage.setItem("nanobot.locale", "en"); });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-transparency", value: "no-preference" }] });
  await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
  await page.route("**/api/sessions/*/webui-thread?*", route => {
    const topic = decodeURIComponent(new URL(route.request().url()).pathname.split("/")[3]).split(":")[1];
    return route.fulfill({ json: { schemaVersion: 3, projection: "events", events: [
      { event: "user_message", chat_id: topic, projection_id: `${topic}-prompt`, turn_id: "fixture-turn", starts_turn: true, text: `Question for ${topic}` },
      { event: "message", chat_id: topic, projection_id: `${topic}-answer`, turn_id: "fixture-turn", text: `Answer for ${topic}\n\n` + "A long conversation stays at its reading position.\n\n".repeat(25) },
    ] } });
  });
  await page.route("**/api/sessions/*/subagents?*", route => route.fulfill({ json: { tasks: /tasks|together|blocked/.test(route.request().url()) ? [{
    task_id: "preview-task", revision: 1, label: "Check navigation", task_description: "Synthetic preview task",
    origin_turn_id: "fixture-turn", origin_message_id: "tasks-prompt", created_at: Date.now() / 1000, completed_at: null,
    state: "running", phase: "awaiting_model", elapsed_seconds: 12, iteration: 1, tool_events: [],
    usage: null, receipts: {}, result: null, partial: false, stop_reason: null, error: null,
  }] : [] } }));
}

async function select(page: Page, topic: string) {
  await page.getByRole("button", { name: topic, exact: true }).click();
  await expect(page.locator("main[data-session]")).toHaveAttribute("data-session", topic);
  await expect(page.getByText(`Question for ${topic}`, { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.hasAttribute("data-session-transition"))).toBe(false);
}

async function armGoalMotionFreeze(page: Page, state: "open" | "closed", time: number) {
  await page.evaluate(({ state, time }) => {
    document.addEventListener("animationstart", function pauseMotion(event) {
      const el = event.target;
      if (!(el instanceof HTMLElement) || !el.matches(`.goal-island-panel[data-state="${state}"]`)) return;
      for (const animation of el.getAnimations({ subtree: true })) { animation.pause(); animation.currentTime = time; }
      document.removeEventListener("animationstart", pauseMotion);
    });
  }, { state, time });
}

test("blocked goal remains visible until cleared and survives session switching", async ({ page }) => {
  await installPreview(page);
  await page.goto("/browser/fixture.html?case=session-transition");
  await select(page, "goal");
  await page.getByRole("button", { name: "Show full goal" }).click();
  const dialog = page.getByRole("dialog", { name: "Goal", exact: true });
  const body = dialog.locator(".goal-island-body");
  await body.evaluate(el => { el.scrollTop = el.scrollHeight; });
  expect(await body.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  // Emit a live goal event without an outside pointer click dismissing the open panel.
  await page.getByRole("button", { name: "Block goal" }).evaluate(button => (button as HTMLButtonElement).click());
  await expect(page.getByRole("status", { name: "Blocked · Waiting for a workspace permission decision." })).toBeVisible();
  await expect.poll(() => body.evaluate(el => el.scrollTop)).toBe(0);
  await expect(dialog.locator(".goal-island-status-icon")).toBeVisible();
  const reason = dialog.getByText("Waiting for a workspace permission decision.");
  await expect(reason).toBeVisible();
  expect(await reason.evaluate(el => {
    const body = el.closest(".goal-island-body")!;
    return el.getBoundingClientRect().bottom <= body.getBoundingClientRect().bottom;
  })).toBe(true);
  await page.keyboard.press("Escape");
  await select(page, "plain");
  await expect(page.locator(".goal-island")).toHaveCount(0);
  await select(page, "goal");
  await expect(page.locator('.goal-island[data-goal-status="blocked"]')).toBeVisible();
  await page.getByRole("button", { name: "Clear goal" }).click();
  await expect(page.locator(".goal-island")).toHaveCount(0);
});

for (const { width, topic } of [{ width: 1440, topic: "goal" }, { width: 390, topic: "blocked" }]) {
  test(`goal cancellation is reachable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await installPreview(page);
    await page.goto("/browser/fixture.html?case=session-transition&cancel-goal");
    await select(page, topic);
    await page.getByRole("textbox").fill("Keep this draft");
    await page.getByRole("button", { name: "Show full goal" }).click();
    const dialog = page.getByRole("dialog", { name: "Goal", exact: true });
    await dialog.evaluate(async el => { await Promise.all(el.getAnimations({ subtree: true }).map(animation => animation.finished)); });
    const cancel = dialog.getByRole("button", { name: "Cancel goal", exact: true });
    const panelBounds = await dialog.boundingBox();
    const buttonBounds = await cancel.boundingBox();
    expect(buttonBounds!.y).toBeGreaterThanOrEqual(panelBounds!.y);
    expect(buttonBounds!.y + buttonBounds!.height).toBeLessThanOrEqual(panelBounds!.y + panelBounds!.height);
    await cancel.focus();
    await page.keyboard.press("Enter");
    const confirm = page.getByRole("button", { name: "Confirm cancellation", exact: true });
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(page.locator(".goal-island")).toHaveCount(0);
    await expect(page.getByRole("textbox")).toHaveValue("Keep this draft");
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  });
}

for (const viewport of [{ width: 390, height: 844 }, { width: 844, height: 390 }]) {
  test(`long goal summaries leave the objective readable at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await installPreview(page);
    await page.goto("/browser/fixture.html?case=session-transition&long-goal");
    await select(page, "goal");
    await page.getByRole("button", { name: "Show full goal" }).click();
    const dialog = page.getByRole("dialog", { name: "Goal", exact: true });
    await dialog.evaluate(async el => { await Promise.all(el.getAnimations({ subtree: true }).map(animation => animation.finished)); });
    const bounds = await dialog.evaluate(el => {
      const title = el.querySelector(".goal-island-summary")!.getBoundingClientRect();
      const body = el.querySelector(".goal-island-body")!;
      const paragraph = body.querySelector("p")!;
      return { titleBottom: title.bottom, panel: el.getBoundingClientRect().toJSON(), body: body.getBoundingClientRect().toJSON(), lineHeight: Number.parseFloat(getComputedStyle(paragraph).lineHeight) };
    });
    expect(bounds.panel.height).toBeLessThanOrEqual(viewport.height / 4);
    expect(bounds.body.height).toBeGreaterThanOrEqual(bounds.lineHeight);
    expect(bounds.titleBottom).toBeLessThanOrEqual(bounds.body.top);
    expect(bounds.body.bottom).toBeLessThanOrEqual(bounds.panel.bottom);
    const body = dialog.locator(".goal-island-body");
    await body.hover();
    await page.mouse.wheel(0, 10_000);
    await expect(body).toHaveAttribute("data-overflow-top");
    await expect(body).not.toHaveAttribute("data-overflow-bottom");
  });
}

for (const width of [320, 390, 1440]) for (const dark of [false, true]) {
  test(`session motion preserves composer anchors at ${width}px ${dark ? "dark" : "light"}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await installPreview(page);
    await page.goto(`/browser/fixture.html?case=session-transition${dark ? "&dark" : ""}`);
    await expect(page.getByText("Question for plain", { exact: true })).toBeVisible();
    await select(page, "goal");
    await expect(page.getByRole("status", { name: "Goal: Keep the composer stable", exact: true })).toBeVisible();
    await select(page, "tasks");
    await expect(page.getByTestId("subagent-task-dock")).toBeVisible();
    await select(page, "plain");
    await page.getByRole("textbox").fill("Plain draft");
    const composer = await page.locator(".thread-composer-surface").boundingBox();
    const toolbar = await page.locator(".thread-composer-footer").boundingBox();
    const input = await page.locator(".thread-composer-input").boundingBox();
    expect(input!.y).toBeGreaterThan(0);
    expect(toolbar!.y + toolbar!.height).toBeLessThanOrEqual(844);
    expect((await page.getByTestId("thread-message-region").boundingBox())!.height).toBeGreaterThan(100);

    const sample = await page.evaluate(async () => {
      const start = document.startViewTransition.bind(document);
      let ready!: () => void;
      const captured = new Promise<void>(resolve => { ready = resolve; });
      document.startViewTransition = callback => {
        const transition = start(callback);
        void transition.ready.then(ready);
        return transition;
      };
      const goal = [...document.querySelectorAll("nav button")].find(button => button.textContent === "goal") as HTMLButtonElement;
      goal.click();
      await captured;
      document.startViewTransition = start;
      const animations = document.getAnimations().filter(animation => animation.effect instanceof KeyframeEffect && animation.effect.pseudoElement);
      const frames = animations.map(animation => ({
        target: (animation.effect as KeyframeEffect).pseudoElement,
        keyframes: (animation.effect as KeyframeEffect).getKeyframes(),
      }));
      for (const animation of animations) { animation.pause(); animation.currentTime = 100; }
      await new Promise(requestAnimationFrame);
      const transform = getComputedStyle(document.documentElement, "::view-transition-group(session-input)").transform;
      const inputMatrix = new DOMMatrix(transform);
      const frameHeight = Number.parseFloat(getComputedStyle(document.documentElement, "::view-transition-group(session-composer)").height);
      const threadOut = getComputedStyle(document.documentElement, "::view-transition-old(session-thread-0)").opacity;
      const threadIn = getComputedStyle(document.documentElement, "::view-transition-new(session-thread-0)").opacity;
      for (const animation of animations) animation.play();
      return { frames, scale: [inputMatrix.a, inputMatrix.d], frameHeight, threadOut: Number(threadOut), threadIn: Number(threadIn) };
    });
    expect(sample.scale).toEqual([1, 1]);
    expect(Math.abs(sample.frameHeight - composer!.height)).toBeLessThanOrEqual(1);
    expect(sample.threadOut).toBe(0);
    expect(sample.threadIn).toBeGreaterThan(0);
    expect(sample.threadIn).toBeLessThan(1);
    await expect.poll(() => page.evaluate(() => document.documentElement.hasAttribute("data-session-transition"))).toBe(false);
    const goalInput = await page.locator(".thread-composer-input").boundingBox();
    const goalToolbar = await page.locator(".thread-composer-footer").boundingBox();
    expect(Math.abs(goalInput!.y - input!.y)).toBeLessThanOrEqual(1);
    expect(Math.abs(goalToolbar!.y - toolbar!.y)).toBeLessThanOrEqual(1);
    await page.getByRole("textbox").fill("Goal draft\nsecond line\nthird line");
    await select(page, "tasks");
    await page.getByRole("textbox").fill("Tasks draft");
    await select(page, "plain");
    await expect(page.getByRole("textbox")).toHaveValue("Plain draft");
    await select(page, "goal");
    await expect(page.getByRole("textbox")).toHaveValue("Goal draft\nsecond line\nthird line");
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);

    await select(page, "together");
    await expect(page.getByTestId("subagent-task-dock")).toBeVisible();
    await page.getByRole("textbox").fill("Draft beside a running task");
    const beforeOpen = await page.locator(".thread-composer-surface").boundingBox();
    const island = await page.locator(".goal-island").boundingBox();
    const controls = await page.locator('[data-header-controls="end"]').boundingBox();
    expect(island!.y + island!.height < controls!.y || island!.y >= controls!.y + controls!.height || island!.x + island!.width <= controls!.x).toBe(true);
    await page.getByRole("button", { name: "Show full goal" }).click();
    const dialog = page.getByRole("dialog", { name: "Goal", exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Verify session navigation with real components.");
    await dialog.evaluate(async el => { await Promise.all(el.getAnimations({ subtree: true }).map(animation => animation.finished)); });
    expect(await dialog.locator(":scope > .goal-island-surface").evaluate(el => getComputedStyle(el, "::before").backdropFilter)).toContain("blur(20px)");
    const panel = await dialog.boundingBox();
    expect(panel!.x).toBeGreaterThanOrEqual(24);
    expect(panel!.x + panel!.width).toBeLessThanOrEqual(width - 24);
    expect(panel!.y + panel!.height).toBeLessThan(844);
    expect(panel!.height).toBeLessThanOrEqual(844 / 4);
    const heading = dialog.getByRole("heading", { name: "Keep the composer stable" });
    const headingPosition = await heading.boundingBox();
    if (width < 768) {
      expect(headingPosition!.y).toBeGreaterThanOrEqual(controls!.y + controls!.height);
      expect(await page.locator('[data-header-controls="end"] button').evaluateAll(buttons => buttons.every(button => {
        const rect = button.getBoundingClientRect();
        return button.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
      }))).toBe(true);
    }
    const typography = await dialog.evaluate(el => {
      const title = getComputedStyle(el.querySelector("h2")!);
      const body = getComputedStyle(el.querySelector(".goal-island-document p")!);
      return { title: Number.parseFloat(title.fontSize), body: Number.parseFloat(body.fontSize), titleFont: title.fontFamily, bodyFont: body.fontFamily };
    });
    expect(typography.title).toBeCloseTo(typography.body * 1.5, 1);
    expect(typography.titleFont).toBe(typography.bodyFont);
    const scrollBody = page.locator(".goal-island-body");
    expect(await scrollBody.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
    await expect(scrollBody).toHaveAttribute("data-overflow-bottom");
    await scrollBody.hover();
    await page.mouse.wheel(0, 10_000);
    await expect(scrollBody).toHaveAttribute("data-overflow-top");
    await expect(scrollBody).not.toHaveAttribute("data-overflow-bottom");
    expect(await heading.boundingBox()).toEqual(headingPosition);
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole("textbox")).toBeFocused();
    expect(await page.locator(".thread-composer-surface").boundingBox()).toEqual(beforeOpen);
    await expect(page.getByRole("textbox")).toHaveValue("Draft beside a running task");

    await select(page, "blocked");
    await expect(page.locator('.goal-island[data-goal-status="blocked"]')).toBeVisible();
    await page.getByRole("button", { name: "Show full goal" }).click();
    await expect(dialog.locator(".goal-island-reason p")).toHaveText("Waiting for a workspace permission decision.");
    const reasonColor = await dialog.locator(".goal-island-reason p").evaluate(el => getComputedStyle(el).color);
    expect(await dialog.locator(".goal-island-status-icon").evaluate(el => getComputedStyle(el).color)).toBe(reasonColor);
    await page.getByRole("textbox").click();
    await expect(dialog).not.toBeVisible();

    await page.emulateMedia({ reducedMotion: "reduce", contrast: "more" });
    await page.getByRole("button", { name: "Show full goal" }).click();
    await expect(dialog).toBeVisible();
    expect(await dialog.locator(":scope > .goal-island-surface").evaluate(el => getComputedStyle(el, "::before").backdropFilter)).toBe("none");
    await page.keyboard.press("Escape");
    await select(page, "plain");
    await expect(page.getByRole("textbox")).toHaveValue("Plain draft");
    await page.getByRole("button", { name: "Stream reply" }).click();
    await expect(page.getByText("Live reply continues", { exact: true })).toBeVisible();
  });
}

test("rapid navigation and cold history keep the latest target and its draft usable", async ({ page }) => {
  await installPreview(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/sessions/websocket%3Acold/webui-thread?*", async route => { await gate; await route.fallback(); });
  await page.goto("/browser/fixture.html?case=session-transition");
  await expect(page.getByText("Question for plain", { exact: true })).toBeVisible();
  await page.evaluate(() => {
    const buttons = [...document.querySelectorAll<HTMLButtonElement>("nav button")];
    for (const name of ["goal", "tasks", "plain", "cold"]) buttons.find(button => button.textContent === name)!.click();
  });
  await expect(page.locator("main[data-session]")).toHaveAttribute("data-session", "cold");
  await expect(page.getByRole("status", { name: "Loading conversation…" })).toBeVisible();
  await page.getByRole("textbox").fill("Cold draft remains editable");
  release();
  await expect(page.getByText("Question for cold", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveValue("Cold draft remains editable");
  await expect(page.locator("main[data-session]")).toHaveAttribute("data-session", "cold");
});

for (const width of [390, 1440]) {
  test(`goal notch follows the active workbench pane at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await installPreview(page);
    await page.goto("/browser/fixture.html?case=session-transition&workbench");
    await expect(page.locator(".goal-island")).toHaveCount(1);
    await expect(page.getByTestId("active-pane-composer").getByRole("textbox")).toBeVisible();
    await page.getByRole("button", { name: "Show full goal" }).click();
    await expect(page.getByRole("dialog", { name: "Goal", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "blocked", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Goal", exact: true })).toHaveCount(0);
    await expect(page.locator('.goal-island[data-goal-status="blocked"]')).toHaveCount(1);
    await page.getByRole("button", { name: "Show full goal" }).click();
    await expect(page.getByRole("dialog", { name: "Goal", exact: true })).toContainText("Waiting for a workspace permission decision.");
    const panel = await page.getByRole("dialog", { name: "Goal", exact: true }).boundingBox();
    expect(panel!.x).toBeGreaterThanOrEqual(0);
    expect(panel!.x + panel!.width).toBeLessThanOrEqual(width);
    expect(panel!.height).toBeLessThanOrEqual(844 / 4);
    await page.getByTestId("active-pane-composer").getByRole("textbox").click();
    await expect(page.getByRole("dialog", { name: "Goal", exact: true })).toHaveCount(0);
  });
}

for (const width of [390, 1440]) {
  test(`goal notch collapses to its summary before unmounting at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await installPreview(page);
    await page.goto("/browser/fixture.html?case=session-transition");
    await select(page, "goal");
    const trigger = page.getByRole("button", { name: "Show full goal" });
    const input = page.getByRole("textbox");
    await input.fill("Keep editing after closing the goal");
    const compact = await trigger.boundingBox();
    await trigger.click();
    const panel = page.locator(".goal-island-panel");
    await panel.evaluate(async el => { await Promise.all(el.getAnimations({ subtree: true }).map(animation => animation.finished)); });
    const expanded = await panel.locator(":scope > .goal-island-surface").boundingBox();
    await armGoalMotionFreeze(page, "closed", 0);
    await input.click();
    await expect(panel).toHaveAttribute("data-state", "closed");
    await expect.poll(() => panel.evaluate(el => el.getAnimations().some(animation => animation.playState === "paused"))).toBe(true);
    await panel.evaluate(el => { for (const animation of el.getAnimations({ subtree: true })) animation.currentTime = 120; });
    const middle = await panel.locator(":scope > .goal-island-surface").boundingBox();
    expect(middle!.height).toBeGreaterThan(compact!.height);
    expect(middle!.height).toBeLessThan(expanded!.height);
    expect(middle!.width).toBeGreaterThan(compact!.width);
    expect(middle!.width).toBeLessThan(expanded!.width);
    expect(await trigger.evaluate(el => getComputedStyle(el).opacity)).toBe("0");
    await expect(input).toBeFocused();
    await expect(input).toHaveValue("Keep editing after closing the goal");
    await panel.evaluate(el => { for (const animation of el.getAnimations({ subtree: true })) animation.finish(); });
    await expect(panel).toHaveCount(0);
    await expect(trigger).toBeVisible();
    expect(await trigger.evaluate(el => getComputedStyle(el).opacity)).toBe("1");
    await expect(input).toBeFocused();
  });
}

test("goal notch reverses interrupted motion from its rendered shape", async ({ page }) => {
  await installPreview(page);
  await page.goto("/browser/fixture.html?case=session-transition");
  await select(page, "goal");
  const trigger = page.getByRole("button", { name: "Show full goal" });
  const panel = page.locator(".goal-island-panel");
  const surface = panel.locator(":scope > .goal-island-surface");
  const input = page.getByRole("textbox");
  await input.fill("Interruptible goal details");
  await armGoalMotionFreeze(page, "open", 150);
  await trigger.click();
  await expect.poll(() => panel.evaluate(el => el.getAnimations().some(animation => animation.playState === "paused"))).toBe(true);
  const opening = await surface.boundingBox();
  await armGoalMotionFreeze(page, "closed", 0);
  await page.keyboard.press("Escape");
  await expect(panel).toHaveAttribute("data-state", "closed");
  await expect.poll(() => panel.evaluate(el => el.getAnimations().some(animation => animation.playState === "paused"))).toBe(true);
  const closingStart = await surface.boundingBox();
  expect(Math.abs(closingStart!.width - opening!.width)).toBeLessThan(1);
  expect(Math.abs(closingStart!.height - opening!.height)).toBeLessThan(1);
  await panel.evaluate(el => { for (const animation of el.getAnimations({ subtree: true })) animation.currentTime = 120; });
  const closing = await surface.boundingBox();
  await armGoalMotionFreeze(page, "open", 0);
  await trigger.click();
  await expect(panel).toHaveAttribute("data-state", "open");
  await expect.poll(() => panel.evaluate(el => el.getAnimations().some(animation => animation.playState === "paused"))).toBe(true);
  const reopening = await surface.boundingBox();
  expect(Math.abs(reopening!.width - closing!.width)).toBeLessThan(1);
  expect(Math.abs(reopening!.height - closing!.height)).toBeLessThan(1);
  await panel.evaluate(el => { for (const animation of el.getAnimations({ subtree: true })) animation.finish(); });
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(input).toBeFocused();
  await expect(input).toHaveValue("Interruptible goal details");
});
