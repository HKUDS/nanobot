import { expect, test } from "@playwright/test";

test("switches the interface direction with the language preference", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=skeleton-additions&surface=settings&section=appearance&state=loaded");
  await page.getByRole("combobox", { name: "Change language" }).click();
  await page.getByRole("option", { name: "עברית" }).click();

  const root = page.locator("html");
  await expect(root).toHaveAttribute("lang", "he");
  await expect(root).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("combobox", { name: "שינוי שפה" })).toHaveText("עברית");
  await page.reload();
  await expect(root).toHaveAttribute("dir", "rtl");
  await page.getByRole("combobox", { name: "שינוי שפה" }).click();
  await expect(page.getByRole("listbox")).toHaveCSS("direction", "rtl");
  await page.getByRole("option", { name: "English" }).click();
  await expect(root).toHaveAttribute("lang", "en");
  await expect(root).toHaveAttribute("dir", "ltr");
});

for (const locale of ["en-US", "he-IL"]) {
  test.describe(locale, () => {
    test.use({ locale });

    test("renders mixed-direction prose and keeps code LTR", async ({ page }) => {
      await page.goto("/browser/fixture.html?case=bidi");
      const prose = page.locator(".markdown-content");
      const heading = prose.getByRole("heading");
      const english = prose.getByText("This paragraph starts in English", { exact: false });

      await expect(heading).toHaveCSS("unicode-bidi", "plaintext");
      const textOffset = (element: Element) => {
        const range = document.createRange();
        range.selectNodeContents(element);
        return range.getBoundingClientRect().left - element.getBoundingClientRect().left;
      };
      expect(await heading.evaluate(textOffset)).toBeGreaterThan(100);
      expect(await english.evaluate(textOffset)).toBeLessThan(2);
      await expect(prose.getByRole("list")).toHaveCSS("direction", "rtl");
      await expect(prose.getByRole("listitem").first()).toHaveCSS("unicode-bidi", "plaintext");
      await expect(prose.locator("blockquote")).toHaveCSS("direction", "rtl");
      await expect(prose.locator("pre")).toHaveCSS("direction", "ltr");
      await expect(prose.locator("pre")).toHaveCSS("unicode-bidi", "isolate");
      await expect(prose.locator("p code").first()).toHaveCSS("direction", "ltr");

      const composer = page.getByRole("textbox");
      await composer.fill("אפשר להריץ git status?");
      await expect(composer).toHaveCSS("direction", "rtl");
      await expect(composer).toHaveCSS("unicode-bidi", "plaintext");
      await composer.fill("Can I run git status? אפשר?");
      await expect(composer).toHaveCSS("direction", "ltr");
    });
  });
}

test.describe("Hebrew credentials", () => {
  test.use({ locale: "he-IL" });

  test("revealing an API key preserves its direction and value", async ({ page }) => {
    await page.goto("/gallery.html#component=nanobot%2Fchannels%2Flinear%2Fwebui%2FLinearSecretField.tsx");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    const preview = page.locator(".gallery-preview");
    const field = preview.locator('input[type="password"]');
    await field.fill("example_key-12/34=");
    await expect(field).toHaveCSS("direction", "ltr");
    await preview.getByRole("group", { name: "מפתח API" }).locator("button[aria-label]").click();
    const revealed = preview.getByRole("textbox", { name: "מפתח API" });
    await expect(revealed).toHaveValue("example_key-12/34=");
    await expect(revealed).toHaveCSS("direction", "ltr");
  });
});
