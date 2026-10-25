import { expect, test, type Locator } from "@playwright/test";

async function expectMatchingInputLayers(input: Locator) {
  const metrics = await input.evaluate((node: HTMLTextAreaElement) => {
    const overlay = node.previousElementSibling as HTMLElement;
    const readStyle = (element: Element) => {
      const style = getComputedStyle(element);
      return {
        fontFamily: style.fontFamily, fontSize: style.fontSize, fontWeight: style.fontWeight,
        lineHeight: style.lineHeight, letterSpacing: style.letterSpacing,
        padding: style.padding, autospace: style.getPropertyValue("text-autospace"),
      };
    };
    const glyphs = (element: Element) => {
      const origin = element.getBoundingClientRect();
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      const result: number[][] = [];
      while (walker.nextNode()) {
        const text = walker.currentNode;
        for (let index = 0; index < (text.textContent?.length ?? 0); index++) {
          const range = document.createRange();
          range.setStart(text, index);
          range.setEnd(text, index + 1);
          const rect = range.getBoundingClientRect();
          result.push([rect.x - origin.x, rect.y - origin.y, rect.width, rect.height]);
        }
      }
      return result;
    };
    const plain = overlay.cloneNode(false) as HTMLElement;
    plain.style.visibility = "hidden";
    plain.textContent = overlay.textContent;
    overlay.parentElement!.append(plain);
    plain.scrollTop = overlay.scrollTop;
    try {
      return {
        inputStyle: readStyle(node), overlayStyle: readStyle(overlay),
        overlayText: overlay.textContent, value: node.value,
        decoratedGlyphs: glyphs(overlay), plainGlyphs: glyphs(plain),
      };
    } finally {
      plain.remove();
    }
  });
  expect(metrics.overlayStyle).toEqual(metrics.inputStyle);
  expect(metrics.overlayText).toBe(metrics.value);
  expect(metrics.decoratedGlyphs.length).toBe(metrics.plainGlyphs.length);
  for (let index = 0; index < metrics.plainGlyphs.length; index++) {
    for (let dimension = 0; dimension < 4; dimension++) {
      expect(Math.abs(metrics.decoratedGlyphs[index][dimension] - metrics.plainGlyphs[index][dimension])).toBeLessThanOrEqual(0.5);
    }
  }
}

for (const narrow of [false, true]) {
  for (const theme of ["light", "dark"]) {
    test(`inline references preserve native editing: ${narrow ? "narrow" : "desktop"}, ${theme}`, async ({ page }, info) => {
      await page.setViewportSize(narrow ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
      await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
      await page.addInitScript(theme => {
        localStorage.setItem("nanobot.locale", "en");
        localStorage.setItem("nanobot-webui.theme", theme);
      }, theme);
      const errors: string[] = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.goto("/browser/fixture.html?case=inline-references");

      const sessionLink = page.getByRole("link", { name: "相关会话", exact: true });
      await sessionLink.waitFor({ state: "visible", timeout: 15_000 });
      await expect(sessionLink).toHaveAttribute("href", "#/chat/websocket%3Atypography");
      await expect(sessionLink.locator("span")).toHaveCSS("color", "rgb(244, 169, 73)");
      await sessionLink.click();
      await expect(page).toHaveURL(/#\/chat\/websocket%3Atypography$/);
      const externalLink = page.getByRole("link", { name: "外部文档", exact: true });
      await expect(externalLink).toHaveAttribute("href", "https://example.com/reference");
      await expect(externalLink).toHaveAttribute("target", "_blank");
      await expect(externalLink).toHaveCSS("color", theme === "light" ? "rgb(59, 130, 246)" : "rgb(147, 197, 253)");

      const input = page.getByRole("textbox", { name: "Message input", exact: true });
      const overlay = page.locator(".thread-composer-input > div[aria-hidden]");
      const text = "like $workflow 和 $skill-creator，检查中文 English 与换行。";
      await input.focus();
      await input.pressSequentially(text);
      const skill = page.getByTestId("composer-skill-reference-workflow");
      await expect(skill).toHaveText("$workflow");
      await expect(skill).toHaveCSS("color", "rgb(244, 169, 73)");
      await expect(skill).toHaveCSS("font-weight", "400");
      expect(await skill.getAttribute("title")).toBeNull();
      await expectMatchingInputLayers(input);

      const start = text.indexOf("workflow") + 1;
      const end = start + 4;
      await input.evaluate((node: HTMLTextAreaElement, range) => node.setSelectionRange(range.start, range.end), { start, end });
      await input.press("ControlOrMeta+c");
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(text.slice(start, end));
      await input.press("ControlOrMeta+x");
      await expect(input).toHaveValue(text.slice(0, start) + text.slice(end));
      await input.press("ControlOrMeta+z");
      await expect(input).toHaveValue(text);
      expect(await input.evaluate((node: HTMLTextAreaElement) => [node.selectionStart, node.selectionEnd])).toEqual([start, end]);

      const mixed = "粘贴 $workflow 与 @typography，继续输入。";
      await input.fill("");
      await page.evaluate(text => navigator.clipboard.writeText(text), mixed);
      await input.press("ControlOrMeta+v");
      await expect(input).toHaveValue(mixed);
      await expect(skill).toHaveText("$workflow");
      await expect(page.getByTestId("composer-session-mention-typography")).toHaveText("@typography");
      await expect(overlay).toHaveText(mixed);

      const multiline = Array.from({ length: 18 }, (_, index) => `第 ${index + 1} 行 $workflow 中文 English 光标与装饰层保持一致。`).join("\n");
      await input.fill(multiline);
      await input.press("ControlOrMeta+End");
      await expect.poll(async () => Math.abs(await input.evaluate(node => node.scrollTop) - await overlay.evaluate(node => node.scrollTop))).toBeLessThanOrEqual(1);
      await expectMatchingInputLayers(input);
      await input.fill(text);
      await input.press("End");
      await page.screenshot({ path: info.outputPath("composer-skills.png") });
      await page.getByRole("button", { name: "Send message", exact: true }).click();
      await expect(page.getByTestId("message-skill-reference-workflow")).toHaveText("$workflow");
      await expect(page.getByTestId("message-skill-reference-workflow")).toHaveCSS("color", "rgb(244, 169, 73)");
      await expect(page.locator("[data-user-text-bubble]").last().locator("p")).toHaveText(text);
      expect(errors).toEqual([]);
    });
  }
}
