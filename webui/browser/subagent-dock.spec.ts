import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`keeps subtasks reachable through long replies, independent list scrolling and detail handoff at ${width}px`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=subagent-dock");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    const messages = page.getByTestId("thread-message-region");
    await expect(trigger).toContainText("Running: 3");
    await page.getByTestId("subagent-task-dock").evaluate(node => Promise.all(node.getAnimations().map(animation => animation.finished)));
    const original = (await trigger.boundingBox())!;
    expect(await messages.locator('[data-testid="subagent-task-dock"]').count()).toBe(0);
    await page.getByRole("button", { name: "追加长回复", exact: true }).click();
    await expect(messages.getByText(/主助手继续输出较长的说明/).first()).toBeAttached();
    await messages.evaluate(node => { node.scrollTop = 0; });
    await expect.poll(async () => Math.abs((await trigger.boundingBox())!.y - original.y)).toBeLessThan(1);
    await expect(trigger).toBeInViewport();
    await trigger.click();
    const tree = page.getByTestId("subagent-task-tree");
    await expect(tree).toBeVisible();
    const dock = page.getByTestId("subagent-task-dock");
    const panel = dock.getByRole("region", { name: "Subtasks", exact: true });
    await panel.evaluate(node => Promise.all(node.getAnimations({ subtree: true })
      .filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished)));
    const bounds = (await panel.boundingBox())!;
    const anchor = (await dock.boundingBox())!;
    expect(bounds.y).toBeGreaterThanOrEqual(0);
    expect(bounds.y + bounds.height).toBeCloseTo(anchor.y + anchor.height - 1, 0);
    expect(bounds.width).toBeGreaterThan(original.width);
    expect(bounds.height).toBeLessThanOrEqual(448);
    await expect(panel).toHaveAccessibleDescription("0 of 3 completed");
    await page.screenshot({ path: info.outputPath("subtask-tree.png") });
    const row = tree.locator('[data-subagent-id="preview-0"]');
    await row.click();
    const detail = page.getByRole("dialog", { name: "检查项目实现", exact: true });
    await expect(detail).toBeVisible();
    await expect(detail).toBeFocused();
    await detail.getByRole("button", { name: "Close", exact: true }).click();
    await expect(detail).toHaveCount(0);
    await expect(tree).toBeVisible();
    await expect(row).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(tree).toHaveCount(0);
    await expect(trigger).toBeFocused();

    await page.getByRole("button", { name: "增加任务", exact: true }).click();
    await trigger.click();
    await expect(tree.locator("[data-subagent-id]")).toHaveCount(23);
    const beforeScroll = await messages.evaluate(node => node.scrollTop);
    await tree.hover();
    await page.mouse.wheel(0, 3000);
    await expect.poll(() => tree.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
    await expect(tree.locator('[data-subagent-id="preview-22"]')).toBeInViewport();
    expect(await messages.evaluate(node => node.scrollTop)).toBe(beforeScroll);
    await page.keyboard.press("Escape");
    await expect(tree).toHaveCount(0);

    await page.getByRole("button", { name: "全部完成", exact: true }).click();
    await expect(trigger).toContainText("Completed: 23");
    await trigger.click();
    await expect(tree.locator('[data-task-state="done"]')).toHaveCount(23);
    await page.keyboard.press("Escape");
    await expect(tree).toHaveCount(0);
    const input = page.getByRole("textbox").first();
    await input.fill("The main conversation is still usable");
    await expect(input).toHaveValue("The main conversation is still usable");
    expect(await page.locator("body").evaluate(node => getComputedStyle(node).pointerEvents)).not.toBe("none");
    expect(errors).toEqual([]);
  });
}

