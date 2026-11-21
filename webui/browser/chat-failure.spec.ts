import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

for (const locale of ["en", "zh-CN", "zh-TW", "fr", "ja", "ko", "es", "pt-BR", "vi", "id"]) {
  for (const gateway of ["bwrap", "seatbelt"]) {
    test(`sandbox path action fits a narrow view: ${gateway}, ${locale}`, async ({ page }) => {
      const copy = JSON.parse(readFileSync(new URL(`../src/i18n/locales/${locale}/common.json`, import.meta.url), "utf8")).settings.sandbox;
      const executable = gateway === "bwrap" ? "bwrap" : "sandbox-exec";
      await page.setViewportSize({ width: 390, height: 1000 });
      await page.addInitScript((locale) => localStorage.setItem("nanobot.locale", locale), locale);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto(`/browser/fixture.html?case=chat-failure&notice=sandbox&gateway=${gateway}`);
      const notice = page.locator(".thread-composer-notice");
      await expect(notice).toContainText(gateway === "bwrap" ? "Bubblewrap (bwrap)" : "macOS Seatbelt (sandbox-exec)");
      await expect(notice).not.toContainText(/{{|settings\.sandbox/);
      const action = notice.getByRole("button", { name: copy.notice.configurePath.replace("{{launcher}}", executable), exact: true });
      await expect(action).toBeInViewport({ ratio: 1 });
      const bounds = (await notice.boundingBox())!;
      const button = (await action.boundingBox())!;
      expect(button.x).toBeGreaterThanOrEqual(bounds.x);
      expect(button.x + button.width).toBeLessThanOrEqual(bounds.x + bounds.width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
      await action.click();
      await expect(page.getByLabel("Fixture action")).toHaveText("settings");
    });
  }
}

test("sandbox guidance stays generic without gateway backend details", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=chat-failure&notice=sandbox&gateway=unknown");
  const notice = page.locator(".thread-composer-notice");
  await expect(notice).toContainText("sandbox launcher");
  await expect(notice).not.toContainText(/bwrap|sandbox-exec/);
  await notice.getByRole("button", { name: "Open sandbox settings" }).click();
  await expect(page.getByLabel("Fixture action")).toHaveText("settings");
});

for (const width of [1440, 390]) {
  for (const variant of ["thread", "hero"]) {
    for (const notice of ["recovery", "stream", "fallback", "sandbox"]) {
      test(`${notice} aligns with ${variant} composer at ${width}px`, async ({ page }, info) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.emulateMedia({ reducedMotion: "reduce" });
        await page.addInitScript(({ dark, locale }) => {
          localStorage.setItem("nanobot.locale", locale);
          localStorage.setItem("nanobot-webui.settings-preferences", JSON.stringify({ schemaVersion: 1, readingTextSize: "large" }));
          document.addEventListener("DOMContentLoaded", () => {
            document.documentElement.classList.toggle("dark", dark);
          });
        }, { dark: variant === "hero", locale: width === 390 ? "zh-CN" : "en" });
        await page.goto(`/browser/fixture.html?case=chat-failure&notice=${notice}&variant=${variant}`);
        const alert = page.locator(".thread-composer-notice");
        const composer = page.locator(".thread-composer-surface");
        await expect(alert).toBeVisible();
        await expect(composer).toBeVisible();
        const noticeBox = (await alert.boundingBox())!;
        const composerBox = (await composer.boundingBox())!;
        expect(Math.abs(noticeBox.x - composerBox.x)).toBeLessThan(1);
        expect(Math.abs(noticeBox.width - composerBox.width)).toBeLessThan(1);
        for (const button of await alert.getByRole("button").all()) {
          await expect(button).toBeInViewport({ ratio: 1 });
          const box = (await button.boundingBox())!;
          expect(box.x).toBeGreaterThanOrEqual(noticeBox.x);
          expect(box.x + box.width).toBeLessThanOrEqual(noticeBox.x + noticeBox.width);
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
        if (notice === "sandbox") {
          await expect(alert).toHaveAttribute("role", "status");
          await expect(alert).toHaveAttribute("aria-live", "polite");
          const input = page.getByRole("textbox");
          await input.fill("Keep this unsent draft / 保留草稿");
          await expect(input).toBeFocused();
          await alert.getByRole("button").first().click();
          await expect(page.getByLabel("Fixture action")).toHaveText("settings");
          await expect(input).toHaveValue("Keep this unsent draft / 保留草稿");
          await page.screenshot({ path: info.outputPath("sandbox-notice.png") });
        }
        if (notice === "recovery") {
          await expect(alert).toContainText(width === 390 ? "模型提供商验证失败" : "Model provider authorization failed");
          await alert.getByRole("button").first().click();
          await expect(page.getByLabel("Fixture action")).toHaveText("settings");
          await alert.getByRole("button").last().click();
          await expect(alert).toBeHidden();
          await expect(page.getByLabel("Fixture action")).toHaveText("continued");
        } else {
          await alert.getByRole("button").last().click();
          await expect(alert).toBeHidden();
          await expect(page.getByLabel("Fixture action")).toHaveText("dismissed");
        }
      });
    }
  }
}

for (const width of [1440, 390]) {
  for (const size of ["small", "standard", "large"] as const) {
    test(`image and quote retain the responsive message actions: ${size}, ${width}px`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(({ size, locale }) => {
        localStorage.setItem("nanobot.locale", locale);
        localStorage.setItem("nanobot-webui.settings-preferences", JSON.stringify({ schemaVersion: 1, readingTextSize: size }));
      }, { size, locale: width === 390 ? "zh-CN" : "en" });
      await page.goto("/browser/fixture.html?case=chat-failure");
      const image = page.getByAltText("Failure screenshot");
      await expect(image).toBeVisible();
      await expect(page.getByText("Earlier context / 之前的上下文")).toBeVisible();
      const bubble = page.locator("[data-user-text-bubble]");
      const text = bubble.locator("p");
      const trigger = page.locator("[data-message-block-menu-trigger]");
      const fontSize = { small: 15, standard: 16, large: 18 }[size];
      await expect(text).toHaveCSS("font-size", `${fontSize}px`);
      await bubble.hover();
      await expect(trigger).toBeVisible();
      const bubbleBox = (await bubble.boundingBox())!;
      const triggerBox = (await trigger.boundingBox())!;
      const imageBox = (await image.boundingBox())!;
      expect(imageBox.y + imageBox.height).toBeLessThan(bubbleBox.y);
      if (width === 390) {
        await expect(page.locator("[data-message-mobile-actions]")).toBeVisible();
        expect(triggerBox.y).toBeGreaterThanOrEqual(bubbleBox.y + bubbleBox.height);
        expect(triggerBox.height).toBeGreaterThanOrEqual(44);
        await expect(trigger).toBeInViewport({ ratio: 1 });
      } else {
        const firstLineCenter = await text.evaluate(node => {
          const style = getComputedStyle(node);
          return node.getBoundingClientRect().y + parseFloat(style.paddingTop) + parseFloat(style.lineHeight) / 2;
        });
        expect(Math.abs(triggerBox.y + triggerBox.height / 2 - firstLineCenter)).toBeLessThan(1);
      }
      await trigger.click();
      await expect(page.locator("[data-message-block-menu]")).toBeVisible();
      if (width === 390) {
        await expect(page.locator("[data-message-mobile-sheet]")).toBeInViewport({ ratio: 1 });
      }
      await page.screenshot({ path: info.outputPath("message-menu.png") });
    });
  }
}
