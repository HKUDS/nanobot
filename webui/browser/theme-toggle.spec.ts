import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test.describe(`theme toggle at ${width}px`, () => {
    test.use({ viewport: { width, height: 844 } });

    test("morphs in place, ignores rapid reversals, and stays keyboard accessible", async ({ page }) => {
      await page.addInitScript(() => {
        localStorage.setItem("nanobot.locale", "en");
        if (!localStorage.getItem("nanobot-webui.theme")) localStorage.setItem("nanobot-webui.theme", "light");
      });
      await page.goto("/browser/fixture.html?case=theme-toggle");
      const toggle = page.getByRole("button", { name: "Toggle theme from header", exact: true });
      const icon = toggle.locator("svg");
      await expect(icon).toHaveAttribute("data-theme", "light");
      expect(await icon.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
      const initialBox = await toggle.boundingBox();

      await toggle.click();
      await expect(page.locator("html")).toHaveClass(/dark/);
      const intermediate = await icon.evaluate(async node => {
        await new Promise(requestAnimationFrame);
        const transitions = node.getAnimations({ subtree: true });
        for (const transition of transitions) {
          transition.pause();
          transition.currentTime = 100;
        }
        const core = getComputedStyle(node.querySelector(":scope > circle")!);
        const rays = getComputedStyle(node.querySelector(".theme-toggle-rays")!);
        const result = { radius: parseFloat(core.r), opacity: parseFloat(rays.opacity), count: transitions.length };
        for (const transition of transitions) transition.play();
        return result;
      });
      expect(intermediate.count).toBeGreaterThan(0);
      expect(intermediate.radius).toBeGreaterThan(5);
      expect(intermediate.radius).toBeLessThan(8);
      expect(intermediate.opacity).toBeGreaterThan(0);
      expect(intermediate.opacity).toBeLessThan(1);
      expect(await toggle.boundingBox()).toEqual(initialBox);

      await toggle.click();
      await expect(icon).toHaveAttribute("data-theme", "dark");
      const input = page.getByRole("textbox");
      await input.fill("Typing stays available during the theme change");
      await expect(input).toHaveValue("Typing stays available during the theme change");
      await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
      await expect(icon).toHaveAttribute("data-theme", "dark");
      await toggle.focus();
      await page.keyboard.press("Space");
      await expect(icon).toHaveAttribute("data-theme", "light");
      await expect(page.locator("html")).not.toHaveClass(/dark/);
      await expect(toggle).toBeFocused();
      await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
      expect(await toggle.boundingBox()).toEqual(initialBox);
      await page.reload();
      await expect(icon).toHaveAttribute("data-theme", "light");
      expect(await icon.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
    });
  });
}

test("reduced motion keeps the canvas fade but switches the icon directly", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    localStorage.setItem("nanobot-webui.theme", "dark");
  });
  await page.goto("/browser/fixture.html?case=theme-toggle");
  const toggle = page.getByRole("button", { name: "Toggle theme from header", exact: true });
  const icon = toggle.locator("svg");
  const core = icon.locator(":scope > circle");
  await expect(core).toHaveCSS("r", "5px");
  await toggle.click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await expect(core).toHaveCSS("r", "8px");
  expect(await icon.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
  const middle = await page.locator(".workbench-pane").evaluate(async node => {
    await new Promise(requestAnimationFrame);
    const transitions = node.getAnimations();
    for (const transition of transitions) {
      transition.pause();
      transition.currentTime = 140;
    }
    const color = getComputedStyle(node).backgroundColor;
    for (const transition of transitions) transition.play();
    return color;
  });
  const red = Number(middle.match(/[\d.]+/)![0]);
  expect(red).toBeGreaterThan(48);
  expect(red).toBeLessThan(255);
  await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
  await toggle.click();
  await expect(core).toHaveCSS("r", "5px");
  expect(await icon.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
});
