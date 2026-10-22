import { expect, test } from "@playwright/test";
const longEditPath = "C:/Users/HR/.nanobot-ncode/workspace/artifacts/nan284-local-file-attachments/review-fixes-20261022-133833/serve_fixture.py";

for (const width of [360, 1024]) {
  test(`file edit paths preserve statistics and reveal full paths at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/browser/fixture.html?case=file-edit-path");
    const references = page.getByTestId("activity-file-reference");
    await expect(references).toHaveCount(4);
    for (let index = 0; index < 4; index++) {
      const row = page.getByTestId("activity-step").nth(index);
      const stats = row.getByTestId("activity-diff-pair");
      await expect(stats).toHaveText(index === 1 ? "+33-0" : "+12345-6789");
      const geometry = await row.evaluate((element) => {
        const path = element.querySelector('[data-testid="activity-file-reference"]')!.getBoundingClientRect();
        const stats = element.querySelector('[data-testid="activity-diff-pair"]')!.getBoundingClientRect();
        return { pathRight: path.right, statsLeft: stats.left, statsRight: stats.right, rowRight: element.getBoundingClientRect().right };
      });
      expect(geometry.pathRight).toBeLessThanOrEqual(geometry.statsLeft);
      expect(geometry.statsRight).toBeLessThanOrEqual(geometry.rowRight);
    }
    const longPath = references.first();
    await expect(longPath).toContainText("…");
    await expect(references.nth(1)).not.toContainText("…");
    // The last filename stays inside the clipping viewport, without reversing text direction.
    const filename = longPath.locator(".font-semibold");
    const tail = await filename.evaluate((element) => {
      const clip = element.parentElement!.parentElement!.getBoundingClientRect();
      const name = element.getBoundingClientRect();
      return { left: name.left, right: name.right, clipLeft: clip.left, clipRight: clip.right };
    });
    expect(tail.left).toBeGreaterThanOrEqual(tail.clipLeft - 1);
    expect(tail.right).toBeLessThanOrEqual(tail.clipRight + 1);
    await page.screenshot({ path: testInfo.outputPath("summary.png") });
    await longPath.hover();
    const hint = page.getByRole("tooltip");
    await expect(hint).toHaveText(longEditPath);
    const surface = page.locator('[data-radix-popper-content-wrapper] > [data-state="delayed-open"], [data-radix-popper-content-wrapper] > [data-state="instant-open"]');
    const hintBounds = await surface.boundingBox();
    expect(hintBounds!.x).toBeGreaterThanOrEqual(0);
    expect(hintBounds!.x + hintBounds!.width).toBeLessThanOrEqual(width);
    expect(await surface.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("full-path-hint.png") });
    await page.mouse.move(0, 0);
    await longPath.focus();
    await expect(hint).toHaveText(longEditPath);
    await longPath.press("Enter");
    await expect(page.getByLabel("Opened file")).toHaveText(longEditPath);
    await expect(hint).toBeHidden();
    await page.getByRole("button", { name: /View changes/ }).first().click();
    await expect(page.getByTestId("file-edit-diff")).toBeVisible();
    const imagePath = references.nth(3);
    await expect(imagePath).toContainText("…");
    await imagePath.hover();
    await expect(hint).toContainText(longEditPath.replace("serve_fixture.py", "screenshot.png"));
    await expect(surface.locator(".select-text")).toHaveText(longEditPath.replace("serve_fixture.py", "screenshot.png"));
    await expect(page.getByTestId("file-image-quick-look")).toHaveCount(1);
    await expect(surface.locator('[data-testid="file-image-quick-look"] img:visible')).toHaveCount(1);
    expect(await surface.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("image-path-hint.png") });
    await page.mouse.move(0, 0);
    await imagePath.focus();
    await expect(hint).toContainText(longEditPath.replace("serve_fixture.py", "screenshot.png"));
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.getByLabel("File edits").evaluate((element) => { (element as HTMLElement).style.maxWidth = "none"; });
    await expect(longPath).not.toContainText("…");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
