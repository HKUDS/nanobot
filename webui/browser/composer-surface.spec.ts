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
      await page.getByTestId("hero-greeting").click();
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

    test("composer focus preserves the active goal's blue ring", async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto("/browser/fixture.html?case=composer-action&goal");
      const surface = page.locator(".thread-composer-surface");
      await expect(surface).toBeVisible();
      const ring = await surface.evaluate(element => {
        const probe = document.createElement("span");
        probe.style.color = getComputedStyle(element).getPropertyValue("--tw-ring-color");
        document.body.append(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
      });
      const input = page.getByRole("textbox", { name: "Message input" });
      await input.blur();
      const rest = await surface.evaluate(element => getComputedStyle(element).boxShadow);
      expect(rest).toContain(ring);
      await input.focus();
      const focused = await surface.evaluate(element => getComputedStyle(element).boxShadow);
      expect(focused).toContain(ring);
      expect(focused).toBe(rest);
    });
  });
}
