import { expect, test, type Page } from "@playwright/test";

const fixture = "/browser/fixture.html?case=queued-guidance";
const storageKey = "nanobot.webui.composerQueuedGuidance.v1:queued-fixture";

async function queue(page: Page, text = "Confirm this instruction") {
  const input = page.getByRole("textbox", { name: "Message input", exact: true });
  await input.fill(text);
  await input.press("Enter");
  await expect(page.getByRole("group", { name: "Waiting to send" })).toContainText(text);
}

for (const width of [1440, 390]) {
  test(`a new page retains waiting content without executing it (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(fixture);
    await queue(page);
    await page.goto(`${fixture}&complete`);
    await expect(page.getByRole("group", { name: "Waiting to send" })).toContainText("Confirm this instruction");
    await expect(page.getByLabel("Submitted messages")).toHaveText("[]");
    await page.getByRole("textbox", { name: "Message input", exact: true }).press("Enter");
    await expect(page.getByLabel("Submitted messages")).toHaveText('[{"text":"Confirm this instruction"}]');
    await expect(page.getByRole("group", { name: "Waiting to send" })).toHaveCount(0);
  });

  for (const interaction of ["refocus", "clear edits"] as const) {
    test(`empty Enter sends waiting content after ${interaction} (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(fixture);
      await queue(page);
      const input = page.getByRole("textbox", { name: "Message input", exact: true });
      if (interaction === "refocus") {
        await input.press("Shift+Tab");
        await expect(input).not.toBeFocused();
        await page.keyboard.press("Tab");
      } else {
        await input.press("x");
        await input.press("Backspace");
      }
      await expect(input).toBeFocused();
      await expect(input).toHaveValue("");
      await expect(page.getByLabel("Submitted messages")).toHaveText("[]");
      await input.press("Enter");
      await expect(page.getByLabel("Submitted messages")).toHaveText('[{"text":"Confirm this instruction","options":{"continueActiveTurn":true}}]');
      await expect(page.getByRole("group", { name: "Waiting to send" })).toHaveCount(0);
    });
  }
}

test("desktop Shift+Enter keeps waiting content until the editor is empty again", async ({ page }) => {
  await page.goto(fixture);
  await queue(page);
  const input = page.getByRole("textbox", { name: "Message input", exact: true });
  await input.press("Shift+Enter");
  await expect(input).toHaveValue("\n");
  await input.press("Enter");
  await expect(page.getByLabel("Submitted messages")).toHaveText("[]");
  await expect(page.getByRole("group", { name: "Waiting to send" })).toContainText("Confirm this instruction");
  await input.press("Backspace");
  await expect(input).toHaveValue("");
  await input.press("Enter");
  await expect(page.getByLabel("Submitted messages")).toHaveText('[{"text":"Confirm this instruction","options":{"continueActiveTurn":true}}]');
});

test("empty Enter sends waiting content after switching away and back", async ({ page }) => {
  await page.goto(fixture);
  await queue(page);
  await page.getByRole("button", { name: "Switch topic" }).click();
  await page.getByRole("button", { name: "Switch topic" }).click();
  await expect(page.getByLabel("Submitted messages")).toHaveText("[]");
  await page.getByRole("textbox", { name: "Message input", exact: true }).press("Enter");
  await expect(page.getByLabel("Submitted messages")).toHaveText('[{"text":"Confirm this instruction","options":{"continueActiveTurn":true}}]');
  await expect(page.getByRole("group", { name: "Waiting to send" })).toHaveCount(0);
});

test("touch Enter keeps a restored message waiting until Send now is clicked", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  try {
    const page = await context.newPage();
    await page.goto(fixture);
    await page.evaluate((key) => localStorage.setItem(key, JSON.stringify([
      { id: "touch-draft", text: "Confirm this instruction", autoPaused: true },
    ])), storageKey);
    await page.reload();
    const input = page.getByRole("textbox", { name: "Message input", exact: true });
    await input.press("Enter");
    await expect(input).toHaveValue("\n");
    await expect(page.getByLabel("Submitted messages")).toHaveText("[]");
    await expect(page.getByRole("group", { name: "Waiting to send" })).toContainText("Confirm this instruction");
    await page.getByRole("button", { name: "Send now", exact: true }).click();
    await expect(page.getByLabel("Submitted messages")).toHaveText('[{"text":"Confirm this instruction","options":{"continueActiveTurn":true}}]');
  } finally {
    await context.close();
  }
});

test("switching topics in the live page retains one automatic send", async ({ page }) => {
  await page.goto(fixture);
  await queue(page);
  await page.getByRole("button", { name: "Switch topic" }).click();
  await page.getByRole("button", { name: "Complete original reply" }).click();
  await page.getByRole("button", { name: "Switch topic" }).click();
  await expect(page.getByLabel("Submitted messages")).toHaveText('[{"text":"Confirm this instruction"}]');
  await expect(page.getByRole("group", { name: "Waiting to send" })).toHaveCount(0);
});

test("leaving and returning through browser history requires manual delivery", async ({ page }) => {
  await page.goto(fixture);
  await queue(page);
  await page.goto("about:blank");
  await page.goBack();
  await page.getByRole("button", { name: "Complete original reply" }).click();
  await expect(page.getByRole("group", { name: "Waiting to send" })).toContainText("Confirm this instruction");
  await expect(page.getByLabel("Submitted messages")).toHaveText("[]");
  await page.getByRole("button", { name: "Send now", exact: true }).click();
  await expect(page.getByLabel("Submitted messages")).toHaveText('[{"text":"Confirm this instruction"}]');
});

test("legacy completed-turn drafts preserve every field until an explicit send", async ({ page }) => {
  await page.goto(fixture);
  const draft = {
    id: "queued-prompt-1792147773397-1", text: "Remember @alpha", autoAfterTurnId: "turn-a",
    quotedContext: "Original quote", sessionMentions: [{ name: "alpha", title: "Alpha", session_key: "websocket:alpha" }],
    images: [{ dataUrl: "data:text/plain;base64,aGVsbG8=", kind: "file", name: "notes.txt" }],
  };
  await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify([value])), { key: storageKey, value: draft });
  await page.goto(`${fixture}&complete`);
  await expect(page.getByRole("group", { name: "Waiting to send" })).toContainText("Remember @alpha");
  await expect(page.getByLabel("Submitted messages")).toHaveText("[]");
  await page.getByRole("button", { name: "Send now", exact: true }).click();
  const sent = JSON.parse(await page.getByLabel("Submitted messages").textContent() ?? "null");
  expect(sent).toEqual([{
    text: draft.text,
    images: [{ media: { data_url: draft.images[0].dataUrl, name: "notes.txt" }, preview: { kind: "file", url: draft.images[0].dataUrl, name: "notes.txt" } }],
    options: { quotedContext: draft.quotedContext, sessionMentions: draft.sessionMentions },
  }]);
});
