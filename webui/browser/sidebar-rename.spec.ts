import { expect, test } from "@playwright/test";

for (const method of ["Enter", "Save button"] as const) {
  test(`saving a topic name with ${method} restores appropriate sidebar focus`, async ({ page }) => {
    await page.goto("/browser/fixture.html?case=sidebar-activity");
    const sidebar = page.getByRole("region", { name: "Activity sidebar" });
    const activeTopic = sidebar.getByRole("button", { name: "@bate Review history", exact: true });
    await sidebar.getByRole("button", { name: "Topic actions for Locate messages" }).click();
    await page.getByRole("menuitem", { name: "Rename" }).click();
    const input = sidebar.getByRole("textbox", { name: "Topic name" });
    await expect(input).toBeFocused();
    await input.fill("Renamed topic");

    if (method === "Enter") await input.press("Enter");
    else await sidebar.getByRole("button", { name: "Save", exact: true }).click();

    const renamedTopic = sidebar.getByRole("button", { name: "@jaru Renamed topic", exact: true });
    await expect(renamedTopic).toBeFocused();
    await expect(activeTopic).toHaveAttribute("aria-current", "page");
    await expect(renamedTopic).toHaveCSS("outline-style", method === "Enter" ? "solid" : "none");
    if (method === "Enter") {
      await page.keyboard.press("Tab");
      await expect(sidebar.getByRole("button", { name: "Topic actions for Renamed topic" })).toBeFocused();
    }
  });
}
