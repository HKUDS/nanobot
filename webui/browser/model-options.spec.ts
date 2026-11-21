import { expect, test, type Locator } from "@playwright/test";

async function expectSpeedCircle(button: Locator, track: { y: number; height: number }) {
  const face = button.locator(":scope > [aria-hidden]");
  await expect(face).toHaveCSS("corner-shape", /^(round|superellipse\(1\))$/);
  const { y, width, height } = (await face.boundingBox())!;
  expect(height).toBe(track.height);
  expect(width).toBe(height);
  expect(y).toBeCloseTo(track.y, 0);
  expect(await face.evaluate((element) => Number.parseFloat(getComputedStyle(element).borderTopLeftRadius))).toBeGreaterThanOrEqual(height / 2);
  await expect(button).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
}

for (const width of [390, 1280]) {
  test(`current-chat model options preserve the compact preset menu at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=model-options");
    await page.getByRole("button", { name: "Default", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
    const selected = dialog.getByRole("option", { name: "default", exact: true });
    await expect(selected).toHaveAttribute("aria-selected", "true");
    await dialog.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));
    const selectedBefore = await selected.boundingBox();
    const effort = dialog.getByRole("slider", { name: "Reasoning effort" });
    const fast = dialog.getByRole("button", { name: "Fast", exact: true });
    await expect(effort).toHaveAttribute("aria-valuetext", "medium");
    await expect(fast).toHaveAttribute("aria-pressed", "false");
    await effort.press("ArrowRight");
    await expect(effort).toHaveAttribute("aria-valuetext", "high");
    await fast.click();
    await expect(page.getByLabel("Sent model options")).toHaveText("No model options sent");
    const selectedAfter = await selected.boundingBox();
    expect(selectedAfter?.height).toBe(selectedBefore?.height);
    expect(selectedAfter?.x).toBe(selectedBefore?.x);
    const row = (await dialog.locator(".model-options-row").boundingBox())!;
    const list = (await dialog.getByRole("listbox").boundingBox())!;
    expect(Math.abs(row.x - selectedAfter!.x)).toBeLessThan(1);
    expect(Math.abs(row.width - list.width)).toBeLessThan(1);
    const track = (await dialog.locator(".reasoning-effort-track").boundingBox())!;
    const thumb = (await dialog.locator(".reasoning-effort-thumb").boundingBox())!;
    expect(track.height).toBe(20);
    expect(thumb.height).toBe(24);
    await expectSpeedCircle(fast, track);
    const stops = await dialog.locator(".reasoning-effort-tick").evaluateAll((elements) =>
      elements.map((element) => element.getBoundingClientRect().x),
    );
    expect(stops).toHaveLength(5);
    for (let i = 1; i < stops.length; i++) {
      expect(stops[i] - stops[i - 1]).toBeCloseTo(thumb.width);
    }
    const label = (await dialog.getByText("Reasoning effort", { exact: true }).boundingBox())!;
    const icon = (await fast.boundingBox())!;
    const centerY = ({ y, height }: { y: number; height: number }) => y + height / 2;
    expect(label.x + label.width).toBeLessThan(track.x);
    const speedGap = icon.x - track.x - track.width;
    expect(speedGap).toBeGreaterThan(0);
    expect(speedGap).toBeLessThanOrEqual(6);
    expect(row.x + row.width - icon.x - icon.width).toBeLessThanOrEqual(12);
    for (const item of [label, thumb, icon]) {
      expect(Math.abs(centerY(item) - centerY(track))).toBeLessThan(1);
    }
    if (width === 390) {
      expect((await effort.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      expect((await fast.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      expect(selectedBefore!.height).toBeGreaterThanOrEqual(44);
    }
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.mouse.move(0, 0);
    await dialog.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));
    await page.screenshot({ path: testInfo.outputPath(`model-options-${width}.png`) });
    await dialog.press("Escape");
    await page.getByLabel("Message input").fill("Send with these options");
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    await expect(page.getByLabel("Sent model options")).toHaveText("Reasoning: high; Codex Fast: on");
    await page.reload();
    await page.getByRole("button", { name: "Default", exact: true }).click();
    await expect(effort).toHaveAttribute("aria-valuetext", "high");
    await expect(fast).toHaveAttribute("aria-pressed", "true");
    await dialog.getByRole("option", { name: "Review", exact: true }).click();
    await page.getByRole("button", { name: "Review", exact: true }).click();
    await expect(effort).toHaveAttribute("aria-valuetext", "medium");
    await expect(fast).toHaveAttribute("aria-pressed", "false");
    if (width === 1280) {
      await fast.focus();
      await expect(page.getByRole("tooltip")).toContainText("Faster responses, increased usage.");
    }
  });
}

test("a long preset list scrolls without moving the model controls in a short viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 380 });
  await page.goto("/browser/fixture.html?case=model-options&many-presets&ultrafast");
  await page.getByRole("button", { name: "Default", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
  const list = dialog.getByRole("listbox");
  const effort = dialog.getByRole("slider", { name: "Reasoning effort" });
  const manage = dialog.getByRole("button", { name: "Manage presets" });
  await dialog.evaluate((node) => Promise.all(node.getAnimations().map((animation) => animation.finished)));
  await expect(manage).toBeInViewport({ ratio: 1 });
  expect(await dialog.evaluate((node) => node.scrollHeight - node.clientHeight)).toBeLessThanOrEqual(1);
  const effortBefore = await effort.boundingBox();
  const manageBefore = await manage.boundingBox();
  await list.hover();
  await page.mouse.wheel(0, 100);
  await expect.poll(() => list.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  expect(await effort.boundingBox()).toEqual(effortBefore);
  expect(await manage.boundingBox()).toEqual(manageBefore);

  await list.getByRole("option", { name: "default", exact: true }).press("End");
  const last = list.getByRole("option", { name: "Example 12", exact: true });
  await expect(last).toBeFocused();
  await expect(last).toBeInViewport({ ratio: 0.9 });
  await last.press("Enter");
  await expect(page.getByRole("button", { name: "Example 12", exact: true })).toBeVisible();
});

test("Temporary Chats do not expose model option controls", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=model-options&temporary");
  await page.getByRole("button", { name: "Default", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Switch model", exact: true })).toBeVisible();
  await expect(page.getByRole("slider", { name: "Reasoning effort" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Fast", exact: true })).toHaveCount(0);
});

test("reselecting medium and choosing Ultrafast sends and remembers both concrete values", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/browser/fixture.html?case=model-options&ultrafast&dark");
  const open = page.getByRole("button", { name: "Default", exact: true });
  await open.click();
  const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
  const speeds = dialog.getByRole("group", { name: "Fast" });
  const fast = speeds.getByRole("button", { name: "Fast", exact: true });
  const effort = dialog.getByRole("slider", { name: "Reasoning effort" });
  await expect(effort).toHaveAttribute("aria-valuetext", "medium");
  await dialog.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));
  const ticks = dialog.locator(".reasoning-effort-tick");
  const medium = (await ticks.nth(2).boundingBox())!;
  const high = (await ticks.nth(3).boundingBox())!;
  const sliderBefore = (await effort.boundingBox())!;
  const speedBounds = (await speeds.boundingBox())!;
  const speedGap = speedBounds.x - sliderBefore.x - sliderBefore.width;
  expect(speedGap).toBeGreaterThan(0);
  expect(speedGap).toBeLessThanOrEqual(6);
  expect(Math.abs(speedBounds.y + speedBounds.height / 2 - sliderBefore.y - sliderBefore.height / 2)).toBeLessThan(1);
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  const startX = medium.x + medium.width / 2;
  const endX = high.x + high.width / 2;
  const y = medium.y + medium.height / 2;
  const hint = page.getByRole("tooltip");
  await page.mouse.move(startX, y);
  await expect(hint).toBeHidden();
  await page.mouse.down();
  await expect(hint).toHaveText("medium");
  const pointerX = startX + 0.7 * (endX - startX);
  await page.mouse.move(pointerX, y, { steps: 5 });
  await expect(hint).toHaveText("high");
  await expect(effort).toHaveAttribute("aria-valuetext", "medium");
  expect(await effort.boundingBox()).toEqual(sliderBefore);
  const thumbCenter = async () => {
    const thumb = (await dialog.locator(".reasoning-effort-thumb").boundingBox())!;
    return thumb.x + thumb.width / 2;
  };
  await expect.poll(async () => Math.abs(await thumbCenter() - pointerX)).toBeLessThan(2);
  await page.mouse.up();
  await expect(hint).toBeHidden();
  await expect(effort).toHaveAttribute("aria-valuetext", "high");
  await expect.poll(async () => Math.abs(await thumbCenter() - endX)).toBeLessThan(1);
  await effort.press("ArrowLeft");
  const ultrafast = speeds.getByRole("button", { name: "Ultrafast" });
  await fast.press("Space");
  await expect(fast).toHaveAttribute("aria-pressed", "true");
  await ultrafast.click();
  await expect(ultrafast).toHaveAttribute("aria-pressed", "true");
  await expect(fast).toHaveAttribute("aria-pressed", "false");
  const track = (await dialog.locator(".reasoning-effort-track").boundingBox())!;
  await expectSpeedCircle(fast, track);
  await expectSpeedCircle(ultrafast, track);
  expect(await speeds.evaluate((group) => [...group.querySelectorAll("button")].every((button) =>
    button.scrollWidth <= button.clientWidth + 1 && button.offsetWidth >= 44 && button.offsetHeight >= 44,
  ))).toBe(true);
  await dialog.locator(".model-options-row").screenshot({ path: testInfo.outputPath("model-options-ultrafast-320.png") });
  await dialog.press("Escape");
  await page.getByLabel("Message input").fill("Test this speed");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByLabel("Sent model options")).toHaveText("Reasoning: medium; Codex Fast: ultrafast");
  await page.reload();
  await open.click();
  await expect(effort).toHaveAttribute("aria-valuetext", "medium");
  await expect(ultrafast).toHaveAttribute("aria-pressed", "true");
  await ultrafast.click();
  await expect(ultrafast).toHaveAttribute("aria-pressed", "false");
  await dialog.press("Escape");
  await page.getByLabel("Message input").fill("Turn fast mode off");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByLabel("Sent model options")).toHaveText("Reasoning: medium; Codex Fast: off");
});

test("provider examples switch from Codex to direct API and gateway capabilities", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=model-options&ultrafast");
  const navigation = page.getByRole("navigation", { name: "Provider examples" });
  await navigation.getByRole("link", { name: "Direct APIs" }).click();
  await page.getByRole("button", { name: "Default", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
  const reasoning = dialog.getByRole("slider", { name: "Reasoning effort" });
  await expect(reasoning).toHaveAttribute("aria-valuetext", "high");
  await expect(dialog.getByRole("button", { name: "Fast", exact: true })).toHaveCount(0);
  await reasoning.press("End");
  await expect(reasoning).toHaveAttribute("aria-valuetext", "max");
  await dialog.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));
  const track = (await dialog.locator(".reasoning-effort-track").boundingBox())!;
  const fill = (await dialog.locator(".reasoning-effort-fill").boundingBox())!;
  const thumb = (await dialog.locator(".reasoning-effort-thumb").boundingBox())!;
  expect(thumb.x + thumb.width).toBeGreaterThan(track.x + track.width);
  expect(Math.abs(fill.x + fill.width - thumb.x - thumb.width / 2)).toBeLessThan(1);
  await dialog.press("Escape");
  await page.getByLabel("Message input").fill("Review direct API reasoning options");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByLabel("Sent model options")).toHaveText("Reasoning: max; Codex Fast: unchanged");
  await navigation.getByRole("link", { name: "Gateways" }).click();
  await page.getByRole("button", { name: "Default", exact: true }).click();
  await expect(reasoning).toHaveAttribute("aria-valuetext", "Auto");
});

test("keeps the reasoning slider track visible while a Codex preset awaits its effort levels", async ({ page }) => {
  const catalogUrl = /\/api\/settings\/provider-models\?provider=openai_codex$/;
  let releaseCatalog!: () => void;
  const catalogGated = new Promise<void>((resolve) => { releaseCatalog = resolve; });
  await page.route(catalogUrl, async (route) => {
    await catalogGated;
    await route.fulfill({ json: {
      provider: "openai_codex", label: "OpenAI Codex", status: "available", catalog_kind: "hybrid", source: "remote", model_count: 1,
      models: [{ id: "openai-codex/gpt-6.2-sol", reasoning_efforts: ["low", "medium", "high", "xhigh", "max", "ultra"] }],
    } });
  });
  await page.goto("/browser/fixture.html?case=model-options&codex-catalog");
  const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
  const effort = dialog.getByRole("slider", { name: "Reasoning effort" });
  try {
    await Promise.all([page.waitForRequest(catalogUrl), page.getByRole("button", { name: "Default", exact: true }).click()]);
    await expect(dialog.locator(".reasoning-effort-track")).toBeVisible();
    await expect(dialog.getByText("xhigh", { exact: true })).toBeVisible();
    await expect(dialog.getByRole("combobox", { name: "Reasoning effort" })).toHaveCount(0);
    await expect(effort).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Fast", exact: true })).toBeEnabled();
  } finally {
    releaseCatalog();
  }
  await expect(effort).toHaveAttribute("aria-valuetext", "xhigh");
  await effort.press("ArrowLeft");
  await expect(effort).toHaveAttribute("aria-valuetext", "high");
});

for (const { width, height, theme } of [
  { width: 1280, height: 900, theme: "light" },
  { width: 390, height: 440, theme: "dark" },
]) {
  test(`selects a custom preset's reasoning effort in the themed picker at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await page.goto(`/browser/fixture.html?case=model-options&group=local&${theme}`);
    // Loading an empty thread moves the composer into the welcome layout.
    const welcome = page.getByTestId("thread-welcome-layout");
    await welcome.getByRole("button", { name: "Default", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
    await dialog.getByRole("option", { name: "Custom API", exact: true }).click();
    await page.getByRole("button", { name: "Custom API", exact: true }).click();
    const effort = dialog.getByRole("combobox", { name: "Reasoning effort" });
    await expect(effort).toHaveText("extended");
    await dialog.evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished)));
    await effort.press("Enter");
    const list = page.getByRole("listbox").filter({ has: page.getByRole("option", { name: "extended", exact: true }) });
    const current = list.getByRole("option", { name: "extended", exact: true });
    const low = list.getByRole("option", { name: "low", exact: true });
    await expect(current).toBeFocused();
    await expect(current).toHaveAttribute("aria-selected", "true");
    await expect(low).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: testInfo.outputPath(`custom-reasoning-effort-${theme}.png`) });
    await current.press("Home");
    await expect(low).toBeFocused();
    await low.press("Escape");
    await expect(list).toBeHidden();
    await expect(effort).toBeFocused();
    await effort.click();
    await low.click();
    await expect(effort).toHaveText("low");
    await effort.press("Escape");
    await page.getByLabel("Message input").fill("Review custom API reasoning options");
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    await expect(page.getByLabel("Sent model options")).toHaveText("Reasoning: low; Codex Fast: unchanged");
  });
}

