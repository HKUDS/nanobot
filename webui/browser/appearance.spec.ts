import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", (route) => route.abort());
});

test("system theme stays live, explicit choices persist, and tabs agree", async ({ page, context }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/browser/fixture.html?case=appearance");
  await expect(page.getByRole("radio", { name: "System", exact: true })).toBeChecked();
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("radio", { name: "Light", exact: true }).check();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.reload();
  await expect(page.getByRole("radio", { name: "Light", exact: true })).toBeChecked();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.getByRole("radio", { name: "System", exact: true }).check();
  await expect(page.locator("html")).toHaveClass(/dark/);
  const other = await context.newPage();
  await other.goto("/browser/fixture.html?case=appearance");
  await expect(other.getByRole("radio", { name: "System", exact: true })).toBeChecked();
  await other.getByRole("radio", { name: "Light", exact: true }).check();
  await expect(page.getByRole("radio", { name: "Light", exact: true })).toBeChecked();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("custom reading size previews, persists and survives preset changes", async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem("nanobot-webui.settings-preferences")) {
      localStorage.setItem("nanobot-webui.settings-preferences", JSON.stringify({
        schemaVersion: 1, notificationSound: true, browserNotifications: true, brandLogos: false,
      }));
    }
  });
  await page.goto("/browser/fixture.html?case=appearance");
  const title = page.getByRole("heading", { name: "Appearance", exact: true });
  const titleSize = await title.evaluate((element) => getComputedStyle(element).fontSize);
  await page.getByRole("spinbutton", { name: "Custom text size", exact: true }).click();
  const input = page.getByRole("spinbutton", { name: "Custom text size" });
  await input.fill("23");
  const paragraph = page.locator("[data-reading-preview-content] .markdown-content p").first();
  await expect(paragraph).toHaveCSS("font-size", "23px");
  await expect(page.locator("[data-reading-preview-content] code")).toHaveCSS("font-size", "20.125px");
  await input.press("ArrowUp");
  await input.press("Enter");
  await expect(input).toHaveValue("24");
  await page.reload();
  await expect(input).toHaveValue("24");
  await page.getByRole("radio", { name: "Small reading text", exact: true }).click();
  await expect(paragraph).toHaveCSS("font-size", "16px");
  await page.getByRole("spinbutton", { name: "Custom text size", exact: true }).click();
  await expect(input).toHaveValue("24");
  await expect(paragraph).toHaveCSS("font-size", "24px");
  await expect(title).toHaveCSS("font-size", titleSize);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("nanobot-webui.settings-preferences")!))).toMatchObject({
    readingTextSize: "custom", customReadingTextSize: 24, notificationSound: true, browserNotifications: true, brandLogos: false,
  });
});

for (const narrow of [false, true]) {
  test(`appearance remains usable at maximum size: ${narrow ? "narrow dark" : "desktop light"}`, async ({ page }, info) => {
    await page.setViewportSize(narrow ? { width: 390, height: 844 } : { width: 1280, height: 1000 });
    await page.addInitScript((dark) => {
      localStorage.setItem("nanobot.locale", "zh-CN");
      localStorage.setItem("nanobot-webui.theme", dark ? "dark" : "light");
    }, narrow);
    await page.goto("/browser/fixture.html?case=appearance");
    await page.getByRole("spinbutton", { name: "自定义字号", exact: true }).click();
    await page.getByRole("spinbutton", { name: "自定义字号" }).fill("28");
    await expect(page.locator("[data-reading-preview-content] .markdown-content p").first()).toHaveCSS("font-size", "28px");
    expect(await page.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    const checkbox = page.getByRole("switch", { name: "品牌图标" });
    await checkbox.click();
    await expect(checkbox).toHaveAttribute("aria-checked", "false");
    await page.getByRole("button", { name: "折叠修改", exact: true }).click();
    await expect(page.getByText("默认收起代码差异，需要时点开。", { exact: true })).toBeVisible();
    await page.locator("main").evaluate((element) => element.scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath("appearance.png") });
  });
}

test("changing a custom size reflows an existing composer and its mention layer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/browser/fixture.html?case=typography");
  await page.getByRole("spinbutton", { name: "Custom text size", exact: true }).click();
  await page.getByRole("spinbutton", { name: "Custom text size" }).fill("14");
  const composer = page.getByRole("textbox", { name: "Message input", exact: true });
  await composer.fill("Hello @typography\nKeep reading\nAnother thought");
  await expect(composer).toHaveCSS("font-size", "16px");
  const before = (await composer.boundingBox())!.height;
  await page.getByRole("spinbutton", { name: "Custom text size" }).fill("28");
  await expect(composer).toHaveCSS("font-size", "28px");
  await expect.poll(async () => (await composer.boundingBox())!.height).toBeGreaterThan(before);
  expect(await composer.evaluate((element) => element.scrollHeight <= element.clientHeight + 1)).toBe(true);
  await expect(page.locator(".thread-composer-input > div[aria-hidden]")).toHaveCSS("font-size", "28px");
  await expect(composer).toHaveValue("Hello @typography\nKeep reading\nAnother thought");
});

