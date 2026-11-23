import { expect, test, type Page } from "@playwright/test";

async function fixture(page: Page) {
  await page.goto("/browser/fixture.html?case=subagent-dock");
  // Hold the observed pending-animation window open; input remains native.
  await page.addStyleTag({ content: "[data-radix-popper-content-wrapper] > [data-state] { animation-delay: 3s !important; }" });
  await expect(page.getByTestId("subagent-task-dock-trigger")).toContainText("Running: 3");
}

async function showDockHint(page: Page) {
  const trigger = page.getByTestId("subagent-task-dock-trigger");
  await trigger.hover();
  await expect(trigger).toHaveAttribute("data-state", /open/);
  await expect(page.getByRole("tooltip")).toContainText("Subtasks");
}

test("a disabled completed-dock hint cannot consume Escape", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await fixture(page);
  const trigger = page.getByTestId("subagent-task-dock-trigger");
  const tree = page.getByTestId("subagent-task-tree");
  await page.getByRole("button", { name: "增加任务", exact: true }).click();
  await expect(trigger).toContainText("Running: 23");
  await page.getByRole("button", { name: "全部完成", exact: true }).click();
  await expect(trigger).toContainText("Completed: 23");
  await showDockHint(page);
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(tree.locator('[data-task-state="done"]')).toHaveCount(23);
  await page.keyboard.press("Escape");
  await expect(tree).toHaveCount(0);
});

test("a disabled dragged-dock hint cannot consume Escape", async ({ page }) => {
  await fixture(page);
  const trigger = page.getByTestId("subagent-task-dock-trigger");
  await page.getByRole("button", { name: "增加任务", exact: true }).click();
  await expect(trigger).toContainText("Running: 23");
  await showDockHint(page);
  const bounds = (await trigger.boundingBox())!;
  const x = bounds.x + 8, y = bounds.y + bounds.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + 30, { steps: 4 });
  await page.keyboard.press("Escape");
  await page.mouse.move(x, y - 60, { steps: 6 });
  await page.mouse.up();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
});

test("an actually open task tooltip owns the first Escape", async ({ page }) => {
  await fixture(page);
  const trigger = page.getByTestId("subagent-task-dock-trigger");
  const tree = page.getByTestId("subagent-task-tree");
  await trigger.click();
  await expect(tree).toBeVisible();
  const stop = tree.getByRole("button", { name: "Stop 检查项目实现", exact: true });
  await stop.hover();
  await expect(stop).toHaveAttribute("data-state", /open/);
  await expect(page.getByRole("tooltip")).toContainText("Stop 检查项目实现");
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-radix-popper-content-wrapper]")).toHaveCount(0);
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(tree).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(tree).toHaveCount(0);
});

test("a task detail dialog owns the first Escape and returns focus before the next", async ({ page }) => {
  await fixture(page);
  const trigger = page.getByTestId("subagent-task-dock-trigger");
  const tree = page.getByTestId("subagent-task-tree");
  const row = tree.locator('[data-subagent-id="preview-0"]');
  await trigger.click();
  await row.click();
  const dialog = page.getByRole("dialog", { name: "检查项目实现", exact: true });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(tree).toBeVisible();
  // The dialog can lose its name before its exit and focus restoration finish.
  await expect(page.locator('[role="dialog"]')).toHaveCount(0);
  await expect(row).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(tree).toHaveCount(0);
});