test("keeps the portaled dock scoped to the active conversation and honors reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
  await page.goto("/browser/fixture.html?case=subagent-dock&portal&dark");
  const portal = page.getByTestId("preview-composer-portal");
  const trigger = portal.getByTestId("subagent-task-dock-trigger");
  await expect(trigger).toContainText("Running: 3");
  await trigger.click();
  const tree = page.getByTestId("subagent-task-tree");
  await expect(tree).toBeVisible();
  await expect(tree.locator(".loading-ring-arc").first()).toHaveCSS("animation-name", "none");
  await expect(portal.locator(".inline-disclosure")).toHaveCSS("transition-duration", "0s");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "切换活动面板", exact: true }).click();
  await expect(portal.getByTestId("subagent-task-dock")).toHaveCount(0);
  await expect(tree).toHaveCount(0);
  await page.getByRole("button", { name: "切换活动面板", exact: true }).click();
  await expect(trigger).toBeVisible();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "切换会话", exact: true }).click();
  await expect(portal.getByTestId("subagent-task-dock")).toHaveCount(0);
  await page.getByRole("button", { name: "切换会话", exact: true }).click();
  await expect(trigger).toContainText("Running: 3");
  await page.getByRole("button", { name: "模拟失败", exact: true }).click();
  await expect(trigger).toContainText("Running: 2");
  const results = page.getByTestId("thread-message-region").getByRole("region", { name: "Subtasks", exact: true });
  await results.getByRole("button", { name: /Review needed: 1/ }).click();
  const failedRow = results.getByRole("button", { name: /核对回归测试 Failed/ });
  expect((await failedRow.getByText("Failed", { exact: true }).boundingBox())!.width).toBeGreaterThan(16);
  await failedRow.click();
  await expect(page.getByRole("dialog", { name: "核对回归测试", exact: true }).getByRole("alert")).toHaveText("演示：测试执行失败，请打开详情检查。");
});

test("keeps the composer editable while the task drawer stays open", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=subagent-dock");
  await page.getByTestId("subagent-task-dock-trigger").click();
  await expect(page.getByTestId("subagent-task-tree")).toBeVisible();
  const input = page.getByRole("textbox").first();
  await input.click();
  await expect(page.getByTestId("subagent-task-tree")).toBeVisible();
  await expect(input).toBeFocused();
  await page.keyboard.type("Continue the conversation");
  await expect(input).toHaveValue("Continue the conversation");
  const imeEscapeAllowed = await input.evaluate(node => node.dispatchEvent(new KeyboardEvent("keydown", {
    key: "Escape", isComposing: true, bubbles: true, cancelable: true,
  })));
  expect(imeEscapeAllowed).toBe(true);
  await expect(page.getByTestId("subagent-task-dock-trigger")).toHaveAttribute("aria-expanded", "true");
});

