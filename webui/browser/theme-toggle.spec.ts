import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test.describe(`theme toggle at ${width}px`, () => {
    test.use({ viewport: { width, height: 844 } });

    test("morphs in place, ignores rapid reversals, and stays keyboard accessible", async ({ page }) => {
      await page.addInitScript(() => {
        localStorage.setItem("nanobot.locale", "en");
        if (!localStorage.getItem("nanobot-webui.theme")) localStorage.setItem("nanobot-webui.theme", "light");
      });
      await page.goto("/browser/fixture.html?case=theme-toggle");
      const toggle = page.getByRole("button", { name: "Toggle theme from header", exact: true });
      const icon = toggle.locator("svg");
      await expect(icon).toHaveAttribute("data-theme", "light");
      expect(await icon.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
      const initialBox = await toggle.boundingBox();

      const intermediate = await icon.evaluate(async node => {
        const changed = new Promise<void>(resolve => {
          const observer = new MutationObserver(() => {
            if (node.getAttribute("data-theme") !== "dark") return;
            observer.disconnect();
            resolve();
          });
          observer.observe(node, { attributes: true, attributeFilter: ["data-theme"] });
        });
        node.closest<HTMLButtonElement>("button")!.click();
        await changed;
        // Sample in the commit microtask, before a protocol round-trip can outlive the morph.
        const transitions = node.getAnimations({ subtree: true });
        for (const transition of transitions) {
          transition.pause();
          transition.currentTime = 100;
        }
        const core = getComputedStyle(node.querySelector(":scope > circle")!);
        const rays = getComputedStyle(node.querySelector(".theme-toggle-rays")!);
        const result = { radius: parseFloat(core.r), opacity: parseFloat(rays.opacity), count: transitions.length };
        for (const transition of transitions) transition.play();
        return result;
      });
      await expect(page.locator("html")).toHaveClass(/dark/);
      expect(intermediate.count).toBeGreaterThan(0);
      expect(intermediate.radius).toBeGreaterThan(5);
      expect(intermediate.radius).toBeLessThan(8);
      expect(intermediate.opacity).toBeGreaterThan(0);
      expect(intermediate.opacity).toBeLessThan(1);
      expect(await toggle.boundingBox()).toEqual(initialBox);

      const toggleBox = (await toggle.boundingBox())!;
      await page.mouse.click(toggleBox.x + toggleBox.width / 2, toggleBox.y + toggleBox.height / 2);
      await expect(icon).toHaveAttribute("data-theme", "dark");
      const input = page.getByRole("textbox");
      await input.fill("Typing stays available during the theme change");
      await expect(input).toHaveValue("Typing stays available during the theme change");
      await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
      await expect(icon).toHaveAttribute("data-theme", "dark");
      await toggle.focus();
      await page.keyboard.press("Space");
      await expect(icon).toHaveAttribute("data-theme", "light");
      await expect(page.locator("html")).not.toHaveClass(/dark/);
      await expect(toggle).toBeFocused();
      await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
      expect(await toggle.boundingBox()).toEqual(initialBox);
      await page.reload();
      await expect(icon).toHaveAttribute("data-theme", "light");
      expect(await icon.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
    });
  });
}

test("reduced motion keeps the canvas fade but switches the icon directly", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    localStorage.setItem("nanobot-webui.theme", "dark");
  });
  await page.goto("/browser/fixture.html?case=theme-toggle");
  const toggle = page.getByRole("button", { name: "Toggle theme from header", exact: true });
  const icon = toggle.locator("svg");
  const core = icon.locator(":scope > circle");
  await expect(core).toHaveCSS("r", "5px");
  await toggle.click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await expect(core).toHaveCSS("r", "8px");
  expect(await icon.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
  const middle = await page.locator(".workbench-pane").evaluate(async node => {
    await new Promise(requestAnimationFrame);
    const transitions = node.getAnimations();
    for (const transition of transitions) {
      transition.pause();
      transition.currentTime = 140;
    }
    const color = getComputedStyle(node).backgroundColor;
    for (const transition of transitions) transition.play();
    return color;
  });
  const red = Number(middle.match(/[\d.]+/)![0]);
  expect(red).toBeGreaterThan(48);
  expect(red).toBeLessThan(255);
  await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
  await toggle.click();
  await expect(core).toHaveCSS("r", "5px");
  expect(await icon.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
});

