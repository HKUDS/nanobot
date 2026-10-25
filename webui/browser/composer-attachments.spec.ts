import { expect, test, type Page } from "@playwright/test";

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
        expect(await image.evaluate(node => (node as HTMLImageElement).naturalWidth)).toBe(480);
        const chip = chips.filter({ has: image });
        await expect(chip).toHaveAttribute("title", new RegExp(`^${name}\\n`));
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
      }
      const document = chips.filter({ hasText: "report.pdf" });
      await expect(document).toContainText("B");
      expect((await document.boundingBox())!.height).toBeLessThan(96);
      expect(await page.evaluate(() => window.document.documentElement.scrollWidth)).toBe(width);
      await page.getByRole("textbox").fill("Compare these images with the report.");
      const screenshot = testInfo.outputPath("composer-attachments.png");
      await page.locator("main").screenshot({ path: screenshot });
      await testInfo.attach("composer-attachments", { path: screenshot, contentType: "image/png" });

      const whiteRemove = chips.filter({ has: page.getByRole("img", { name: "white.png", exact: true }) }).getByRole("button");
      // Tap outside the visible circle, but inside the larger touch target.
      if (width < 640) await whiteRemove.tap({ position: { x: 6, y: 22 } });
      else await whiteRemove.click();
      await expect(chips).toHaveCount(3);
      const darkRemove = chips.filter({ has: page.getByRole("img", { name: "dark.png", exact: true }) }).getByRole("button");
      await darkRemove.focus();
      await expect(darkRemove).toBeFocused();
      await page.keyboard.press("Delete");
      await expect(chips).toHaveCount(2);
      await chips.filter({ has: page.getByRole("img", { name: "notes.png", exact: true }) }).getByRole("button").click();
      await document.getByRole("button").click();
      await expect(page.getByRole("textbox")).toBeFocused();
      await expect(page.getByRole("textbox")).toHaveValue("Compare these images with the report.");
    });
  });
}

test("shows a readable error card and allows removal of a corrupt image", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=composer-action");
  const broken = Buffer.from("not a PNG image");
  await page.locator('input[type="file"]').setInputFiles({ name: "broken.png", mimeType: "image/png", buffer: broken });
  const chip = page.getByTestId("composer-chip");
  await expect(chip).toContainText("broken.png");
  await expect(chip).toContainText("File doesn't look like a real image");
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeDisabled();
  await chip.getByRole("button", { name: "Remove attachment" }).click();
  await expect(page.getByRole("button", { name: "Voice input", exact: true })).toBeEnabled();
  await expect(page.getByRole("textbox")).toBeFocused();
});
