import { expect, test } from "@playwright/test";

test("sidebar cat follows the chosen app theme without moving or losing the draft", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    if (!localStorage.getItem("nanobot-webui.theme")) localStorage.setItem("nanobot-webui.theme", "light");
  });
  await page.goto("/browser/fixture.html?case=theme-toggle&chat");
  const mark = page.getByTestId("sidebar-brand-mark");
  const day = mark.locator("img").nth(0);
  const night = mark.locator("img").nth(1);
  await expect.poll(() => mark.locator("img").evaluateAll(elements => elements.every(element => {
    const image = element as HTMLImageElement;
    return image.complete && image.naturalWidth === 759 && image.naturalHeight === 718;
  }))).toBe(true);
  await expect(day).toHaveCSS("opacity", "1");
  await expect(night).toHaveCSS("opacity", "0");
  const before = (await mark.boundingBox())!;
  const draft = page.getByRole("textbox");
  await draft.fill("Keep this draft while the cat gets sleepy");
  await page.getByRole("button", { name: "Toggle theme from header", exact: true }).click();
  await expect(night).toHaveCSS("opacity", "1");
  await expect(day).toHaveCSS("opacity", "0");
  expect(await mark.boundingBox()).toEqual(before);
  await expect(draft).toHaveValue("Keep this draft while the cat gets sleepy");
  await page.reload();
  await expect(night).toHaveCSS("opacity", "1");
  await page.getByRole("button", { name: "Toggle theme from header", exact: true }).click();
  await expect(day).toHaveCSS("opacity", "1");
  await expect(night).toHaveCSS("opacity", "0");
});

test("the sidebar night mark follows live System theme changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    localStorage.setItem("nanobot-webui.theme", "system");
  });
  await page.goto("/browser/fixture.html?case=theme-toggle&chat");
  const images = page.getByTestId("sidebar-brand-mark").locator("img");
  await expect(images.nth(0)).toHaveCSS("opacity", "1");
  await expect(images.nth(1)).toHaveCSS("opacity", "0");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(images.nth(1)).toHaveCSS("opacity", "1");
  await expect(images.nth(0)).toHaveCSS("opacity", "0");
});

test("paired artwork blends in place without native snapshots", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    localStorage.setItem("nanobot-webui.theme", "light");
    Object.defineProperty(document, "startViewTransition", { value: undefined });
  });
  await page.goto("/browser/fixture.html?case=theme-toggle&chat");
  const mark = page.getByTestId("sidebar-brand-mark");
  const box = await mark.boundingBox();
  const draft = page.getByRole("textbox");
  await draft.fill("A draft survives the artwork transition");
  await expect(mark.locator("img").first()).toHaveCSS("opacity", "1");
  // Hold each real opacity transition when it starts, not after a protocol round trip.
  await page.evaluate(() => document.addEventListener("transitionrun", event => {
    const image = event.target as HTMLElement;
    if (!image.matches(".theme-art") || event.propertyName !== "opacity") return;
    for (const fade of image.getAnimations()) { fade.pause(); fade.currentTime = 100; }
  }));
  for (const target of ["dark", "light"]) {
    await page.getByRole("button", { name: "Toggle theme from header", exact: true }).click();
    await expect(mark.locator("img").first()).toHaveCSS("opacity", "0.5");
    const middle = await mark.evaluate(element => {
      const images = Array.from(element.querySelectorAll("img"));
      const fades = images.flatMap(image => image.getAnimations());
      const result = { theme: document.documentElement.className, count: fades.length, opacity: images.map(image => Number(getComputedStyle(image).opacity)) };
      for (const fade of fades) fade.finish();
      return result;
    });
    expect(middle.count).toBe(2);
    expect(middle.theme.includes("dark")).toBe(target === "dark");
    for (const opacity of middle.opacity) expect(opacity).toBeCloseTo(0.5);
    await expect(mark.locator("img").nth(target === "dark" ? 1 : 0)).toHaveCSS("opacity", "1");
    expect(await mark.boundingBox()).toEqual(box);
    await expect(draft).toHaveValue("A draft survives the artwork transition");
    await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
  }
});
