import { expect, test } from "@playwright/test";

for (const locale of ["en", "zh-CN"]) {
  for (const width of [390, 1280]) {
    test(`idle compaction settings in ${locale} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((language) => localStorage.setItem("nanobot.locale", language), locale);
      await page.goto("/browser/fixture.html?case=idle-compaction");
      const chinese = locale === "zh-CN";
      const input = page.getByRole("textbox", { name: chinese ? "空闲时限" : "Idle timeout" });
      const toggle = page.getByRole("switch", { name: chinese ? "空闲自动压缩" : "Auto-compact idle sessions" });
      const persisted = page.getByRole("status", { name: "Persisted minutes" });
      await expect(input).toHaveValue("720");
      for (const draft of ["37", "0"]) {
        await input.fill(draft);
        await page.getByRole("button", { name: chinese ? "取消" : "Cancel", exact: true }).click();
        await expect(input).toHaveValue("720");
        await expect(persisted).toHaveText("720");
      }
      await input.fill("721");
      await expect(persisted).toHaveText("720");
      await page.getByText(chinese ? "分钟" : "minutes", { exact: true }).click();
      await expect(persisted).toHaveText("721");
      await expect(toggle).toBeEnabled();
      await toggle.click();
      await expect(persisted).toHaveText("0");
      await expect(input).toHaveCount(0);
      await page.reload();
      await expect(toggle).not.toBeChecked();
      await toggle.click();
      await expect(input).toHaveValue("15");
      await expect(toggle).toBeEnabled();

      await input.fill("-1");
      await input.press("Enter");
      await expect(input).toHaveAttribute("aria-invalid", "true");
      await expect(input).toHaveValue("-1");
      await expect(persisted).toHaveText("15");
      await input.fill("37");
      // Arm the failure without moving focus and committing the draft first.
      await page.getByRole("button", { name: "Fail next save" }).evaluate((button: HTMLButtonElement) => button.click());
      await input.press("Enter");
      await expect(page.getByText("Fixture save failed")).toBeVisible();
      await expect(input).toHaveValue("37");
      await input.press("Enter");
      await expect(persisted).toHaveText("37");
      await expect(page.getByText("Fixture save failed")).toHaveCount(0);
      await page.reload();
      await expect(input).toHaveValue("37");
      await input.scrollIntoViewIfNeeded();
      const bounds = await input.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: test.info().outputPath(`idle-compaction-${locale}-${width}.png`), fullPage: true });
    });
  }
}