test("long localized labels fit a small phone without hiding their meaning", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 320, height: 800 }, hasTouch: true, isMobile: true });
  try {
    const page = await context.newPage();
    await page.route("**/api/**", (route) => route.abort());
    await page.goto("/browser/fixture.html?case=appearance&lang=fr");
    const custom = page.locator(".appearance-size-options").getByRole("spinbutton");
    await page.locator(".appearance-custom-label").tap();
    await expect(custom).toBeFocused();
    await expect(custom).toHaveCSS("font-size", "16px");
    const hint = page.getByRole("tooltip");
    await expect(hint).toBeVisible();
    const hintSurface = page.locator("[data-radix-popper-content-wrapper]").filter({ has: hint });
    const hintBox = (await hintSurface.boundingBox())!;
    expect(hintBox.x).toBeGreaterThanOrEqual(0);
    expect(hintBox.x + hintBox.width).toBeLessThanOrEqual(320);
    expect(await page.locator(".appearance-theme-label, .appearance-size-options, .appearance-custom-label, .appearance-size-options button").evaluateAll(
      (elements) => elements.every((element) => element.scrollWidth <= element.clientWidth + 1 && element.scrollHeight <= element.clientHeight + 1),
    )).toBe(true);
    const labelBox = (await page.locator(".appearance-custom-label").boundingBox())!;
    const fieldBox = (await page.locator(".appearance-custom-option").boundingBox())!;
    expect(fieldBox.height).toBeGreaterThanOrEqual(44);
    expect(labelBox.y).toBeGreaterThan(fieldBox.y);
    expect(labelBox.y + labelBox.height).toBeLessThan((await custom.boundingBox())!.y + 1);
  } finally {
    await context.close();
  }
});

test("the inline custom field is keyboard-editable without moving the size control", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=appearance");
  const preset = page.getByRole("radio", { name: "Large reading text", exact: true });
  await preset.click();
  const input = page.getByRole("spinbutton", { name: "Custom text size", exact: true });
  const before = (await input.boundingBox())!;
  await preset.press("Tab");
  await expect(input).toBeFocused();
  await input.pressSequentially("22");
  await expect(input).toHaveValue("22");
  await input.press("Enter");
  await expect(page.locator("[data-reading-preview-content] .markdown-content p").first()).toHaveCSS("font-size", "22px");
  const after = (await input.boundingBox())!;
  expect(after.y).toBe(before.y);
  expect(after.height).toBe(before.height);
  const presetBox = (await preset.boundingBox())!;
  const groupBox = (await page.locator(".appearance-size-presets").boundingBox())!;
  const customBox = (await page.locator(".appearance-custom-option").boundingBox())!;
  expect(Math.abs((customBox.y + customBox.height / 2) - (presetBox.y + presetBox.height / 2))).toBeLessThan(1);
  expect(customBox.height).toBe(groupBox.height);
  expect(presetBox.width).toBe(presetBox.height);
  expect(customBox.x - (groupBox.x + groupBox.width)).toBeGreaterThanOrEqual(8);
  await input.fill("");
  await input.press("Enter");
  await expect(input).toHaveValue("22");
});

test("reading-size guidance opens on hover and focus, and invalid entries explain what stays saved", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=appearance");
  const input = page.getByRole("spinbutton", { name: "Custom text size", exact: true });
  await input.hover();
  const hint = page.getByRole("tooltip");
  await expect(hint).toContainText("Enter a whole number from 14 to 28 px.");
  await expect(page.getByRole("radio", { name: "Standard reading text" })).toBeChecked();
  await input.click();
  await expect(hint).toContainText("the composer stays at least 16px");
  await input.fill("40");
  await input.press("Enter");
  await expect(input).toHaveValue("40");
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(hint).toContainText("Your text remains at 18 px.");
  await expect(page.locator("[data-reading-preview-content] .markdown-content p").first()).toHaveCSS("font-size", "18px");
  await input.fill("22");
  await input.press("Enter");
  await expect(input).not.toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("[data-reading-preview-content] .markdown-content p").first()).toHaveCSS("font-size", "22px");
  await expect(hint).toBeHidden();
  await page.reload();
  await expect(input).toHaveValue("22");
});

test("the visible Custom label activates the same inline editor from a preset", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=appearance");
  const label = page.locator(".appearance-custom-label");
  const input = page.getByRole("spinbutton", { name: "Custom text size", exact: true });
  await label.click();
  await expect(input).toBeFocused();
  await input.pressSequentially("23");
  await input.press("Enter");
  await expect(page.locator("[data-reading-preview-content] .markdown-content p").first()).toHaveCSS("font-size", "23px");
  await page.getByRole("radio", { name: "Small reading text", exact: true }).click();
  await label.click();
  await expect(input).toBeFocused();
  await expect(input).toHaveValue("23");
  await expect(page.locator("[data-reading-preview-content] .markdown-content p").first()).toHaveCSS("font-size", "23px");
});


test("unfinished numeric input reports an error instead of acting like a cleared field", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=appearance");
  const input = page.getByRole("spinbutton", { name: "Custom text size", exact: true });
  const paragraph = page.locator("[data-reading-preview-content] .markdown-content p").first();
  for (const text of ["-", "1e"]) {
    await input.click();
    await input.pressSequentially(text);
    expect(await input.evaluate((element: HTMLInputElement) => element.validity.badInput)).toBe(true);
    await input.press("Enter");
    await expect(input).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByRole("tooltip", { name: /Your text remains at 18 px\./ })).toBeVisible();
    await expect(paragraph).toHaveCSS("font-size", "18px");
    await input.click();
    await input.press("Escape");
    await expect(input).toHaveValue("18");
    await expect(input).not.toHaveAttribute("aria-invalid", "true");
    await input.press("Tab");
  }
  await input.fill("22");
  await input.press("Enter");
  await expect(paragraph).toHaveCSS("font-size", "22px");
  await input.fill("");
  await input.press("Enter");
  await expect(input).toHaveValue("22");
  await expect(input).not.toHaveAttribute("aria-invalid", "true");
});
