import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  for (const variant of ["hero", "thread"]) {
    test(`composer edge presses send and stop without losing the click (${width}px, ${variant})`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/browser/fixture.html?case=composer-action&composerVariant=${variant}`);
      await page.getByRole("textbox").fill("An edge press");
      const action = page.locator(".composer-primary-action");
      await expect(action).toHaveAccessibleName("Send message");
      for (const status of ["Working", "Stop requested"]) {
        const bounds = (await action.boundingBox())!;
        await page.mouse.move(bounds.x + bounds.width - 0.5, bounds.y + bounds.height / 2);
        await page.mouse.down();
        // Let the press animation settle before releasing at the same edge point.
        await page.waitForTimeout(200);
        await page.mouse.up();
        await expect(page.getByLabel("Execution status")).toHaveText(status);
        expect(await action.boundingBox()).toEqual(bounds);
      }
    });

    test(`composer actions crossfade without shifting or delaying Stop (${width}px, ${variant})`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/browser/fixture.html?case=composer-action&composerVariant=${variant}`);
      const input = page.getByRole("textbox");
      const action = page.locator(".composer-primary-action");
      await expect(action).toHaveAccessibleName("Voice input");
      const bounds = await action.boundingBox();
      const pillBounds = await page.locator(".composer-model-pill").boundingBox();
      expect(bounds!.height).toBe(pillBounds!.height);
      expect(bounds!.y + bounds!.height / 2).toBe(pillBounds!.y + pillBounds!.height / 2);
      const model = page.getByText("Preview", { exact: true });
      const modelBounds = await model.boundingBox();
      const send = action.locator('[data-action-icon="send"]');
      await expect(send).toHaveCSS("opacity", "0");
      const capture = await send.evaluateHandle((icon) => {
        // Sample the real transition at activation, before a test round trip can outlast it.
        const sample = { opacity: 0 };
        const observer = new MutationObserver(() => {
          if (!icon.hasAttribute("data-active")) return;
          observer.disconnect();
          const fade = icon.getAnimations().find((animation) => animation instanceof CSSTransition
            && animation.transitionProperty === "opacity");
          if (!fade || !fade.effect) return;
          fade.pause();
          fade.currentTime = Number(fade.effect.getTiming().duration) / 2;
          sample.opacity = Number(getComputedStyle(icon).opacity);
          fade.play();
        });
        observer.observe(icon, { attributes: true, attributeFilter: ["data-active"] });
        return sample;
      });
      await input.fill("Please work");
      await expect(action).toHaveAccessibleName("Send message");
      const { opacity } = await capture.jsonValue();
      await capture.dispose();
      expect(opacity).toBeGreaterThan(0);
      expect(opacity).toBeLessThan(1);
      await expect(send).toHaveCSS("opacity", "1");
      expect(await action.boundingBox()).toEqual(bounds);
      expect(await model.boundingBox()).toEqual(modelBounds);

      await input.fill("");
      await input.fill("A newer draft");
      await action.click();
      await expect(action).toHaveAccessibleName("Stop response");
      const stop = action.locator('[data-action-icon="stop"]');
      const ring = stop.locator(".loading-ring-arc");
      await expect.poll(() => ring.evaluate((node) => node.getAnimations().length)).toBe(1);
      const phase = await ring.evaluate((node) => Number(node.getAnimations()[0].currentTime));
      await expect.poll(() => ring.evaluate((node) => Number(node.getAnimations()[0].currentTime))).toBeGreaterThan(phase);
      await action.click();
      await expect(page.getByLabel("Execution status")).toHaveText("Stop requested");
      await expect(action).toHaveAccessibleName("Stop response");
      await expect.poll(() => stop.evaluate((node) => getComputedStyle(node).opacity)).toBe("1");
      expect(await action.boundingBox()).toEqual(bounds);
      await page.getByRole("button", { name: "Finish response" }).click();
      await expect(action).toHaveAccessibleName("Voice input");
      await expect.poll(() => stop.evaluate((node) => getComputedStyle(node).opacity)).toBe("0");
      expect(await ring.evaluate((node) => node.getAnimations().length)).toBe(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }
}

test("composer activity follows both themes and live reduced-motion preferences", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=composer-action");
  await page.getByRole("textbox").fill("Run a task");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  const action = page.getByRole("button", { name: "Stop response", exact: true });
  const ring = action.locator('[data-action-icon="stop"] svg:has(.loading-ring-arc)');
  const colors: string[] = [];
  for (const dark of [false, true]) {
    await page.evaluate((enabled) => document.documentElement.classList.toggle("dark", enabled), dark);
    colors.push(await ring.evaluate((node) => getComputedStyle(node).color));
  }
  expect(colors[0]).not.toBe(colors[1]);
  for (const reducedMotion of ["reduce", "no-preference"] as const) {
    await page.emulateMedia({ reducedMotion });
    await expect.poll(() => ring.evaluate((node) => node.getAnimations({ subtree: true }).length))
      .toBe(reducedMotion === "reduce" ? 0 : 1);
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await action.hover();
  await page.mouse.down();
  expect(await action.evaluate((node) => getComputedStyle(node).transform)).toBe("none");
  expect(await action.locator(".composer-action-icons").evaluate((node) => getComputedStyle(node).transform)).toBe("none");
  await page.mouse.up();
  await page.getByRole("button", { name: "Finish response" }).click();
  await page.getByRole("textbox").fill("Another draft");
  await expect(page.getByRole("button", { name: "Send message", exact: true })).toBeEnabled();
  expect(await action.count()).toBe(0);
});


