import { expect, test } from "@playwright/test";

test("inferred files wrap without losing copy text or preview actions", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.goto("/browser/fixture.html?case=inline-file-reference");
  const files = page.getByRole("region", { name: "File references" }).getByTestId("inline-file-path");
  await expect(files).toHaveCount(9);

  for (const state of ["streaming", "complete"]) {
    if (state === "complete") await page.getByRole("button", { name: "Complete message" }).click();
    for (const width of [390, 1024]) {
      await page.setViewportSize({ width, height: 1000 });
      // Spaced and unbroken long paths exercise the two wrapping cases.
      for (const index of [1, 7]) {
        const metrics = await files.nth(index).locator("code").evaluate(node => {
          const bounds = node.closest("p")!.getBoundingClientRect();
          return {
            lines: node.getClientRects().length,
            contained: [...node.getClientRects()].every(rect => rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1),
          };
        });
        expect(metrics.lines).toBeGreaterThan(1);
        expect(metrics.contained).toBe(true);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }

  for (const [index, text] of [
    [1, `notes/${"long directory/".repeat(16)}report.md`],
    [2, String.raw`C:\Users\reader\My Docs\report.md`],
    [4, "cat  \t~/My Docs/report.md"],
  ] as const) {
    const selected = await files.nth(index).locator("code").evaluate(node => {
      const range = document.createRange();
      range.selectNodeContents(node);
      const selection = window.getSelection()!;
      selection.removeAllRanges();
      selection.addRange(range);
      return selection.toString();
    });
    expect(selected).toBe(text);
    await page.keyboard.press("ControlOrMeta+c");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(text);
  }
  await page.evaluate(() => window.getSelection()?.removeAllRanges());
  await expect(files.last()).toHaveText("Short report");

  await files.nth(1).click();
  await expect(page.getByLabel("Opened file")).toHaveText(`notes/${"long directory/".repeat(16)}report.md`);
  const first = files.first();
  await first.press("Enter");
  await expect(page.getByLabel("Opened file")).toHaveText("notes/ready.md");
  await first.click();
  await expect(first).toHaveCSS("box-shadow", "none");
  await page.keyboard.press("Shift+F10");
  const copyMenu = page.getByRole("menu");
  await expect(copyMenu).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(first).toBeFocused();
  await expect(first).not.toHaveCSS("box-shadow", "none");

  await page.keyboard.press("Shift+F10");
  await page.getByRole("menuitem", { name: "Copy absolute path", exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("notes/ready.md");
  await files.nth(6).hover();
  await expect(page.getByTestId("file-image-quick-look").locator("img")).toBeVisible();
});

for (const copied of [true, false]) {
  test(`a narrow preview shows ${copied ? "success" : "failure"} after copying a tab path`, async ({ page, context }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.addInitScript((success) => {
      localStorage.setItem("nanobot.locale", "en");
      if (!success) {
        navigator.clipboard.writeText = async () => { throw new Error("Clipboard denied"); };
        document.execCommand = () => false;
      }
    }, copied);
    await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
    await page.route("**/api/sessions/*/webui-thread?*", route => route.fulfill({ json: {
      schemaVersion: 3, projection: "events", events: [{ event: "message", projection_id: "file", chat_id: "loading-preview", text: "See [notes.txt](notes.txt)." }],
    } }));
    await page.route("**/file-preview?*", route => {
      const query = new URL(route.request().url()).searchParams;
      return route.fulfill({ json: query.has("probe") ? { available: true } : query.has("metadata")
        ? { path: "/workspace/notes.txt", relative_path: "notes.txt" }
        : { path: "/workspace/notes.txt", display_path: "notes.txt", project_path: "/workspace", kind: "text", language: "text", content: "File contents", size: 13, truncated: false } });
    });
    await page.goto("/browser/fixture.html?case=thread-loading");
    await page.getByRole("button", { name: "notes.txt" }).click();
    const preview = page.getByTestId("preview-pane");
    await expect(page.locator(".thread-conversation")).toBeHidden();
    await preview.getByRole("tab", { name: "notes.txt" }).click({ button: "right" });
    await page.getByRole("menuitem", { name: "Copy absolute path" }).click();
    const feedback = preview.getByRole(copied ? "status" : "alert").filter({ hasText: copied ? "Copied" : "Could not copy" });
    await expect(feedback).toBeVisible();
    await expect(feedback).toBeInViewport();
    if (copied) expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("/workspace/notes.txt");
  });
}