for (const width of [1440, 390]) {
  test(`preserves the top detail layer and its opener across a breakpoint change from ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=subagent-dock");
    await page.getByTestId("subagent-task-dock-trigger").click();
    const row = page.getByTestId("subagent-task-tree").locator('[data-subagent-id="preview-1"]');
    await row.click();
    const detail = page.getByRole("dialog", { name: "核对回归测试", exact: true });
    await expect(detail).toBeFocused();
    await page.setViewportSize({ width: width > 639 ? 390 : 1440, height: 900 });
    await expect(detail).toBeVisible();
    await expect(detail).toBeFocused();
    await expect(page.getByRole("dialog")).toHaveCount(1);
    await detail.getByRole("button", { name: "Close", exact: true }).click();
    await expect(detail).toHaveCount(0);
    await expect(page.getByTestId("subagent-task-tree")).toBeVisible();
    await expect(row).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("subagent-task-tree")).toHaveCount(0);
    await expect(page.getByTestId("subagent-task-dock-trigger")).toBeFocused();
  });
}

test("keeps the task drawer above the composer inside a shortened visual viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/browser/fixture.html?case=subagent-dock");
  await page.evaluate(() => {
    document.documentElement.style.setProperty("--app-viewport-top", "0px");
    document.documentElement.style.setProperty("--app-viewport-height", "500px");
  });
  await page.getByTestId("subagent-task-dock-trigger").click();
  const panel = page.getByTestId("subagent-task-dock").getByRole("region", { name: "Subtasks", exact: true });
  const bounds = (await panel.boundingBox())!;
  const input = page.getByRole("textbox").first();
  const inputBounds = (await input.boundingBox())!;
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(inputBounds.y);
  expect(inputBounds.y + inputBounds.height).toBeLessThanOrEqual(500);
  await input.fill("Keyboard viewport remains usable");
  await expect(panel).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await expect(input).toBeFocused();
});

for (const width of [1440, 390]) {
  test(`retires completed live work into the conversation and restores only active tasks at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=subagent-dock&saved&past");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    await trigger.click();
    const tree = page.getByTestId("subagent-task-tree");
    await expect(tree.locator("[data-subagent-id]")).toHaveCount(3);
    await expect(tree).toContainText("检查项目实现");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "完成第一项", exact: true }).click();
    await expect(trigger).toContainText("Running: 2");
    await page.getByRole("button", { name: "新一轮消息", exact: true }).click();
    await expect(trigger).toContainText("Running: 2");
    await trigger.click();
    await expect(tree.locator("[data-subagent-id]")).toHaveCount(2);
    await expect(tree).toContainText("核对回归测试");
    await expect(tree).toContainText("整理交互建议");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "全部完成", exact: true }).click();
    await expect(trigger).toContainText("Completed: 2");
    await expect(trigger).toHaveCount(0, { timeout: 7000 });
    const results = page.getByTestId("thread-message-region").getByRole("region", { name: "Subtasks", exact: true });
    await results.getByRole("button", { name: /Subtasks/ }).click();
    await expect(results.locator("[data-subagent-id]")).toHaveCount(3);
    await results.getByRole("button", { name: /检查项目实现 Completed/ }).click();
    const detail = page.getByRole("dialog", { name: "检查项目实现", exact: true });
    await expect(detail).toContainText("第一项已完成并归档。");
    await detail.getByRole("button", { name: "Close", exact: true }).click();
    await expect(results.getByRole("button", { name: /检查项目实现 Completed/ })).toBeFocused();
    await page.reload();
    await expect(page.getByTestId("thread-message-region").getByText("随时查看，不必回翻聊天", { exact: true })).toBeAttached();
    await expect(trigger).toHaveCount(0);
    const restoredResults = page.getByTestId("thread-message-region").getByRole("region", { name: "Subtasks", exact: true });
    await restoredResults.getByRole("button", { name: /Subtasks/ }).click();
    await expect(restoredResults.getByRole("button", { name: /检查项目实现 Completed/ })).toBeVisible();
  });
}

test("does not retire a completed list or detail while it is being read", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=subagent-dock");
  await page.getByRole("button", { name: "模拟运行", exact: true }).click();
  const trigger = page.getByTestId("subagent-task-dock-trigger");
  await trigger.click();
  const tree = page.getByTestId("subagent-task-tree");
  await tree.locator('[data-subagent-id="preview-1"]').click();
  const detail = page.getByRole("dialog", { name: "核对回归测试", exact: true });
  await expect(detail).toContainText("保留详情与单任务停止", { timeout: 12000 });
  await detail.getByRole("button", { name: "Close", exact: true }).click();
  await expect(tree.locator('[data-subagent-id="preview-1"]')).toBeFocused();
  await expect(tree.locator('[data-task-state="done"]')).toHaveCount(3);
  await page.keyboard.press("Escape");
  await expect(tree).toHaveCount(0);
  await expect(trigger).toHaveCount(0);
  await expect(page.getByRole("textbox").first()).toBeFocused();
});

