import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"] as const) {
  for (const width of [360, 1024]) {
    test(`links match edit filenames in ${theme} at ${width}px`, async ({ page }, testInfo) => {
      await page.route("https://**/*", (route) => route.abort());
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/browser/fixture.html?case=file-edit-path");
      await page.evaluate((dark) => document.documentElement.classList.toggle("dark", dark), theme === "dark");
      const filename = page.getByTestId("activity-file-reference").first().getByText("serve_fixture.py", { exact: true });
      const color = theme === "light" ? "rgb(3, 105, 161)" : "rgb(186, 230, 253)";
      await expect(filename).toHaveCSS("color", color);
      const links = page.getByRole("link");
      await expect(links).toHaveCount(3);
      for (const link of await links.all()) {
        await expect(link).toHaveCSS("color", color);
        await expect(link).toHaveAttribute("target", "_blank");
        await expect(link).toHaveAttribute("rel", "noreferrer noopener");
      }
      const ordinaryLink = page.getByRole("link", { name: "NAN-368", exact: true });
      await ordinaryLink.hover();
      await expect(ordinaryLink).toHaveCSS("color", theme === "light" ? "rgb(7, 89, 133)" : "rgb(224, 242, 254)");
      await expect(ordinaryLink).toHaveCSS("text-decoration-line", "underline");
      await ordinaryLink.focus();
      await expect(ordinaryLink).toBeFocused();
      await page.mouse.move(0, 0);
      await expect(ordinaryLink).toHaveCSS("color", color);
      await page.screenshot({ path: testInfo.outputPath(`${theme}-${width}.png`), fullPage: true });
      await page.getByTestId("activity-file-reference").first().press("Enter");
      await expect(page.getByLabel("Opened file")).toContainText("serve_fixture.py");
    });
  }
}
