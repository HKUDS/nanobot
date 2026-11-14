import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
});

for (const theme of ["light", "dark"]) {
  test.describe(theme, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((theme) => {
        localStorage.setItem("nanobot.locale", "en");
        localStorage.setItem("nanobot-webui.theme", theme);
        document.documentElement.classList.toggle("dark", theme === "dark");
      }, theme);
    });

    test("composer focus keeps the surface and actions stable", async ({ page }) => {
      await page.goto(`/browser/fixture.html?case=new-chat-skeleton${theme === "dark" ? "&dark" : ""}`);
      const surface = page.locator(".thread-composer-surface");
      await expect(surface).toBeVisible();
      const input = page.getByRole("textbox", { name: "Message input" });
      await input.blur();
      await page.getByTestId("thread-empty-region").click();
      const rest = await surface.evaluate(element => getComputedStyle(element).boxShadow);
      const bounds = await surface.boundingBox();
      const footer = await page.locator(".thread-composer-footer").boundingBox();
      await input.focus();
      await expect(input).toBeFocused();
      await expect.poll(() => surface.evaluate(element => getComputedStyle(element).boxShadow)).toBe(rest);
      expect(await surface.boundingBox()).toEqual(bounds);
      expect(await page.locator(".thread-composer-footer").boundingBox()).toEqual(footer);
      await input.fill("Keep the work in focus.");
      await expect(input).toHaveValue("Keep the work in focus.");
    });

  });
}
