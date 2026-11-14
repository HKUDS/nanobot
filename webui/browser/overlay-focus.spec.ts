import { expect, test, type BrowserContext, type Page } from "@playwright/test";

let overlayFocusContext: BrowserContext;
let page: Page;

test.beforeEach(async ({ browser, baseURL }) => {
  overlayFocusContext = await browser.newContext({ baseURL });
  page = await overlayFocusContext.newPage();
  await page.goto("/browser/overlay-focus.html");
  await expect(page.getByRole("textbox", { name: "Composer draft" })).toBeVisible();
});
test.afterEach(async () => { await overlayFocusContext.close(); });

async function armFocusCleanup() {
  // The outer overlay owns the focus scope; pickers can contain nested listboxes.
  await page.locator('[role="dialog"], [role="menu"], [role="listbox"]').first().evaluate(node => {
    document.documentElement.removeAttribute("data-overlay-focus-settled");
    node.addEventListener("focusScope.autoFocusOnUnmount", () => {
      queueMicrotask(() => document.documentElement.setAttribute("data-overlay-focus-settled", "true"));
    }, { once: true });
  });
}

async function settleClose(action: () => Promise<unknown>) {
  await armFocusCleanup();
  await action();
  await expect(page.locator("html")).toHaveAttribute("data-overlay-focus-settled", "true");
}

test("model picker outside click keeps the clicked input focused", async () => {
  await page.getByRole("textbox", { name: "Composer draft" }).click();
  await page.getByRole("button", { name: "First model", exact: true }).click();
  await settleClose(() => page.getByRole("textbox", { name: "Outside field" }).click());
  await expect(page.getByRole("textbox", { name: "Outside field" })).toBeFocused();
});

test("model picker selection returns to the composer after its exit", async () => {
  await page.getByRole("button", { name: "First model", exact: true }).click();
  await settleClose(() => page.getByRole("option", { name: "Second model" }).click());
  await expect(page.getByRole("textbox", { name: "Composer draft" })).toBeFocused();
});

test("model picker keyboard Escape returns visible focus to its trigger", async () => {
  await page.getByRole("textbox", { name: "Composer draft" }).click();
  await page.keyboard.press("Tab");
  const trigger = page.getByRole("button", { name: "First model", exact: true });
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("option", { name: "First model" })).toBeFocused();
  await page.getByRole("dialog").evaluate(async (node) => { await Promise.all(node.getAnimations().map((animation) => animation.finished)); });
  await settleClose(() => page.keyboard.press("Escape"));
  await expect(trigger).toBeFocused();
  expect(await trigger.evaluate((node) => node.matches(":focus-visible"))).toBe(true);
});

