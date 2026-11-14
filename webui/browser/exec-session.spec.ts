import { expect, test } from "@playwright/test";

for (const width of [1280, 360]) {
  test(`shows command activity and keeps long check histories inspectable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 720 });
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.goto("/browser/fixture.html?case=exec-session");
    const activity = page.getByRole("region", { name: "Command activity" });
    await expect(activity).toContainText("Waiting for command result curl -u •••• https://example.invalid");
    await page.getByRole("button", { name: "running", exact: true }).click();
    await expect(activity).toContainText("Command was still running at the last check curl -u •••• https://example.invalid");
    await page.getByRole("button", { name: "input", exact: true }).click();
    await expect(activity).toContainText("Sent input curl -u •••• https://example.invalid");
    await page.getByRole("button", { name: "failed", exact: true }).click();
    await expect(activity).toContainText("Command failed (exit code 7) curl -u •••• https://example.invalid");
    await page.getByRole("button", { name: "many", exact: true }).click();
    await expect(activity.getByTestId("latest-activity-wheel")).toContainText("Command was still running at the last check");
    await activity.getByRole("button", { name: /^Working for / }).click();
    const disclosure = activity.getByRole("button", { name: "Show earlier command checks (24)" });
    await expect(activity.getByTestId("activity-step")).toHaveCount(1);
    await disclosure.click();
    await expect(activity.getByTestId("activity-step")).toHaveCount(25);
    await activity.getByRole("button", { name: "Hide earlier command checks (24)" }).click();
    await expect(activity.getByTestId("activity-step")).toHaveCount(1);
    await expect(activity).not.toContainText("012345abcdef");
    await expect(activity).not.toContainText("private-stdin");
    await expect(activity).not.toContainText("secret-value");
    expect(await activity.innerHTML()).not.toContain("secret-value");
    expect(await activity.innerHTML()).not.toContain("012345abcdef");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  });
}