for (const width of [1440, 390]) {
  test(`keeps the reading position when results are archived and the live entry retires at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=subagent-dock");
    const body = page.getByTestId("thread-message-region");
    const anchor = body.getByText("主对话仍然可以正常输出和滚动。任务列表与消息区分别滚动，展开详情也不会取消正在执行的任务。", { exact: true }).nth(6);
    await body.hover();
    await page.mouse.wheel(0, -160);
    await expect.poll(() => body.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeGreaterThan(100);
    await expect(anchor).toBeInViewport();
    const before = (await anchor.boundingBox())!.y;
    await page.getByRole("button", { name: "完成第一项", exact: true }).click();
    await expect(page.getByTestId("subagent-task-dock-trigger")).toContainText("Running: 2");
    await expect.poll(async () => Math.abs((await anchor.boundingBox())!.y - before)).toBeLessThan(1);
    await page.getByRole("button", { name: "全部完成", exact: true }).click();
    await expect(page.getByTestId("subagent-task-dock-trigger")).toHaveCount(0, { timeout: 7000 });
    await expect.poll(async () => Math.abs((await anchor.boundingBox())!.y - before)).toBeLessThan(1);
  });
}

test("returns to the composer when completed work is dismissed on desktop blank space", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=subagent-dock");
  await page.getByRole("button", { name: "模拟运行", exact: true }).click();
  await page.getByTestId("subagent-task-dock-trigger").click();
  const tree = page.getByTestId("subagent-task-tree");
  await expect(tree.locator('[data-task-state="done"]')).toHaveCount(3, { timeout: 12000 });
  await page.locator("main").click({ position: { x: 4, y: 65 } });
  await expect(tree).toHaveCount(0);
  await expect(page.getByTestId("subagent-task-dock-trigger")).toHaveCount(0);
  await expect(page.getByRole("textbox").first()).toBeFocused();
});


test("keeps long task names, stop controls and detail handoff usable on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/browser/fixture.html?case=subagent-dock&long-labels");
  await page.getByTestId("subagent-task-dock-trigger").click();
  const panel = page.getByTestId("subagent-task-dock").getByRole("region", { name: "Subtasks", exact: true });
  const tree = page.getByTestId("subagent-task-tree");
  await expect(tree).toBeVisible();
  expect(await tree.evaluate(node => node.scrollWidth)).toBe(await tree.evaluate(node => node.clientWidth));
  const label = "核对多轮任务完成后的归档位置、长标题换行与独立详情入口";
  const row = tree.locator('[data-subagent-id="preview-0"]');
  await expect(row).toHaveAccessibleName(new RegExp(label));
  const stop = panel.getByRole("button", { name: `Stop ${label}`, exact: true });
  const stopBounds = (await stop.boundingBox())!;
  expect(stopBounds.width).toBeGreaterThanOrEqual(44);
  expect(stopBounds.height).toBeGreaterThanOrEqual(44);
  await row.click();
  const detail = page.getByRole("dialog", { name: label, exact: true });
  await expect(detail).toBeFocused();
  const close = detail.getByRole("button", { name: "Close", exact: true });
  const closeBounds = (await close.boundingBox())!;
  expect(closeBounds.width).toBeGreaterThanOrEqual(44);
  expect(closeBounds.height).toBeGreaterThanOrEqual(44);
  await close.click();
  await expect(row).toBeFocused();
});

test("exposes only the handle until requested and supports mouse drags without double toggling", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=subagent-dock");
  const trigger = page.getByTestId("subagent-task-dock-trigger");
  const tree = page.getByTestId("subagent-task-tree");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "增加任务", exact: true }).click();
  await expect(trigger).toContainText("Running: 23");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(tree).toHaveCount(0);
  await trigger.focus();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("textbox").first()).toBeFocused();
  const swipe = async (dx: number, dy: number) => {
    const bounds = (await trigger.boundingBox())!;
    const x = bounds.x + bounds.width / 2;
    const y = bounds.y + bounds.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + dx, y + dy, { steps: 8 });
    await page.mouse.up();
  };
  await swipe(40, 2);
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await swipe(0, -60);
  await expect(tree).toBeVisible();
  await page.getByTestId("subagent-task-dock").evaluate(node => Promise.all(node.getAnimations({ subtree: true })
    .filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished)));
  await swipe(0, 60);
  await expect(tree).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Space");
  await expect(tree).toBeVisible();
});

test.describe("touch task drawer", () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });
  test("opens upward, cancels a gesture, and scrolls tasks without closing the drawer", async ({ page }) => {
    await page.goto("/browser/fixture.html?case=subagent-dock");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    const tree = page.getByTestId("subagent-task-tree");
    const cdp = await page.context().newCDPSession(page);
    const swipe = async (target: typeof trigger, dy: number, cancel = false) => {
      const bounds = (await target.boundingBox())!;
      const x = bounds.x + bounds.width / 2;
      const y = bounds.y + bounds.height / 2;
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
      for (let step = 1; step <= 6; step++) {
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: y + dy * step / 6 }] });
      }
      await cdp.send("Input.dispatchTouchEvent", { type: cancel ? "touchCancel" : "touchEnd", touchPoints: [] });
    };
    await swipe(trigger, -60, true);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await swipe(trigger, -60);
    await expect(tree).toBeVisible();
    await page.getByTestId("subagent-task-dock").evaluate(node => Promise.all(node.getAnimations({ subtree: true })
      .filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished)));
    await swipe(trigger, 60);
    await expect(tree).toHaveCount(0);
    await page.getByRole("button", { name: "增加任务", exact: true }).click();
    await trigger.tap();
    await expect(tree.locator("[data-subagent-id]")).toHaveCount(23);
    await page.getByTestId("subagent-task-dock").evaluate(node => Promise.all(node.getAnimations({ subtree: true })
      .filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished)));
    await swipe(tree, -100);
    await expect.poll(() => tree.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await cdp.detach();
  });
});

for (const width of [1440, 390, 320]) {
  test(`aligns archived task columns with their disclosure at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/browser/fixture.html?case=subagent-dock&archived${width === 320 ? "&long-labels" : ""}`);
    if (width === 1440) await page.evaluate(() => { document.documentElement.style.zoom = "1.25"; });
    const archive = page.locator("[data-subagent-results]").first();
    const header = archive.locator("[data-subagent-results-summary]");
    const rows = archive.locator('[data-subagent-surface="archive"]');
    await expect(rows.first()).toBeHidden();
    await header.click();
    await expect(rows).toHaveCount(3);
    await expect(rows.first()).toBeVisible();
    await archive.evaluate(node => Promise.all(node.getAnimations({ subtree: true })
      .filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished)));
    const geometry = await archive.evaluate(node => {
      const header = node.querySelector<HTMLElement>("[data-subagent-results-summary]")!;
      const bounds = (element: Element) => element.getBoundingClientRect();
      return {
        overflow: node.scrollWidth > node.clientWidth,
        header: [header.children[0], header.children[1]].map(element => bounds(element).x),
        trailingEdge: bounds(header.lastElementChild!).right,
        rows: [...node.querySelectorAll('[data-subagent-surface="archive"]')].map(row => ({
          columns: [row.children[0], row.children[1]].map(element => bounds(element).x),
          elapsedRight: bounds(row.children[3]).right,
        })),
      };
    });
    expect(geometry.overflow).toBe(false);
    for (const row of geometry.rows) {
      row.columns.forEach((position, index) => expect(Math.abs(position - geometry.header[index])).toBeLessThan(0.5));
      expect(Math.abs(row.elapsedRight - geometry.trailingEdge)).toBeLessThan(0.5);
    }
    await rows.first().click();
    await expect(page.getByRole("dialog")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(rows.first()).toBeFocused();
    await header.click();
    await expect(rows.first()).toBeHidden();
  });
}