test("model picker management handoff keeps focus in the new dialog", async () => {
  await page.getByRole("button", { name: "First model", exact: true }).click();
  await settleClose(() => page.getByRole("button", { name: "Manage presets" }).click());
  await expect(page.getByRole("dialog", { name: "Manage models fixture" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Manage models fixture" })).toBeFocused();
});

test("prompt search shortcut Escape restores the editing field", async () => {
  const composer = page.getByRole("textbox", { name: "Composer draft" });
  await composer.click();
  await page.keyboard.press("Control+f");
  await expect(page.getByRole("textbox", { name: "Search messages" })).toBeFocused();
  await page.getByRole("dialog").evaluate(async (node) => { await Promise.all(node.getAnimations().map((animation) => animation.finished)); });
  await settleClose(() => page.keyboard.press("Escape"));
  await expect(composer).toBeFocused();
});

for (const name of ["First model", "Session details", "This reply switched to a fallback model, answered by Fallback model."]) {
  test(`pointer-open / Escape restores the interrupted editor: ${name}`, async () => {
    const composer = page.getByRole("textbox", { name: "Composer draft" });
    const trigger = page.getByRole("button", { name, exact: true });
    await composer.click();
    await trigger.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("dialog").evaluate(async (node) => { await Promise.all(node.getAnimations().map((animation) => animation.finished)); });
    await settleClose(() => page.keyboard.press("Escape"));
    await expect(composer).toBeFocused();
    expect(await trigger.evaluate((node) => node.matches(":focus-visible"))).toBe(false);
  });

  if (name !== "First model") {
    test(`Space-open / Escape retains visible keyboard focus: ${name}`, async () => {
      const trigger = page.getByRole("button", { name, exact: true });
      await page.getByRole("textbox", { name: "Composer draft" }).click();
      for (let count = 0; count < 4 && !await trigger.evaluate((node) => node === document.activeElement); count++) await page.keyboard.press("Tab");
      await expect(trigger).toBeFocused();
      await page.keyboard.press("Space");
      await expect(page.getByRole("dialog")).toBeVisible();
      await page.getByRole("dialog").evaluate(async (node) => { await Promise.all(node.getAnimations().map((animation) => animation.finished)); });
      await settleClose(() => page.keyboard.press("Escape"));
      await expect(trigger).toBeFocused();
      expect(await trigger.evaluate((node) => node.matches(":focus-visible"))).toBe(true);
      expect(await trigger.evaluate((node) => getComputedStyle(node).boxShadow)).not.toBe("none");
    });

    test(`outside click retains the clicked control: ${name}`, async () => {
      await page.getByRole("button", { name, exact: true }).click();
      const outside = page.getByRole("button", { name: "Outside button", exact: true });
      await settleClose(() => outside.click());
      await expect(outside).toBeFocused();
    });
  }
}

for (const name of ["Open dialog", "Open menu", "Example select"]) {
  test(`shared overlay keyboard Escape preserves trigger focus: ${name}`, async () => {
    const trigger = page.getByRole(name === "Example select" ? "combobox" : "button", { name, exact: true, includeHidden: true });
    await trigger.focus();
    await page.keyboard.press("Enter");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await page.locator('[role="dialog"], [role="menu"], [role="listbox"]').evaluate(async (node) => { await Promise.all(node.getAnimations().map((animation) => animation.finished)); });
    await settleClose(() => page.keyboard.press("Escape"));
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(trigger).toBeFocused();
    expect(await trigger.evaluate((node) => node.matches(":focus-visible"))).toBe(true);
  });
}

test("feature dialog returns to the title trigger that opened it, not the other Configure trigger", async () => {
  const trigger = page.getByRole("button", { name: "Example feature", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Example feature", exact: true });
  await expect(dialog).toBeFocused();
  await dialog.evaluate(async (node) => { await Promise.all(node.getAnimations().map((animation) => animation.finished)); });
  await settleClose(() => page.keyboard.press("Escape"));
  await expect(trigger).toBeFocused();
});

test("feature save-on-close restores keyboard focus when it disables the opening switch", async () => {
  const toggle = page.getByRole("switch", { name: "Example feature", includeHidden: true });
  await toggle.focus();
  await page.keyboard.press("Space");
  const dialog = page.getByRole("dialog", { name: "Example feature", exact: true });
  await expect(dialog).toBeFocused();
  await expect(toggle).toBeChecked();
  await dialog.evaluate(async node => { await Promise.all(node.getAnimations().map(animation => animation.finished)); });
  await settleClose(() => page.keyboard.press("Escape"));
  await expect(dialog).toBeHidden();
  await expect(toggle).toBeDisabled();
  const configure = page.getByRole("button", { name: "Configure", exact: true });
  await expect(configure).toBeFocused();
  expect(await configure.evaluate(node => node.matches(":focus-visible"))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("textbox", { name: "Outside field" })).toBeFocused();
});

test("prompt search button Escape returns to its keyboard trigger", async () => {
  const trigger = page.getByRole("button", { name: "Message navigation", exact: true });
  await page.getByRole("textbox", { name: "Composer draft" }).click();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Space");
  const dialog = page.getByRole("dialog");
  await expect(page.getByRole("textbox", { name: "Search messages" })).toBeFocused();
  await dialog.evaluate(async (node) => { await Promise.all(node.getAnimations().map((animation) => animation.finished)); });
  await settleClose(() => page.keyboard.press("Escape"));
  await expect(trigger).toBeFocused();
});

test("workspace pointer-open / Escape restores the interrupted editor instead of dropping focus", async () => {
  const composer = page.getByRole("textbox", { name: "Composer draft" });
  await composer.click();
  await page.getByRole("button", { name: "Switch directory", exact: true }).click();
  await expect(page.getByRole("option", { name: "/workspace/project", exact: true })).toBeVisible();
  await page.getByRole("dialog").evaluate(async (node) => { await Promise.all(node.getAnimations().map((animation) => animation.finished)); });
  await settleClose(() => page.keyboard.press("Escape"));
  await expect(composer).toBeFocused();
});

test("an outside interaction during Escape's exit keeps the newly chosen focus", async () => {
  await page.getByRole("textbox", { name: "Composer draft" }).click();
  await page.getByRole("button", { name: "First model", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.evaluate(async node => { await Promise.all(node.getAnimations().map(animation => animation.finished)); });
  await armFocusCleanup();
  await dialog.evaluate(node => {
    node.addEventListener("animationstart", () => {
      for (const animation of node.getAnimations()) animation.pause();
    }, { once: true });
  });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveAttribute("data-state", "closed");
  await expect.poll(() => dialog.evaluate(node => node.getAnimations().some(animation => animation.playState === "paused"))).toBe(true);
  const outside = page.getByRole("textbox", { name: "Outside field" });
  await outside.click();
  await dialog.evaluate(node => { for (const animation of node.getAnimations()) animation.finish(); });
  await expect(page.locator("html")).toHaveAttribute("data-overlay-focus-settled", "true");
  await expect(outside).toBeFocused();
});