for (const width of [1440, 390]) {
  for (const initial of ["light", "dark"] as const) {
    test(`reduced motion fades existing chat surfaces together from ${initial} at ${width}px`, async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.setViewportSize({ width, height: 844 });
      await page.addInitScript((theme) => {
        localStorage.setItem("nanobot.locale", "en");
        localStorage.setItem("nanobot-webui.theme", theme);
      }, initial);
      await page.goto("/browser/fixture.html?case=theme-toggle&chat");
      const input = page.getByRole("textbox");
      await input.fill("Keep this draft while changing theme");
      const inputBox = await input.boundingBox();
      await expect(page.locator("[data-user-text-bubble]").first()).toBeInViewport();
      const selectors = [
        ".thread-workspace", ".workbench-pane", ".thread-composer-surface",
        "[data-testid='thread-header'] > div:last-child", "[data-user-text-bubble] p",
        "blockquote", "[data-session-message] > div:last-child",
      ];
      const readPaint = () => page.evaluate((targets) => targets.map(selector =>
        getComputedStyle(document.querySelector(selector)!).backgroundColor), selectors);
      const before = await readPaint();
      await page.getByRole("button", { name: "Toggle theme from header", exact: true }).click();
      const middle = await page.evaluate(async (targets) => {
        await new Promise(requestAnimationFrame);
        const transitions = document.getAnimations().filter(animation => animation instanceof CSSTransition);
        for (const transition of transitions) {
          transition.pause();
          transition.currentTime = 140;
        }
        const style = (selector: string) => getComputedStyle(document.querySelector(selector)!);
        const result = {
          paint: targets.map(selector => style(selector).backgroundColor),
          footer: style(".workbench-composer-footer").backgroundColor,
          sidebarFooter: style("nav > div:last-child").backgroundColor,
          gradient: style(".thread-history-status").getPropertyValue("--thread-history-background"),
          highlight: style("[data-testid='chats-selection-highlight']").transitionProperty,
          rowAction: style(".sidebar-action-trigger").transitionProperty,
        };
        for (const transition of transitions) transition.finish();
        return result;
      }, selectors);
      await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
      const after = await readPaint();
      for (const [index, selector] of selectors.entries()) {
        expect(middle.paint[index], `${selector} must not snap to the target palette`).not.toBe(after[index]);
        expect(middle.paint[index], `${selector} must leave the old palette`).not.toBe(before[index]);
      }
      // These in-flow wrappers now reveal their painted parent instead of adding a second canvas.
      expect(middle.footer).toBe("rgba(0, 0, 0, 0)");
      expect(middle.sidebarFooter).toBe("rgba(0, 0, 0, 0)");
      expect(middle.gradient).toBe(middle.paint[0]);
      expect(middle.highlight).toContain("background-color");
      expect(middle.rowAction).toBe("opacity");
      await expect(input).toHaveValue("Keep this draft while changing theme");
      expect(await input.boundingBox()).toEqual(inputBox);
    });
  }
}

