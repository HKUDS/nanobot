import { expect, test, type Page } from "@playwright/test";

const previewUrl = "/gallery.html#component=webui%2Fsrc%2Fcomponents%2Fui%2Fsegmented-control.tsx";

async function indicatorGeometry(page: Page) {
  return page.getByRole("region", { name: "Component preview", exact: true }).evaluate((preview) => {
    const selected = preview.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
    const indicator = preview.querySelector<HTMLElement>("[data-segmented-control-indicator]");
    if (!selected || !indicator) return null;
    const tab = selected.getBoundingClientRect();
    const pill = indicator.getBoundingClientRect();
    return {
      fits: Math.abs(tab.left - pill.left) < 1 && Math.abs(tab.width - pill.width) < 1,
      transition: getComputedStyle(indicator).transitionProperty,
    };
  });
}

test("segmented indicator keeps a fixed box and follows differently sized tabs", async ({ page }) => {
  await page.goto(previewUrl);
  const preview = page.getByRole("region", { name: "Component preview", exact: true });
  const tabs = preview.getByRole("tablist", { name: "Example period" });
  const indicator = tabs.locator("[data-segmented-control-indicator]");
  await expect(tabs.getByRole("tab", { name: "Day" })).toHaveAttribute("aria-selected", "true");
  await page.evaluate(() => document.fonts.ready);
  await expect.poll(async () => (await indicatorGeometry(page))?.fits).toBe(true);
  const initialWidth = await indicator.evaluate((element) => element.style.width);

  for (const name of ["Week", "Month", "Day"]) {
    await tabs.getByRole("tab", { name }).click();
    await expect(tabs.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
    await expect.poll(async () => (await indicatorGeometry(page))?.fits).toBe(true);
    expect(await indicator.evaluate((element) => element.style.width)).toBe(initialWidth);
  }
  await expect.poll(async () => (await indicatorGeometry(page))?.transition).toBe("translate, scale");

  await page.locator(".gallery-header").getByRole("combobox").click();
  await page.getByRole("option", { name: "简体中文", exact: true }).click();
  const translated = page.getByRole("region", { name: "组件预览", exact: true });
  await expect(translated.getByRole("tab", { name: "日" })).toBeVisible();
  await expect.poll(async () => {
    const pill = translated.locator("[data-segmented-control-indicator]");
    const day = translated.getByRole("tab", { name: "日" });
    return (await pill.evaluate((element) => element.style.width)) === `${await day.evaluate((element) => (element as HTMLElement).offsetWidth)}px`
      && (await pill.evaluate((element) => getComputedStyle(element).scale)) === "1";
  }).toBe(true);
});

test("reduced motion snaps the resized indicator to its selected tab", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
  await page.setViewportSize({ width: 800, height: 800 });
  await page.goto(previewUrl);
  const tabs = page.getByRole("region", { name: "Component preview", exact: true })
    .getByRole("tablist", { name: "Example period" });
  await tabs.getByRole("tab", { name: "Month" }).click();
  await page.setViewportSize({ width: 390, height: 800 });
  await expect.poll(async () => (await indicatorGeometry(page))?.fits).toBe(true);
  await expect(tabs.locator("[data-segmented-control-indicator]")).toHaveCSS("transition-duration", "0s");
});
