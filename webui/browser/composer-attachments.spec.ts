import { expect, test, type Locator, type Page } from "@playwright/test";

async function imageFile(page: Page, name: string, background: string) {
  const data = await page.evaluate((fill) => {
    const canvas = document.createElement("canvas");
    canvas.width = 480;
    canvas.height = 320;
    const context = canvas.getContext("2d")!;
    context.fillStyle = fill;
    context.fillRect(0, 0, 480, 320);
    context.fillStyle = "#7898a5";
    context.fillRect(48, 64, 260, 24);
    context.fillRect(48, 112, 380, 16);
    context.fillRect(48, 152, 320, 16);
    return canvas.toDataURL("image/png").split(",")[1];
  }, background);
  return { name, mimeType: "image/png", buffer: Buffer.from(data, "base64") };
}

async function expectAttachmentDetails(page: Page, chip: Locator, name: string, touch = false) {
  const info = chip.getByRole("button", { name, exact: true });
  const size = await info.getAttribute("aria-description");
  expect(size).toMatch(/^\d+(?:\.\d+)? (?:B|KiB|MiB)$/);
  if (touch) await info.tap();
  else {
    await info.hover();
    await expect(page.getByRole("tooltip")).toContainText(name);
    await expect(page.getByRole("tooltip")).toContainText(size!);
    await info.click();
  }
  const details = page.getByRole("dialog", { name, exact: true });
  await expect(details.getByText(name, { exact: true })).toBeVisible();
  await expect(details.getByText(size!, { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(details).toHaveCount(0);
  await expect(info).toBeFocused();
  await page.mouse.move(0, 0);
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("**/api/**", route => route.fulfill({ json: {} }));
});

for (const { width, dark, variant } of [
  { width: 1440, dark: false, variant: "hero" },
  { width: 1440, dark: true, variant: "thread" },
  { width: 360, dark: false, variant: "hero" },
  { width: 314, dark: true, variant: "thread" },
]) {
  test.describe(`${width}px ${dark ? "dark" : "light"} ${variant} attachments`, () => {
    test.use({ viewport: { width, height: 800 }, hasTouch: width < 640 });
    test("shows image-only thumbnails and keeps mixed attachments removable", async ({ page }, testInfo) => {
      await page.goto(`/browser/fixture.html?case=composer-action&composerVariant=${variant}`);
      await page.locator("html").evaluate((node, enabled) => node.classList.toggle("dark", enabled), dark);
      const files = [
        await imageFile(page, "white.png", "#fff"),
        await imageFile(page, "dark.png", "#111"),
        await imageFile(page, "notes.png", "#dfebe4"),
        { name: "report.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\npreview fixture") },
      ];
      await page.locator('input[type="file"]').setInputFiles(files);
      await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeEnabled();
      const chips = page.getByTestId("composer-chip");
      await expect(chips).toHaveCount(4);
      for (const name of ["white.png", "dark.png", "notes.png"]) {
        const image = page.getByRole("img", { name, exact: true });
        await expect(image).toBeVisible();
        expect(await image.evaluate(node => ({ width: (node as HTMLImageElement).naturalWidth, height: (node as HTMLImageElement).naturalHeight }))).toEqual({ width: 480, height: 320 });
        const chip = chips.filter({ has: image });
        const box = (await chip.boundingBox())!;
        expect(box.width).toBe(96);
        expect(box.height).toBe(96);
        expect(await chip.innerText()).toBe("");
        const remove = chip.getByRole("button", { name: "Remove attachment" });
        await expect(remove).toBeVisible();
        await expect(remove).toHaveAccessibleDescription(name);
        const target = (await remove.boundingBox())!;
        expect(target.width).toBeGreaterThanOrEqual(44);
        expect(target.height).toBeGreaterThanOrEqual(44);
        expect(target.x + target.width).toBeCloseTo(box.x + box.width - 1);
        expect(target.y).toBeCloseTo(box.y + 1);
        await expectAttachmentDetails(page, chip, name, width < 640);
      }
      const document = chips.filter({ has: page.getByRole("button", { name: "report.pdf", exact: true }) });
      await expect(document).toHaveText("PDF");
      await expect(document.getByRole("button", { name: "report.pdf", exact: true })).toHaveAccessibleDescription(`${files[3].buffer.byteLength} B`);
      const documentBox = (await document.boundingBox())!;
      expect(documentBox.width).toBe(96);
      expect(documentBox.height).toBe(96);
      await expectAttachmentDetails(page, document, "report.pdf", width < 640);
      expect(await page.evaluate(() => window.document.documentElement.scrollWidth)).toBe(width);
      await page.getByRole("textbox").fill("Compare these images with the report.");
      const screenshot = testInfo.outputPath("composer-attachments.png");
      await page.locator("main").screenshot({ path: screenshot });
      await testInfo.attach("composer-attachments", { path: screenshot, contentType: "image/png" });

      const whiteRemove = chips.filter({ has: page.getByRole("img", { name: "white.png", exact: true }) }).getByRole("button", { name: "Remove attachment", exact: true });
      // Tap outside the visible circle, but inside the larger touch target.
      if (width < 640) await whiteRemove.tap({ position: { x: 6, y: 22 } });
      else await whiteRemove.click();
      await expect(chips).toHaveCount(3);
      const darkRemove = chips.filter({ has: page.getByRole("img", { name: "dark.png", exact: true }) }).getByRole("button", { name: "Remove attachment", exact: true });
      await darkRemove.focus();
      await expect(darkRemove).toBeFocused();
      await page.keyboard.press("Delete");
      await expect(chips).toHaveCount(2);
      await chips.filter({ has: page.getByRole("img", { name: "notes.png", exact: true }) }).getByRole("button", { name: "Remove attachment", exact: true }).click();
      await document.getByRole("button", { name: "Remove attachment", exact: true }).click();
      await expect(page.getByRole("textbox")).toBeFocused();
      await expect(page.getByRole("textbox")).toHaveValue("Compare these images with the report.");
    });
  });
}

test("shows a readable error card and allows removal of a corrupt image", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=composer-action");
  const input = page.getByRole("textbox");
  const draft = "Keep this draft while checking the attachment.";
  await input.fill(draft);
  const broken = Buffer.from("not a PNG image");
  await page.locator('input[type="file"]').setInputFiles({ name: "broken.png", mimeType: "image/png", buffer: broken });
  const chip = page.getByTestId("composer-chip");
  await expect(chip.getByRole("button", { name: "broken.png", exact: true })).toHaveText("PNG");
  await expect(chip.getByText("File doesn't look like a real image", { exact: true })).toBeVisible();
  await expectAttachmentDetails(page, chip, "broken.png");
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeDisabled();
  await input.press("Enter");
  await expect(page.getByRole("status", { name: "Execution status", exact: true })).toHaveText("Idle");
  await expect(input).toHaveValue(draft);
  await expect(chip).toHaveCount(1);
  await chip.getByRole("button", { name: "Remove attachment", exact: true }).click();
  await expect(chip).toHaveCount(0);
  await expect(input).toBeFocused();
  await expect(input).toHaveValue(draft);
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeEnabled();
  await input.fill("");
  await expect(page.getByRole("button", { name: "Voice input", exact: true })).toBeEnabled();
});
