import { expect, test, type Locator } from "@playwright/test";

async function settledMotion(target: Locator) {
  await target.evaluate(() => document.fonts.ready);
  await expect.poll(() => target.evaluate(async node => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return node.getAnimations({ subtree: true }).filter(animation =>
      animation.effect?.getTiming().iterations !== Infinity && (animation.pending || animation.playState === "running")).length;
  })).toBe(0);
}

for (const width of [1440, 390]) {
  test(`keeps subtasks reachable through long replies, independent list scrolling and detail handoff at ${width}px`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=subagent-dock");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    const messages = page.getByTestId("thread-message-region");
    await expect(trigger).toContainText("Running: 3");
    await settledMotion(page.getByTestId("subagent-task-dock"));
    const original = (await trigger.boundingBox())!;
    const composer = page.locator(".thread-composer-surface");
    const composerBounds = (await composer.boundingBox())!;
    const corner = await composer.evaluate(node => Number.parseFloat(getComputedStyle(node).borderTopLeftRadius));
    expect(original.x - composerBounds.x).toBeGreaterThanOrEqual(corner);
    expect(composerBounds.x + composerBounds.width - original.x - original.width).toBeGreaterThanOrEqual(corner);
    expect(original.y + original.height).toBeCloseTo(composerBounds.y, 0);
    await page.screenshot({ path: info.outputPath("attached-handle-closed.png") });
    expect(await messages.locator('[data-testid="subagent-task-dock"]').count()).toBe(0);
    await page.getByRole("button", { name: "追加长回复", exact: true }).click();
    await expect(messages.getByText(/主助手继续输出较长的说明/).first()).toBeAttached();
    await messages.evaluate(node => { node.scrollTop = 0; });
    await expect.poll(async () => Math.abs((await trigger.boundingBox())!.y - original.y)).toBeLessThan(1);
    await expect(trigger).toBeInViewport();
    await trigger.click({ position: { x: original.width - 8, y: original.height / 2 } });
    const tree = page.getByTestId("subagent-task-tree");
    await expect(tree).toBeVisible();
    const dock = page.getByTestId("subagent-task-dock");
    const panel = dock.getByRole("region", { name: "Subtasks", exact: true });
    await settledMotion(panel);
    const bounds = (await panel.boundingBox())!;
    const anchor = (await dock.boundingBox())!;
    expect(bounds.y).toBeGreaterThanOrEqual(0);
    expect(bounds.y + bounds.height).toBeCloseTo(anchor.y + anchor.height, 0);
    expect(bounds.y + bounds.height).toBeCloseTo((await composer.boundingBox())!.y, 0);
    expect(bounds.width).toBeCloseTo(original.width, 0);
    expect(bounds.height).toBeLessThanOrEqual(448);
    await expect(panel).toHaveAccessibleDescription("0 of 3 completed");
    await page.mouse.move(1, 1);
    await page.screenshot({ path: info.outputPath("subtask-tree.png") });
    const row = tree.locator('[data-subagent-id="preview-0"]');
    await tree.getByText("read_file", { exact: true }).click();
    const detail = page.getByRole("dialog", { name: "检查项目实现", exact: true });
    await expect(detail).toBeVisible();
    await expect(detail).toBeFocused();
    await settledMotion(detail);
    const headerStop = detail.getByRole("button", { name: "Stop 检查项目实现", exact: true });
    await expect(detail).toHaveAccessibleDescription("Running");
    await expect(detail.getByText("Running", { exact: true }).locator("..")).toHaveClass(/\bsr-only\b/);
    await expect(headerStop.locator('[data-action-icon="stop"][data-active] .loading-ring-arc')).toBeVisible();
    const headerTitle = detail.getByRole("heading", { name: "检查项目实现", exact: true });
    const stopBounds = (await headerStop.boundingBox())!;
    const closeBounds = (await detail.getByRole("button", { name: "Close", exact: true }).boundingBox())!;
    expect(Math.abs(stopBounds.y + stopBounds.height / 2 - closeBounds.y - closeBounds.height / 2)).toBeLessThanOrEqual(1);
    expect((await headerTitle.boundingBox())!.x + (await headerTitle.boundingBox())!.width).toBeLessThanOrEqual(stopBounds.x);
    expect(stopBounds.x + stopBounds.width).toBeLessThanOrEqual(closeBounds.x);
    if (width === 390) {
      expect(stopBounds.width).toBeGreaterThanOrEqual(44);
      expect(stopBounds.height).toBeGreaterThanOrEqual(44);
    }
    await headerTitle.locator("..").screenshot({ path: info.outputPath("running-detail-header-stop.png") });
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

for (const width of [1440, 390]) {
  test(`renders complete result Markdown without clipping inside the task drawer at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`/browser/fixture.html?case=subagent-dock&markdown-result${width === 390 ? "&dark" : ""}`);
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    const tree = page.getByTestId("subagent-task-tree");
    const messages = page.getByTestId("thread-message-region");
    await trigger.click();
    const row = tree.locator('[data-subagent-id="preview-0"]');
    const panel = page.getByTestId("subagent-task-dock").getByRole("region", { name: "Subtasks", exact: true });
    await expect(tree).toBeVisible();
    await expect.poll(async () => Math.abs((await panel.boundingBox())!.height - (await tree.boundingBox())!.height)).toBeLessThan(1);
    const task = row.locator("xpath=ancestor::li[1]");
    await expect(task.locator(".loading-ring-arc")).toHaveCount(1);
    const labelX = (await row.locator(":scope > span").nth(1).boundingBox())!.x;
    const statusSlot = (await row.locator(":scope > span").first().boundingBox())!;
    await page.mouse.move(1, 1);
    await page.screenshot({ path: info.outputPath("one-task-ring-running.png") });
    // Finish through the existing control without dismissing the reading view.
    await page.getByRole("button", { name: "全部完成", exact: true }).evaluate(node => (node as HTMLButtonElement).click());
    const heading = tree.getByRole("heading", { level: 2, name: "天气结果" });
    await expect(heading).toBeVisible();
    await expect(row).toHaveAccessibleName(/检查项目实现 Completed/);
    await expect(row.locator("svg")).toHaveCount(0);
    expect((await row.locator(":scope > span").nth(1).boundingBox())!.x).toBeCloseTo(labelX, 1);
    const completedSlot = (await row.locator(":scope > span").first().boundingBox())!;
    expect(completedSlot.width).toBeCloseTo(statusSlot.width, 1);
    expect(completedSlot.height).toBeCloseTo(statusSlot.height, 1);
    await expect(tree.locator("strong").filter({ hasText: "10°C" })).toBeVisible();
    await settledMotion(page.getByTestId("subagent-task-dock"));
    const dimensions = await tree.evaluate(node => ({ clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight }));
    expect(dimensions.scrollWidth).toBe(dimensions.clientWidth);
    expect(dimensions.scrollHeight).toBeGreaterThan(dimensions.clientHeight);
    await page.screenshot({ path: info.outputPath("result-markdown-start.png") });
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await tree.getByRole("button", { name: "Copy code", exact: true }).click();
    await expect(tree.getByRole("button", { name: "Copied", exact: true })).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const beforeScroll = await messages.evaluate(node => node.scrollTop);
    const tail = tree.getByText("最后一条完整结论：以上结果均可继续核对。", { exact: true });
    await tail.scrollIntoViewIfNeeded();
    await expect(tail).toBeInViewport();
    await expect(tree.getByRole("link", { name: "天气来源", exact: true })).toHaveAttribute("href", "https://example.com/weather");
    await expect(tree.locator("pre")).toContainText("checked_at: 2026-10-25T20:52:00+08:00");
    expect(await messages.evaluate(node => node.scrollTop)).toBe(beforeScroll);
    await page.screenshot({ path: info.outputPath("result-markdown-end.png") });
    const tailBounds = (await tail.boundingBox())!;
    await page.mouse.move(tailBounds.x + 2, tailBounds.y + tailBounds.height / 2);
    await page.mouse.down();
    await page.mouse.move(tailBounds.x + Math.min(120, tailBounds.width - 2), tailBounds.y + tailBounds.height / 2, { steps: 6 });
    await page.mouse.up();
    expect(await page.evaluate(() => window.getSelection()?.toString())).toBeTruthy();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.route("https://example.com/weather", route => route.fulfill({ body: "Weather source" }));
    const sourceOpened = page.waitForEvent("popup");
    await tree.getByRole("link", { name: "天气来源", exact: true }).click();
    const source = await sourceOpened;
    await expect(source).toHaveURL("https://example.com/weather");
    await source.close();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const readingPosition = await tree.evaluate(node => node.scrollTop);
    const input = page.getByRole("textbox").first();
    await input.fill("继续阅读完整结果，同时输入下一条消息");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await tail.click();
    const detail = page.getByRole("dialog", { name: "检查项目实现", exact: true });
    await expect(detail.getByRole("heading", { level: 2, name: "天气结果" })).toBeVisible();
    await expect(detail).toHaveAccessibleDescription("Completed");
    const title = detail.getByRole("heading", { name: "检查项目实现", exact: true });
    await settledMotion(detail);
    const closeButton = await detail.getByRole("button", { name: "Close", exact: true }).elementHandle();
    const { titleBounds, closeBounds } = await title.evaluate((node, close) => ({
      titleBounds: node.getBoundingClientRect().toJSON(),
      closeBounds: close!.getBoundingClientRect().toJSON(),
    }), closeButton);
    expect(Math.abs(titleBounds.y + titleBounds.height / 2 - closeBounds.y - closeBounds.height / 2)).toBeLessThanOrEqual(1);
    expect(titleBounds.x + titleBounds.width).toBeLessThanOrEqual(closeBounds.x);
    await expect(title.locator("..")).not.toContainText(/\d+s/);
    await title.locator("..").screenshot({ path: info.outputPath("completed-detail-header.png") });
    await page.keyboard.press("Escape");
    await expect(row).toBeFocused();
    expect(await tree.evaluate(node => node.scrollTop)).toBeCloseTo(readingPosition, 0);
    await expect(tail).toBeInViewport();
    const nextRow = tree.locator('[data-subagent-id="preview-1"]');
    await nextRow.scrollIntoViewIfNeeded();
    await expect(nextRow).toBeInViewport();
    await nextRow.click();
    await expect(page.getByRole("dialog", { name: "核对回归测试", exact: true })).toBeVisible();
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
  await expect(portal.getByRole("region", { name: "Subtasks", exact: true })).toHaveCSS("transition-property", "none");
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
    const paragraphs = body.getByText("主对话仍然可以正常输出和滚动。任务列表与消息区分别滚动，展开详情也不会取消正在执行的任务。", { exact: true });
    await expect(paragraphs).toHaveCount(12);
    await settledMotion(body);
    const anchor = paragraphs.nth(6);
    await anchor.scrollIntoViewIfNeeded();
    await body.hover();
    await page.mouse.wheel(0, -160);
    await expect.poll(() => body.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeGreaterThan(100);
    await expect(anchor).toBeInViewport();
    await settledMotion(body);
    await expect.poll(() => body.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeGreaterThan(100);
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


test("keeps long task names, stop controls and detail handoff usable on a narrow screen", async ({ page }, info) => {
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
  await settledMotion(detail);
  const close = detail.getByRole("button", { name: "Close", exact: true });
  const closeBounds = (await close.boundingBox())!;
  expect(closeBounds.width).toBeGreaterThanOrEqual(44);
  expect(closeBounds.height).toBeGreaterThanOrEqual(44);
  const title = detail.getByRole("heading", { name: label, exact: true });
  await expect(title).toHaveAttribute("title", label);
  await expect(detail).toHaveAccessibleDescription("Running");
  const titleBounds = (await title.boundingBox())!;
  expect(titleBounds.height).toBeLessThan(30);
  expect(Math.abs(titleBounds.y + titleBounds.height / 2 - closeBounds.y - closeBounds.height / 2)).toBeLessThanOrEqual(1);
  expect(titleBounds.x + titleBounds.width).toBeLessThanOrEqual(closeBounds.x);
  const detailStop = detail.getByRole("button", { name: `Stop ${label}`, exact: true });
  const detailStopBounds = (await detailStop.boundingBox())!;
  expect(detailStopBounds.width).toBeGreaterThanOrEqual(44);
  expect(detailStopBounds.height).toBeGreaterThanOrEqual(44);
  expect(Math.abs(detailStopBounds.y + detailStopBounds.height / 2 - closeBounds.y - closeBounds.height / 2)).toBeLessThanOrEqual(1);
  expect(titleBounds.x + titleBounds.width).toBeLessThanOrEqual(detailStopBounds.x);
  expect(detailStopBounds.x + detailStopBounds.width).toBeLessThanOrEqual(closeBounds.x);
  await title.locator("..").screenshot({ path: info.outputPath("long-running-detail-header.png") });
  await detailStop.click();
  await expect(detail).toHaveAccessibleDescription("Cancelled");
  await close.click();
  await expect(row).toBeFocused();
});

test("follows the mouse before release and snaps without double toggling", async ({ page }, info) => {
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
    const x = bounds.x + 8;
    const y = bounds.y + bounds.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 4 });
    if (Math.abs(dy) > Math.abs(dx)) {
      await expect.poll(async () => (await trigger.boundingBox())!.y).toBeCloseTo(bounds.y + dy / 2, 0);
      const panel = page.getByTestId("subagent-task-dock").getByRole("region", { name: "Subtasks", exact: true });
      const panelBounds = (await panel.boundingBox())!;
      const composerBounds = (await page.locator(".thread-composer-surface").boundingBox())!;
      expect(panelBounds.y + panelBounds.height).toBeCloseTo(composerBounds.y, 0);
      await page.screenshot({ path: info.outputPath(dy < 0 ? "mouse-drag-opening.png" : "mouse-drag-closing.png") });
    }
    await page.mouse.move(x + dx, y + dy, { steps: 4 });
    await page.mouse.up();
  };
  await swipe(40, 2);
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await swipe(0, -60);
  await expect(tree).toBeVisible();
  await settledMotion(page.getByTestId("subagent-task-dock"));
  await swipe(0, 60);
  await expect(tree).toHaveCount(0);
  await expect(trigger).toBeFocused();
  const bounds = (await trigger.boundingBox())!;
  const x = bounds.x + 8;
  const y = bounds.y + bounds.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + 30, { steps: 4 });
  await page.keyboard.press("Escape");
  await page.mouse.move(x, y - 60, { steps: 6 });
  await page.mouse.up();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Space");
  await expect(tree).toBeVisible();
});

test.describe("touch task drawer", () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });
  test("keeps native taps working after a fast handle drag", async ({ page }) => {
    await page.goto("/browser/fixture.html?case=subagent-dock");
    await page.getByRole("button", { name: "增加任务", exact: true }).click();
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    const tree = page.getByTestId("subagent-task-tree");
    const events = await trigger.evaluateHandle(node => {
      const records: { type: string; prevented: boolean }[] = [];
      for (const type of ["touchstart", "touchmove", "click"]) {
        node.addEventListener(type, event => records.push({ type, prevented: event.defaultPrevented }));
      }
      return records;
    });
    const cdp = await page.context().newCDPSession(page);
    try {
      const closed = (await trigger.boundingBox())!;
      const x = closed.x + closed.width / 2;
      const y = closed.y + closed.height / 2;
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x + 2, y: y + 2 }] });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await expect(tree.locator("[data-subagent-id]")).toHaveCount(23);
      expect((await events.jsonValue()).filter(event => event.type === "click")).toHaveLength(1);
      await settledMotion(page.getByTestId("subagent-task-dock"));
      await events.evaluate(records => { records.length = 0; });

      const bounds = (await trigger.boundingBox())!;
      const dragX = bounds.x + bounds.width / 2;
      const dragY = bounds.y + bounds.height / 2;
      // Define a fast release independently of CDP round-trip and screenshot timing.
      const timestamp = (Date.now() - 35) / 1000;
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", timestamp, touchPoints: [{ x: dragX, y: dragY }] });
      for (let step = 1; step <= 6; step++) {
        await cdp.send("Input.dispatchTouchEvent", {
          type: "touchMove", timestamp: timestamp + step * 0.005,
          touchPoints: [{ x: dragX, y: dragY + step * 10 }],
        });
      }
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", timestamp: timestamp + 0.035, touchPoints: [] });
      await expect(tree).toHaveCount(0);
      await trigger.tap();
      await expect(tree.locator("[data-subagent-id]")).toHaveCount(23);
      const records = await events.jsonValue();
      expect(records.filter(event => event.type === "click")).toHaveLength(1);
      expect(records.filter(event => event.type === "touchstart").every(event => !event.prevented)).toBe(true);
      const moves = records.filter(event => event.type === "touchmove");
      expect(moves.length).toBeGreaterThan(0);
      expect(moves.every(event => event.prevented)).toBe(true);
    } finally {
      await events.dispose();
      await cdp.detach();
    }
  });

  test("follows touch movement, restores a cancelled drag, and keeps list scrolling independent", async ({ page }, info) => {
    await page.goto("/browser/fixture.html?case=subagent-dock");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    const tree = page.getByTestId("subagent-task-tree");
    const cdp = await page.context().newCDPSession(page);
    const swipe = async (target: typeof trigger, dy: number, cancel = false) => {
      await settledMotion(page.getByTestId("subagent-task-dock"));
      const bounds = (await target.boundingBox())!;
      const x = bounds.x + bounds.width / 2;
      const y = bounds.y + bounds.height / 2;
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
      for (let step = 1; step <= 6; step++) {
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: y + dy * step / 6 }] });
        if (step === 3 && target === trigger) {
          await expect.poll(async () => (await trigger.boundingBox())!.y).toBeCloseTo(bounds.y + dy / 2, 0);
          await page.screenshot({ path: info.outputPath(cancel ? "touch-drag-before-cancel.png" : dy < 0 ? "touch-drag-opening.png" : "touch-drag-closing.png") });
        }
      }
      await cdp.send("Input.dispatchTouchEvent", { type: cancel ? "touchCancel" : "touchEnd", touchPoints: [] });
    };
    await swipe(trigger, -60, true);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await swipe(trigger, -60);
    await expect(tree).toBeVisible();
    await settledMotion(page.getByTestId("subagent-task-dock"));
    await swipe(trigger, 60, true);
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await settledMotion(page.getByTestId("subagent-task-dock"));
    await swipe(trigger, 60);
    await expect(tree).toHaveCount(0);
    await page.getByRole("button", { name: "增加任务", exact: true }).click();
    await trigger.tap();
    await expect(tree.locator("[data-subagent-id]")).toHaveCount(23);
    await settledMotion(page.getByTestId("subagent-task-dock"));
    await swipe(tree, -100);
    await expect.poll(() => tree.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await cdp.detach();
  });

  test("opens task details by tapping tool activity and scrolled result content", async ({ page }) => {
    await page.goto("/browser/fixture.html?case=subagent-dock&markdown-result");
    await page.getByTestId("subagent-task-dock-trigger").tap();
    const tree = page.getByTestId("subagent-task-tree");
    await settledMotion(page.getByTestId("subagent-task-dock"));
    await tree.getByText("read_file", { exact: true }).tap();
    const detail = page.getByRole("dialog", { name: "检查项目实现", exact: true });
    await expect(detail).toHaveAccessibleDescription("Running");
    await detail.getByRole("button", { name: "Close", exact: true }).tap();
    await expect(detail).toHaveCount(0);
    await page.getByRole("button", { name: "全部完成", exact: true }).evaluate(node => (node as HTMLButtonElement).click());
    const tail = tree.getByText("最后一条完整结论：以上结果均可继续核对。", { exact: true });
    await tail.scrollIntoViewIfNeeded();
    await settledMotion(page.getByTestId("subagent-task-dock"));
    const readingPosition = await tree.evaluate(node => node.scrollTop);
    await tail.tap();
    await expect(detail).toHaveAccessibleDescription("Completed");
    await detail.getByRole("button", { name: "Close", exact: true }).tap();
    await expect(detail).toHaveCount(0);
    expect(await tree.evaluate(node => node.scrollTop)).toBeCloseTo(readingPosition, 0);
    await expect(tail).toBeInViewport();
  });

  test("preserves completion feedback when an opening drag is cancelled", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
    await page.goto("/browser/fixture.html?case=subagent-dock&dark");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    await trigger.focus();
    const bounds = (await trigger.boundingBox())!;
    const x = bounds.x + 12;
    const y = bounds.y + bounds.height / 2;
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: y - 40 }] });
    await expect.poll(async () => (await trigger.boundingBox())!.y).toBeCloseTo(bounds.y - 40, 0);
    await page.getByRole("button", { name: "全部完成", exact: true }).evaluate(node => (node as HTMLButtonElement).click());
    await expect(page.getByTestId("subagent-task-tree").locator('[data-task-state="done"]')).toHaveCount(3);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchCancel", touchPoints: [] });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(trigger).toContainText("Completed: 3");
    await expect(page.getByTestId("subagent-task-tree")).toHaveCount(0);
    await cdp.detach();
  });
});

for (const width of [1440, 390, 320]) {
  test(`aligns archived task columns with their disclosure at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/browser/fixture.html?case=subagent-dock&archived${width === 320 ? "&long-labels" : ""}`);
    if (width === 1440) await page.evaluate(() => { document.documentElement.style.zoom = "1.25"; });
    const archive = page.locator("[data-subagent-results]").first();
    const header = archive.locator("[data-subagent-results-summary]");
    const logo = header.locator("img");
    await expect(logo).toHaveAttribute("src", "/brand/nanobot_mark.svg");
    await expect.poll(() => logo.evaluate(node => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    const rows = archive.locator('[data-subagent-surface="archive"]');
    await expect(rows.first()).toBeHidden();
    await header.click();
    await expect(rows).toHaveCount(3);
    await expect(rows.first()).toBeVisible();
    await settledMotion(archive);
    const geometry = await archive.evaluate(node => {
      const header = node.querySelector<HTMLElement>("[data-subagent-results-summary]")!;
      const bounds = (element: Element) => element.getBoundingClientRect();
      return {
        overflow: node.scrollWidth > node.clientWidth,
        header: [header.children[0], header.children[1]].map(element => bounds(element).x),
        headerCenters: [...header.children].map(element => {
          const rect = bounds(element);
          return rect.y + rect.height / 2;
        }),
        trailingEdge: bounds(header.lastElementChild!).right,
        rows: [...node.querySelectorAll('[data-subagent-surface="archive"]')].map(row => ({
          columns: [row.children[0], row.children[1]].map(element => bounds(element).x),
          elapsedRight: bounds(row.children[3]).right,
        })),
      };
    });
    expect(geometry.overflow).toBe(false);
    expect(Math.max(...geometry.headerCenters) - Math.min(...geometry.headerCenters)).toBeLessThan(0.5);
    for (const row of geometry.rows) {
      row.columns.forEach((position, index) => expect(Math.abs(position - geometry.header[index])).toBeLessThan(0.5));
      expect(Math.abs(row.elapsedRight - geometry.trailingEdge)).toBeLessThan(0.5);
    }
    await archive.screenshot({ path: info.outputPath("archive-logo-light.png") });
    await page.getByRole("button", { name: "切换主题", exact: true }).click();
    await expect(logo).toBeVisible();
    await archive.screenshot({ path: info.outputPath("archive-logo-dark.png") });
    await rows.first().click();
    await expect(page.getByRole("dialog")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(rows.first()).toBeFocused();
    await header.click();
    await expect(rows.first()).toBeHidden();
  });
}

for (const width of [1440, 390]) {
  test(`keeps composer palettes reachable above an open task drawer at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=subagent-dock");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    await trigger.click();
    await settledMotion(page.getByTestId("subagent-task-dock"));
    const input = page.getByRole("textbox").first();
    for (const [query, inserted] of [["/", "/history"], ["@ref", "@reference "]]) {
      await input.fill(query);
      const option = page.getByRole("option").first();
      await expect(option).toBeVisible();
      expect(await option.evaluate(node => {
        const bounds = node.getBoundingClientRect();
        const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
        return !!hit && node.contains(hit);
      })).toBe(true);
      await option.click();
      await expect(input).toHaveValue(inserted);
      await expect(trigger).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByTestId("subagent-task-tree")).toBeVisible();
    }
  });

  test(`keeps result image portals owned by the task drawer at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("https://example.com/dock-result.svg", route => route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#7788aa" /></svg>',
    }));
    await page.goto("/browser/fixture.html?case=subagent-dock&image-result");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    await trigger.click();
    await page.getByRole("button", { name: "全部完成", exact: true }).evaluate(node => (node as HTMLButtonElement).click());
    const tree = page.getByTestId("subagent-task-tree");
    const thumbnail = tree.getByRole("button", { name: "View image: Result image", exact: true });
    await thumbnail.click();
    const viewer = page.getByRole("dialog", { name: "Result image", exact: true });
    await expect(viewer).toBeVisible();
    await viewer.getByRole("button", { name: "Zoom in", exact: true }).click();
    await expect(viewer.getByRole("button", { name: "Fit image", exact: true })).toHaveText("150%");
    await viewer.getByRole("img", { name: "Result image", exact: true }).click();
    await expect(viewer).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(viewer).toHaveCount(0);
    await expect(thumbnail).toBeFocused();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await page.locator("main").click({ position: { x: 4, y: 65 } });
    await expect(tree).toHaveCount(0);
    await expect(trigger).toHaveCount(0);
    await expect(page.getByRole("textbox").first()).toBeFocused();
  });
}
