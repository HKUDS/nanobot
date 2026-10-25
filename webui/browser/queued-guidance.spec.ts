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
    await page.getByRole("button", { name: "Send now", exact: true }).click();
    await expect(page.getByLabel("Submitted messages")).toHaveText('[{"text":"Confirm this instruction"}]');
    await expect(page.getByRole("group", { name: "Waiting to send" })).toHaveCount(0);
  });
}

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
