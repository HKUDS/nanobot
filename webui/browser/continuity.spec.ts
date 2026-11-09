import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
for (const name of ["Conversation actions", "Quick note"]) {
  test(`${name} grows from its anchor and returns keyboard focus at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=continuity");
    // Capture at animation start, before protocol latency can outlive the 150ms entry.
    await page.evaluate(() => {
      const capture = (event: AnimationEvent) => {
        const element = event.target as HTMLElement;
        if (!element.matches("[role=menu], [role=dialog]")) return;
        for (const animation of element.getAnimations()) if (animation instanceof CSSAnimation) animation.pause();
        document.removeEventListener("animationstart", capture);
      };
      document.addEventListener("animationstart", capture);
    });
    const trigger = page.getByRole("button", { name, exact: true, includeHidden: true });
    const before = (await trigger.boundingBox())!;
    await trigger.click();
    const surface = page.getByRole(name === "Quick note" ? "dialog" : "menu");
    await expect(surface).toBeVisible();
    await expect(surface).toHaveCSS("pointer-events", "auto");
    // Keep the entry measurable while Radix resolves the anchor's final geometry.
    await surface.evaluate(element => { for (const animation of element.getAnimations()) if (animation instanceof CSSAnimation) animation.pause(); });
    await expect(surface).toHaveCSS("transform-origin", "0px 0px");
    if (name === "Quick note") await expect(page.getByRole("textbox", { name: "Quick note draft" })).toBeFocused();
    else await expect(surface).toBeFocused();
    const motion = await surface.evaluate(element => {
      const animation = element.getAnimations().find(item => item instanceof CSSAnimation);
      if (!animation) return null;
      animation.pause();
      animation.currentTime = 75;
      const css = getComputedStyle(element);
      const sample = { transform: css.transform, origin: css.transformOrigin, side: element.getAttribute("data-side"), width: element.clientWidth };
      animation.play();
      return sample;
    });
    expect(motion).not.toBeNull();
    expect(motion!.transform).not.toBe("none");
    const origin = motion!.origin.split(" ").map(Number.parseFloat);
    if (motion!.side === "bottom") expect(origin[1]).toBe(0);
    else if (motion!.side === "top") expect(origin[1]).toBeGreaterThan(0);
    expect(Math.abs((await trigger.boundingBox())!.x - before.x)).toBeLessThan(1);
    const box = (await surface.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    // Exercise Escape after the first interactive paint, not before Radix's layer effect.
    await surface.evaluate(() => new Promise(requestAnimationFrame));
    if (name === "Quick note") await page.getByRole("textbox", { name: "Quick note draft" }).press("Escape");
    else await surface.press("Escape");
    await expect(surface).toBeHidden();
    await expect(trigger).toBeFocused();
  });
}
}

test("a sidebar follows its actual exit and preserves an interrupted editor", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=continuity");
  const toggle = page.getByRole("button", { name: "Toggle details", exact: true });
  const panel = page.locator(".file-preview-pane");
  await toggle.click();
  await expect.poll(() => panel.evaluate(element => Math.round(element.getBoundingClientRect().width))).toBe(420);
  await page.getByRole("textbox", { name: "Details draft" }).fill("Keep this draft");
  const original = (await panel.elementHandle())!;
  // Hold the real close in flight; a wall-clock timeout must not remove the surface.
  await page.evaluate(async () => {
    (document.querySelector("button[aria-expanded=true]") as HTMLButtonElement).click();
    await new Promise(requestAnimationFrame);
    const node = document.querySelector(".file-preview-pane")!;
    const animations = [node, node.firstElementChild!].flatMap(element => element.getAnimations());
    for (const animation of animations) { animation.pause(); animation.currentTime = 80; }
  });
  await expect(panel).toHaveAttribute("inert");
  await expect(panel).toHaveAttribute("aria-hidden", "true");
  // This exceeds the old fixed 300ms teardown while the actual exit is paused.
  const heldSince = Date.now();
  await expect.poll(async () => ({
    connected: await original.evaluate(element => element.isConnected),
    held: Date.now() - heldSince >= 350,
  })).toEqual({ connected: true, held: true });
  await toggle.click();
  await expect(panel).not.toHaveAttribute("inert");
  expect(await original.evaluate(element => element === document.querySelector(".file-preview-pane"))).toBe(true);
  await expect(page.getByRole("textbox", { name: "Details draft" })).toHaveValue("Keep this draft");
  await page.getByRole("textbox", { name: "Details draft" }).focus();
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(toggle).toBeFocused();
});

test("folding moves the next row continuously without discarding drafts", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=continuity");
  const toggle = page.getByRole("button", { name: "Advanced options", exact: true });
  const content = page.locator(".inline-disclosure");
  const row = page.getByTestId("following-row");
  const closed = (await row.boundingBox())!.y;
  await toggle.click();
  await expect.poll(() => content.evaluate(element => element.getAnimations().length)).toBe(0);
  await page.getByRole("textbox", { name: "Advanced draft" }).fill("Keep folded draft");
  const expanded = (await row.boundingBox())!.y;
  expect(expanded).toBeGreaterThan(closed + 50);
  await toggle.click();
  const middle = await content.evaluate(element => {
    for (const animation of element.getAnimations()) { animation.pause(); animation.currentTime = 110; }
    const top = document.querySelector("[data-testid=following-row]")!.getBoundingClientRect().y;
    for (const animation of element.getAnimations()) animation.play();
    return top;
  });
  expect(middle).toBeGreaterThan(closed);
  expect(middle).toBeLessThan(expanded);
  await expect(content).toHaveAttribute("inert");
  await toggle.click();
  await expect(page.getByRole("textbox", { name: "Advanced draft" })).toHaveValue("Keep folded draft");
});

test("reduced motion keeps the same controls without travel or delayed teardown", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/browser/fixture.html?case=continuity");
  for (const name of ["Conversation actions", "Quick note"]) {
    const trigger = page.getByRole("button", { name, exact: true });
    await trigger.click();
    const surface = page.getByRole(name === "Quick note" ? "dialog" : "menu");
    await expect(surface).toHaveCSS("animation-name", "none");
    await expect(surface).toHaveCSS("pointer-events", "auto");
    if (name === "Quick note") await expect(page.getByRole("textbox", { name: "Quick note draft" })).toBeFocused();
    else await expect(surface).toBeFocused();
    await surface.evaluate(() => new Promise(requestAnimationFrame));
    if (name === "Quick note") await page.getByRole("textbox", { name: "Quick note draft" }).press("Escape");
    else await surface.press("Escape");
    await expect(surface).toBeHidden();
    await expect(trigger).toBeFocused();
  }
  await page.getByRole("button", { name: "Toggle details", exact: true }).click();
  const panel = page.locator(".file-preview-pane");
  await expect(page.getByRole("textbox", { name: "Details draft" })).toBeVisible();
  await page.getByRole("button", { name: "Close details", exact: true }).click();
  await expect(panel).toHaveCount(0);
});
