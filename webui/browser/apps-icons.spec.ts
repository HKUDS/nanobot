import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"]) {
  for (const logos of ["shown", "hidden"]) {
    test(`unbranded Apps initials stay readable in ${theme} mode with logos ${logos}`, async ({ page }) => {
      await page.route("**/missing-app-icon.svg", (route) => route.fulfill({ status: 404, body: "" }));
      await page.goto(`/browser/fixture.html?case=apps&logos=${logos}`);
      await page.locator("html").evaluate((element, dark) => element.classList.toggle("dark", dark), theme === "dark");

      for (const initials of ["NW", "TM"]) {
        const icon = page.getByText(initials, { exact: true });
        await expect(icon).toBeVisible();
        const contrast = await icon.evaluate((element) => {
          const style = getComputedStyle(element);
          const luminance = (color: string) => {
            const channels = color.match(/[\d.]+/g)!.slice(0, 3).map((value) => {
              const channel = Number(value) / 255;
              return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
            });
            return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
          };
          const foreground = luminance(style.color);
          const background = luminance(style.backgroundColor);
          return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
        });
        expect(contrast).toBeGreaterThanOrEqual(4.5);
        await expect(icon).toHaveCSS("width", "36px");
        await expect(icon).toHaveCSS("height", "36px");
      }
      const branded = page.getByText("BE", { exact: true });
      await expect(branded).toHaveCSS("background-color", "rgb(94, 106, 210)");
      await expect(branded).toHaveCSS("color", "rgb(255, 255, 255)");
    });
  }
}
