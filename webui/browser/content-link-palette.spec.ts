import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"] as const) {
  for (const width of [360, 1024]) {
    test(`links match edit filenames in ${theme} at ${width}px`, async ({ page }, testInfo) => {
      await page.route("https://**/*", (route) => route.abort());
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/browser/content-link-palette.html");
      await page.evaluate((dark) => document.documentElement.classList.toggle("dark", dark), theme === "dark");
      const filename = page.getByTestId("activity-file-reference").first().getByText("serve_fixture.py", { exact: true });
      const color = theme === "light" ? "rgb(3, 105, 161)" : "rgb(186, 230, 253)";
      const hoverColor = theme === "light" ? "rgb(7, 89, 133)" : "rgb(224, 242, 254)";
      const mutedColor = theme === "light" ? "rgb(98, 98, 106)" : "rgb(184, 184, 184)";
      await expect(filename).toHaveCSS("color", color);
      const links = page.getByRole("link");
      await expect(links).toHaveCount(4);
      for (const link of await links.all()) {
        await expect(link).toHaveCSS("color", color);
        await expect(link).toHaveAttribute("target", "_blank");
        await expect(link).toHaveAttribute("rel", "noreferrer noopener");
      }
      const ordinaryLink = page.getByRole("link", { name: "NAN-368", exact: true });
      await ordinaryLink.hover();
      await expect(ordinaryLink).toHaveCSS("color", hoverColor);
      await expect(ordinaryLink).toHaveCSS("text-decoration-line", "underline");
      await ordinaryLink.focus();
      await expect(ordinaryLink).toBeFocused();
      await page.mouse.move(0, 0);
      await expect(ordinaryLink).toHaveCSS("color", color);

      const inlineFile = page.getByRole("button", { name: "src/report.md" });
      const localLink = page.getByRole("button", { name: "docs/notes.md" });
      const documentLink = page.getByRole("button", { name: "/workspace/notes.md" });
      const rootFile = page.getByTestId("root-file-reference");
      for (const reference of [inlineFile, localLink, documentLink, rootFile]) {
        await expect(reference).toHaveCSS("color", color);
        await reference.hover();
        await expect(reference).toHaveCSS("color", hoverColor);
      }
      await filename.hover();
      await expect(filename).toHaveCSS("color", hoverColor);
      const directory = page.getByTestId("activity-file-reference").nth(1).getByText("src/", { exact: true });
      const unavailable = page.getByTestId("inline-file-path").filter({ hasText: "missing.md" });
      await expect(directory).toHaveCSS("color", mutedColor);
      await expect(unavailable).toHaveCSS("color", mutedColor);
      await expect(unavailable).not.toHaveAttribute("role", "button");
      await inlineFile.focus();
      await expect(inlineFile).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(localLink).toBeFocused();
      await documentLink.focus();
      await documentLink.press("Enter");
      await expect(page.getByLabel("Opened inline file")).toHaveText("/workspace/notes.md");
      await inlineFile.focus();
      await inlineFile.press("Enter");
      await expect(page.getByLabel("Opened inline file")).toHaveText("src/report.md");

      const source = page.getByRole("link", { name: "Project notes, example.com/source" });
      const sourceTitle = source.getByText("Project notes", { exact: true });
      await expect(source).toHaveAttribute("href", "https://example.com/source");
      await expect(sourceTitle).toHaveCSS("color", color);
      await expect(source.getByTestId("activity-web-url")).toHaveCSS("color", mutedColor);
      await source.hover();
      await expect(source).toHaveCSS("color", hoverColor);
      await expect(sourceTitle).toHaveCSS("color", hoverColor);
      await expect(source.getByTestId("activity-web-url")).toHaveCSS("color", mutedColor);
      await source.focus();
      await expect(source).toBeFocused();
      await page.mouse.move(0, 0);
      await expect(source).toHaveCSS("color", color);
      await page.screenshot({ path: testInfo.outputPath(`${theme}-${width}.png`), fullPage: true });
      await page.getByTestId("activity-file-reference").first().press("Enter");
      await expect(page.getByLabel("Opened file")).toContainText("serve_fixture.py");
    });
  }
}
