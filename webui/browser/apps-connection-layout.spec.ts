import { expect, test, type Locator } from "@playwright/test";

async function rowGeometry(row: Locator) {
  return row.evaluate((element) => {
    const body = element.querySelector<HTMLButtonElement>("button")!;
    const actions = body.nextElementSibling!;
    const title = body.querySelector("h3")!;
    const rowBox = element.getBoundingClientRect();
    const bodyBox = body.getBoundingClientRect();
    const actionsBox = actions.getBoundingClientRect();
    return {
      height: rowBox.height,
      sameLine: Math.abs(bodyBox.y + bodyBox.height / 2 - actionsBox.y - actionsBox.height / 2) < 1,
      noOverlap: bodyBox.right <= actionsBox.left,
      titleFits: title.clientWidth >= title.scrollWidth,
      noOverflow: element.scrollWidth <= element.clientWidth,
    };
  });
}

for (const width of [314, 390, 1280]) {
  for (const locale of ["en", "zh-CN", "fr"] as const) {
    test(`MCP connection controls stay on one row at ${width}px in ${locale}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 850 });
      await page.addInitScript((language) => localStorage.setItem("nanobot.locale", language), locale);
      await page.goto("/browser/fixture.html?case=apps&connection-layout");
      const body = page.getByRole("button", { name: "Linear", exact: true });
      const row = page.locator("article").filter({ has: body });
      const initial = await rowGeometry(row);
      await body.click();
      const dialog = page.getByRole("dialog", { name: "Linear", exact: true });
      await dialog.getByRole("tab").last().click();
      await dialog.getByRole("button", { name: /^(Connect|连接|Connecter)$/ }).click();
      await expect(dialog).not.toBeVisible();
      const cancel = row.getByRole("button", { name: /^(Cancel|取消|Annuler)$/ });
      await expect(cancel).toBeEnabled();
      await expect(body).toHaveAccessibleDescription({ en: "Connecting…", "zh-CN": "正在连接…", fr: "Connexion…" }[locale]);
      const connecting = await rowGeometry(row);
      expect(connecting).toEqual({
        height: initial.height, sameLine: true, noOverlap: true, titleFits: true, noOverflow: true,
      });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await body.focus();
      await page.keyboard.press("Tab");
      await expect(cancel).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(cancel).not.toBeVisible();
      expect(await rowGeometry(row)).toEqual(initial);
    });
  }
}

for (const width of [314, 1280]) {
  test(`runtime MCP connection stays on one row at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 850 });
    await page.goto("/browser/fixture.html?case=apps&connection-layout&runtime");
    const body = page.getByRole("button", { name: "Linear", exact: true });
    const row = page.locator("article").filter({ has: body });
    await expect(row.getByRole("button", { name: "Remove", exact: true })).toBeEnabled();
    expect(await rowGeometry(row)).toMatchObject({
      sameLine: true, noOverlap: true, titleFits: true, noOverflow: true,
    });
  });
}