for (const width of [1440, 390]) {
  for (const initial of ["light", "dark"] as const) {
    test(`crossfades the whole ${initial === "light" ? "dark" : "light"} palette without a blank stage at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.addInitScript((theme) => {
        localStorage.setItem("nanobot.locale", "en");
        if (!localStorage.getItem("nanobot-webui.theme")) localStorage.setItem("nanobot-webui.theme", theme);
      }, initial);
      await page.goto("/browser/fixture.html?case=theme-toggle&chat");
      const toggle = page.getByRole("button", { name: "Toggle theme from header", exact: true });
      const input = page.getByRole("textbox");
      await input.fill("Crossfade keeps the draft and layout");
      const box = await input.boundingBox();
      await expect(page.locator("[data-user-text-bubble]").first()).toBeInViewport();
      await toggle.focus();
      await page.keyboard.press("Space");
      await expect.poll(() => page.evaluate(() => document.getAnimations().filter(animation => animation instanceof CSSAnimation
        && animation.animationName.startsWith("theme-crossfade-")).length)).toBe(2);
      const middle = await page.evaluate(() => {
        const root = document.documentElement;
        const fades = document.getAnimations().filter(animation => animation instanceof CSSAnimation
          && animation.animationName.startsWith("theme-crossfade-"));
        for (const fade of fades) {
          fade.pause();
          fade.currentTime = 100;
        }
        const oldTheme = getComputedStyle(root, "::view-transition-old(root)");
        const newTheme = getComputedStyle(root, "::view-transition-new(root)");
        return {
          durations: fades.map(fade => fade.effect!.getTiming().duration),
          canvas: getComputedStyle(document.querySelector(".workbench-pane")!).backgroundColor,
          bubble: getComputedStyle(document.querySelector("[data-user-text-bubble] p")!).backgroundColor,
          oldOpacity: Number(oldTheme.opacity), newOpacity: Number(newTheme.opacity),
          oldBlend: oldTheme.mixBlendMode, newBlend: newTheme.mixBlendMode,
          isolation: getComputedStyle(root, "::view-transition-image-pair(root)").isolation,
          mask: newTheme.maskImage, clip: newTheme.clipPath,
        };
      });
      expect(middle.durations).toEqual([200, 200]);
      expect(middle.canvas).toBe(initial === "light" ? "rgb(48, 48, 48)" : "rgb(255, 255, 255)");
      expect(middle.bubble).toBe(initial === "light" ? "rgba(56, 56, 56, 0.7)" : "rgba(245, 245, 245, 0.7)");
      expect(middle.oldOpacity).toBeCloseTo(0.5);
      expect(middle.newOpacity).toBeCloseTo(0.5);
      expect(middle.oldOpacity + middle.newOpacity).toBeCloseTo(1);
      expect(middle.oldBlend).toBe("plus-lighter");
      expect(middle.newBlend).toBe("plus-lighter");
      expect(middle.isolation).toBe("isolate");
      expect(middle.mask).toBe("none");
      expect(middle.clip).toBe("none");
      await expect(toggle).toBeFocused();
      expect(await input.boundingBox()).toEqual(box);
      await page.screenshot({ path: test.info().outputPath(`crossfade-${width}-${initial}-mid.png`), animations: "allow" });
      // Keyboard input still reaches the live DOM while the native snapshots are paused.
      await page.keyboard.press("Space");
      for (let step = 0; step < 20 && !await input.evaluate(node => node === document.activeElement); step++) {
        await page.keyboard.press("Tab");
      }
      await expect(input).toBeFocused();
      await page.keyboard.type(" — typed during the crossfade");
      await expect(input).toHaveValue("Crossfade keeps the draft and layout — typed during the crossfade");
      await page.evaluate(() => document.getAnimations().filter(animation => animation instanceof CSSAnimation
        && animation.animationName.startsWith("theme-crossfade-")).forEach(animation => animation.finish()));
      await expect.poll(() => page.locator("html").getAttribute("data-theme-snapshot")).toBeNull();
      await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
      await expect(toggle.locator("svg")).toHaveAttribute("data-theme", initial === "light" ? "dark" : "light");
      await page.reload();
      await expect(toggle.locator("svg")).toHaveAttribute("data-theme", initial === "light" ? "dark" : "light");
      expect(await page.evaluate(() => document.getAnimations().some(animation => animation instanceof CSSAnimation
        && animation.animationName.startsWith("theme-crossfade-")))).toBe(false);
    });
  }
}

test("browsers without View Transitions keep a working palette fade", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("nanobot-webui.theme", "light");
    Object.defineProperty(document, "startViewTransition", { value: undefined });
  });
  await page.goto("/browser/fixture.html?case=theme-toggle&chat");
  await page.getByRole("button", { name: "Toggle theme from header", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  const midpoint = await page.locator(".workbench-pane").evaluate(async node => {
    await new Promise(requestAnimationFrame);
    const paint = node.getAnimations().filter(animation => animation instanceof CSSTransition);
    paint.forEach(animation => { animation.pause(); animation.currentTime = 140; });
    const color = getComputedStyle(node).backgroundColor;
    paint.forEach(animation => animation.finish());
    return color;
  });
  expect(midpoint).not.toBe("rgb(48, 48, 48)");
  expect(midpoint).not.toBe("rgb(255, 255, 255)");
  await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
  await expect(page.getByRole("textbox")).toBeEditable();
});

test("a browser-skipped transition still applies the theme and releases the toggle", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("nanobot-webui.theme", "light");
    const start = document.startViewTransition.bind(document);
    document.startViewTransition = (...args) => {
      const transition = start(...args);
      transition.skipTransition();
      return transition;
    };
  });
  await page.goto("/browser/fixture.html?case=theme-toggle&chat");
  const toggle = page.getByRole("button", { name: "Toggle theme from header", exact: true });
  await toggle.click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect.poll(() => page.locator("html").getAttribute("data-theme-snapshot")).toBeNull();
  await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
  await toggle.click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("selection highlights keep geometry easing and only fade paint with reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 844 });
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    localStorage.setItem("nanobot-webui.theme", "light");
  });
  await page.goto("/browser/fixture.html?case=theme-toggle&chat");
  const highlight = page.getByTestId("chats-selection-highlight");
  await expect(highlight).toHaveCSS("transition-property", "transform, width, height, background-color");
  await expect(highlight).toHaveCSS("transition-duration", "0.3s, 0.3s, 0.3s, 0s");
  await expect(highlight).toHaveCSS("transition-timing-function", "ease-out, ease-out, ease-out, ease");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(highlight).toHaveCSS("transition-property", "none");
  const paint = await highlight.evaluate(node => {
    document.querySelector<HTMLButtonElement>("button[aria-label='Toggle theme from header']")!.click();
    const style = getComputedStyle(node);
    return { property: style.transitionProperty, duration: style.transitionDuration };
  });
  expect(paint).toEqual({
    property: "background-color, border-color, box-shadow",
    duration: "0.28s, 0.28s, 0.28s",
  });
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect.poll(() => page.locator("html").getAttribute("data-theme-transition")).toBeNull();
  await expect(highlight).toHaveCSS("transition-property", "none");
});
