import { expect, test } from "@playwright/test";

const tile = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="#171717"/><circle cx="16" cy="16" r="10" fill="white"/></svg>';
const mark = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><circle cx="16" cy="16" r="12" fill="#E87D0D"/></svg>';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("https://icons.duckduckgo.com/ip3/linear.app.ico", route => route.fulfill({ contentType: "image/svg+xml", body: tile }));
  await page.route("https://cdn.simpleicons.org/blender", route => route.fulfill({ contentType: "image/svg+xml", body: mark }));
  await page.route("**/api/**", route => route.fulfill({ json: {} }));
});

for (const width of [1280, 360]) {
  for (const dark of [false, true]) {
    test.describe(`${width}px ${dark ? "dark" : "light"} activity logos`, () => {
      test.use({ viewport: { width, height: 700 } });
      test("fits brand images directly to the rounded mark while preserving status and alignment", async ({ page }, testInfo) => {
        await page.goto(`/browser/fixture.html?case=activity-logos${dark ? "&dark" : ""}`);
        for (const phase of ["end", "start", "error"]) {
          const section = page.getByRole("region", { name: phase, exact: true });
          const positions: number[] = [];
          for (const id of ["activity-mcp-logo-linear", "activity-cli-logo-blender"]) {
            const logo = section.getByTestId(id);
            const image = logo.locator("img");
            await expect(image).toBeVisible();
            await expect.poll(() => image.evaluate(node => (node as HTMLImageElement).naturalWidth)).toBe(32);
            const imageBox = (await image.boundingBox())!;
            const frame = (await logo.boundingBox())!;
            expect(frame.width).toBe(16);
            expect(frame.height).toBe(16);
            expect(imageBox).toEqual(frame);
            await expect(logo).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
            await expect(logo).toHaveCSS("border-top-width", "0px");
            await expect(logo).toHaveCSS("box-shadow", "none");
            await expect(logo).toHaveCSS("animation-name", phase === "start" ? "pulse" : "none");
            expect(await logo.evaluate(node => parseFloat(getComputedStyle(node).borderRadius))).toBeGreaterThan(0);
            positions.push(frame.x);
          }
          expect(positions[0]).toBe(positions[1]);
        }
        await expect(page.getByRole("region", { name: "end", exact: true })).toContainText("Used Blender");
        await expect(page.getByRole("region", { name: "start", exact: true })).toContainText("Using Blender");
        await expect(page.getByRole("region", { name: "error", exact: true })).toContainText("Could not use Blender");
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
        await page.locator("main").screenshot({ path: testInfo.outputPath("activity-logos.png") });
      });
    });
  }
}

test("keeps missing and failed logos identifiable in both themes", async ({ page }) => {
  await page.route("**/browser/missing-activity-logo.svg", route => route.fulfill({ status: 404, body: "" }));
  await page.goto("/browser/fixture.html?case=activity-logos&fallback");
  for (const dark of [false, true]) {
    if (dark) await page.getByRole("button", { name: "Toggle theme" }).click();
    for (const phase of ["end", "start", "error"]) {
      const section = page.getByRole("region", { name: phase, exact: true });
      await expect(section.getByTestId("activity-mcp-logo-linear")).toHaveText("L");
      await expect(section.getByTestId("activity-cli-logo-blender")).toHaveText("B");
      for (const logo of [section.getByTestId("activity-mcp-logo-linear"), section.getByTestId("activity-cli-logo-blender")]) {
        await expect(logo).toHaveCSS("width", "16px");
        await expect(logo).toHaveCSS("color", "rgb(255, 255, 255)");
        expect(await logo.evaluate(node => getComputedStyle(node).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
      }
    }
  }
});