test("idle voice and ready send remain distinct from the composer in both themes", async ({ page }) => {
  const measurements = [];
  for (const variant of ["hero", "thread"]) {
    for (const theme of ["light", "dark"]) {
      await page.goto(`/browser/fixture.html?case=composer-action&composerVariant=${variant}`);
      await page.locator("html").evaluate((element, dark) => element.classList.toggle("dark", dark), theme === "dark");
      const action = page.locator(".composer-primary-action");
      for (const [state, value] of [["voice", ""], ["send", "A ready message"]]) {
        await page.getByRole("textbox").fill(value);
        await expect(action).toBeEnabled();
        await expect(action).toHaveAccessibleName(state === "voice" ? "Voice input" : "Send message");
        await page.waitForTimeout(250);
        const contrast = await action.evaluate((button) => {
          const parse = (color: string) => color.match(/[\d.]+/g)!.map(Number);
          const composite = (foreground: number[], background: number[]) => {
            const alpha = foreground[3] ?? 1;
            return background.map((channel, index) => foreground[index] * alpha + channel * (1 - alpha));
          };
          const luminance = (color: number[]) => {
            const channels = color.map((value) => {
              const channel = value / 255;
              return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
            });
            return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
          };
          const ratio = (first: number[], second: number[]) => {
            const a = luminance(first), b = luminance(second);
            return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
          };
          const ancestors: Element[] = [];
          for (let node = button.parentElement; node; node = node.parentElement) ancestors.unshift(node);
          let background = [255, 255, 255];
          for (const node of ancestors) background = composite(parse(getComputedStyle(node).backgroundColor), background);
          const style = getComputedStyle(button);
          const surface = composite(parse(style.backgroundColor), background);
          const glyph = composite(parse(style.color), surface);
          return { surface: ratio(surface, background), glyph: ratio(glyph, surface) };
        });
        expect(contrast.surface, `${variant}/${theme}/${state} button boundary`).toBeGreaterThanOrEqual(3);
        expect(contrast.glyph, `${variant}/${theme}/${state} icon`).toBeGreaterThanOrEqual(4.5);
        measurements.push({ variant, theme, state, ...contrast });
      }
    }
  }
  await test.info().attach("action-contrast", { body: JSON.stringify(measurements, null, 2), contentType: "application/json" });
});


test("a compact mobile composer preserves its placeholder, focus, and sizing", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 314, height: 844 }, hasTouch: true, isMobile: true, reducedMotion: "reduce" });
  try {
    const page = await context.newPage();
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "fr"));
    await page.goto("/browser/fixture.html?case=composer-action&composerVariant=thread");
    await page.evaluate(() => document.fonts.ready);
    const input = page.locator(".thread-composer-input textarea");
    const action = page.locator(".composer-primary-action");
    await expect(input).toHaveAttribute("placeholder", "Votre message…");
    await expect.poll(() => input.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
    const placeholder = (await input.getAttribute("aria-description"))!;
    expect(placeholder).toContain("compétences");
    const before = (await action.boundingBox())!;
    const initialHeight = await input.evaluate(node => node.clientHeight);

    await input.tap();
    await expect(input).toBeFocused();
    expect(await action.boundingBox()).toEqual(before);

    await input.fill("Bonjour");
    expect(await action.boundingBox()).toEqual(before);
    await input.fill("Première ligne\nDeuxième ligne\nTroisième ligne");
    await expect.poll(() => input.evaluate(node => node.clientHeight)).toBeGreaterThan(initialHeight);
    await input.fill("");
    await expect.poll(() => input.evaluate(node => node.clientHeight)).toBe(initialHeight);
    expect(await action.boundingBox()).toEqual(before);

    await page.locator(".thread-composer-footer button").first().focus();
    await page.keyboard.press("Shift+Tab");
    await expect(input).toBeFocused();
  } finally {
    await context.close();
  }
});

for (const variant of ["hero", "thread"]) {
  test(`placeholder follows available input width in a ${variant} composer`, async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 900 });
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.goto(`/browser/fixture.html?case=composer-action&composerVariant=${variant}`);
    await page.evaluate(() => document.fonts.ready);
    const container = page.locator("main");
    const input = page.locator(".thread-composer-input textarea");
    const fullHint = "Type / for commands, @ for chats or apps, $ for skills";
    await expect(input).toHaveAttribute("placeholder", fullHint);

    await container.evaluate(node => { node.style.maxWidth = "340px"; });
    await expect(input).toHaveAttribute("placeholder", "Type a message…");
    await expect(input).toHaveAttribute("aria-description", fullHint);
    await expect.poll(() => input.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);

    await input.fill("Keep this draft");
    await container.evaluate(node => { node.style.maxWidth = "600px"; });
    await expect(input).toHaveAttribute("placeholder", fullHint);
    await container.evaluate(node => { node.style.setProperty("--text-reading-size", "28px"); });
    await expect(input).toHaveAttribute("placeholder", "Type a message…");
    await container.evaluate(node => { node.style.maxWidth = "900px"; });
    await expect(input).toHaveAttribute("placeholder", fullHint);
    await expect(input).toHaveValue("Keep this draft");

    await page.goto(`/browser/fixture.html?case=composer-action&composerVariant=${variant}&opening`);
    await page.locator("main").evaluate(node => { node.style.maxWidth = "340px"; });
    await expect(input).toHaveAttribute("placeholder", "Opening a new topic…");
  });
}
