import { expect, test } from "@playwright/test";

for (const locale of ["en", "zh-CN"]) {
  for (const width of [390, 1280]) {
    test(`request parameter text aligns in ${locale} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((language) => localStorage.setItem("nanobot.locale", language), locale);
      await page.goto("/gallery.html#component=webui%2Fsrc%2Fcomponents%2Fsettings%2Fmodels%2FProviderParameterFields.tsx");
      const preview = page.getByRole("region", { name: "Component preview" });
      const rows = preview.getByRole("button");
      await expect(rows).toHaveCount(3);

      for (const row of await rows.all()) {
        const text = await row.locator(":scope > span").evaluateAll((elements) => elements.map((element) => {
          const style = getComputedStyle(element);
          const bounds = element.getBoundingClientRect();
          return { fontSize: style.fontSize, lineHeight: style.lineHeight, top: bounds.top, height: bounds.height };
        }));
        expect(text).toHaveLength(3);
        for (const item of text.slice(1)) {
          expect(item.fontSize).toBe(text[0].fontSize);
          expect(item.lineHeight).toBe(text[0].lineHeight);
          expect(item.top).toBeCloseTo(text[0].top, 2);
          expect(item.height).toBeCloseTo(text[0].height, 2);
        }
      }
    });
  }
}
