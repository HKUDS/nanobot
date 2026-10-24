import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`keeps subtasks reachable through long replies, independent list scrolling and detail handoff at ${width}px`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=subagent-dock");
    const trigger = page.getByTestId("subagent-task-dock-trigger");
    const messages = page.getByTestId("thread-message-region");
    await expect(trigger).toContainText("Active: 3");
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
    const panel = page.getByRole("dialog", { name: "Subtasks", exact: true });
    if (width > 639) {
      const bounds = (await panel.boundingBox())!;
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(original.y);
    } else {
      await expect.poll(async () => {
        const bounds = (await panel.boundingBox())!;
        return Math.round(bounds.y + bounds.height);
      }).toBe(900);
      const bounds = (await panel.boundingBox())!;
      expect(bounds.y + bounds.height).toBeCloseTo(900, 0);
      expect(bounds.height).toBeLessThanOrEqual(630);
    }
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
  await expect(trigger).toContainText("Active: 3");
  await trigger.click();
  const tree = page.getByTestId("subagent-task-tree");
  await expect(tree).toBeVisible();
  await expect(tree.locator(".loading-ring-arc").first()).toHaveCSS("animation-name", "none");
  await expect(page.getByRole("dialog", { name: "Subtasks", exact: true })).toHaveCSS("animation-name", "none");
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
  await expect(trigger).toContainText("Active: 3");
  await page.getByRole("button", { name: "模拟失败", exact: true }).click();
  await expect(trigger).toContainText("Review needed: 1");
  await trigger.click();
  await expect(tree.getByText("演示：测试执行失败，请打开详情检查。", { exact: true })).toBeVisible();
});

test("lets an outside click return directly to the composer without stealing its focus", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=subagent-dock");
  await page.getByTestId("subagent-task-dock-trigger").click();
  await expect(page.getByTestId("subagent-task-tree")).toBeVisible();
  const input = page.getByRole("textbox").first();
  await input.click();
  await expect(page.getByTestId("subagent-task-tree")).toHaveCount(0);
  await expect(input).toBeFocused();
  await page.keyboard.type("Continue the conversation");
  await expect(input).toHaveValue("Continue the conversation");
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

test("keeps a bottom task sheet inside a shortened visual viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/browser/fixture.html?case=subagent-dock");
  await page.evaluate(() => {
    document.documentElement.style.setProperty("--app-viewport-top", "0px");
    document.documentElement.style.setProperty("--app-viewport-height", "500px");
  });
  await page.getByTestId("subagent-task-dock-trigger").click();
  const panel = page.getByRole("dialog", { name: "Subtasks", exact: true });
  const bounds = (await panel.boundingBox())!;
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.y + bounds.height).toBeCloseTo(500, 0);
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole("textbox").first()).toBeEditable();
});