test("reopening the model picker keeps focus after the previous picker closes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 440 });
  await page.goto("/browser/fixture.html?case=model-options&group=local&dark");
  await page.getByTestId("thread-welcome-layout").getByRole("button", { name: "Default", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
  const preset = dialog.getByRole("option", { name: "Custom API", exact: true });

  // Reopen at the actual exit boundary, before the old surface can restore focus.
  await dialog.evaluate((closing) => {
    const observer = new MutationObserver(() => {
      if (closing.isConnected) return;
      observer.disconnect();
      const trigger = document.querySelector<HTMLButtonElement>(`button[aria-controls="${closing.id}"]`);
      trigger?.focus();
      trigger?.click();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
  await preset.click();
  const trigger = page.getByRole("button", { name: "Custom API", exact: true });
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await dialog.evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished)));
  await expect(preset).toBeFocused();
  await expect(preset).toHaveAttribute("aria-selected", "true");
  await dialog.getByRole("combobox", { name: "Reasoning effort" }).press("Enter");
  await expect(page.getByRole("option", { name: "extended", exact: true })).toBeFocused();
});

test("touch drag previews the next effort without saving it until release", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 1 });
  await page.goto("/browser/fixture.html?case=model-options&ultrafast&dark");
  await page.getByRole("button", { name: "Default", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
  const effort = dialog.getByRole("slider", { name: "Reasoning effort" });
  await expect(effort).toHaveAttribute("aria-valuetext", "medium");
  await dialog.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));
  const ticks = dialog.locator(".reasoning-effort-tick");
  const medium = (await ticks.nth(2).boundingBox())!;
  const high = (await ticks.nth(3).boundingBox())!;
  const startX = medium.x + medium.width / 2;
  const endX = high.x + high.width / 2;
  const y = medium.y + medium.height / 2;
  const touch = (type: "touchStart" | "touchMove" | "touchCancel" | "touchEnd", x?: number) =>
    cdp.send("Input.dispatchTouchEvent", { type, touchPoints: x === undefined ? [] : [{ x, y }] });
  const hint = page.getByRole("tooltip");
  const previewHigh = async () => {
    await touch("touchStart", startX);
    await touch("touchMove", startX + 0.75 * (endX - startX));
    await expect(hint).toHaveText("high");
    await expect(effort).toHaveAttribute("aria-valuetext", "medium");
  };
  await previewHigh();
  await touch("touchCancel");
  await expect(hint).toBeHidden();
  await expect(effort).toHaveAttribute("aria-valuetext", "medium");
  await previewHigh();
  await touch("touchEnd");
  await expect(hint).toBeHidden();
  await expect(effort).toHaveAttribute("aria-valuetext", "high");
});
