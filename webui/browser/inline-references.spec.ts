import { EOL } from "node:os";

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

async function minimumHandleContrast(handle: Locator): Promise<number> {
  return handle.evaluate(node => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d", { willReadFrequently: true })!;
    const pixel = (color: string) => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data];
    };
    const layers: number[][] = [];
    for (let element = node.parentElement; element; element = element.parentElement) {
      layers.push(pixel(getComputedStyle(element).backgroundColor));
    }
    let background = [255, 255, 255];
    for (const [r, g, b, alpha] of layers.reverse()) {
      const opacity = alpha / 255;
      background = [r, g, b].map((channel, index) => channel * opacity + background[index] * (1 - opacity));
    }
    const luminance = (rgb: number[]) => {
      const linear = rgb.map(value => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
    };
    const style = getComputedStyle(node);
    const lightness = style.getPropertyValue("--session-handle-lightness").trim();
    const chroma = style.getPropertyValue("--session-handle-chroma").trim();
    const backgroundLuminance = luminance(background);
    return Math.min(...Array.from({ length: 360 }, (_, hue) => {
      const foreground = luminance(pixel(`oklch(${lightness} ${chroma} ${hue})`).slice(0, 3));
      return (Math.max(foreground, backgroundLuminance) + 0.05) / (Math.min(foreground, backgroundLuminance) + 0.05);
    }));
  });
}

test("keeps a long app name readable in a minimum-width pane", async ({ page }) => {
  await page.setViewportSize({ width: 200, height: 844 });
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.goto("/browser/fixture.html?case=inline-references");
  const input = page.getByRole("textbox", { name: "Message input", exact: true });
  await input.fill("@adobe");
  const option = page.getByRole("option", { name: /@adobe-express-docs Adobe Express Developer/i });
  const label = option.getByText("Adobe Express Developer", { exact: true });
  await expect(label).toBeVisible();
  expect(await label.evaluate(node => node.clientWidth)).toBeGreaterThanOrEqual(64);
  expect(await option.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await expect(option.locator("img")).toBeVisible();
  await expect(option.getByText("MCP", { exact: true })).toBeVisible();
});

for (const narrow of [false, true]) {
  for (const theme of ["light", "dark"]) {
    test(`mention choices show colored session handles and retain app icons: ${narrow ? "narrow" : "desktop"}, ${theme}`, async ({ page }, info) => {
      await page.setViewportSize(narrow ? { width: 320, height: 844 } : { width: 1440, height: 1000 });
      await page.addInitScript(theme => {
        localStorage.setItem("nanobot.locale", "en");
        localStorage.setItem("nanobot-webui.theme", theme);
      }, theme);
      await page.goto("/browser/fixture.html?case=inline-references");
      const input = page.getByRole("textbox", { name: "Message input", exact: true });
      await input.fill("@");
      const conversation = page.getByRole("option", { name: /@typography Reference target/i });
      const app = page.getByRole("option", { name: /@drawio Draw.io/i });
      const mcp = page.getByRole("option", { name: /@linear Linear/i });
      const sessionHandle = conversation.locator(":scope > span").nth(0);
      await expect(sessionHandle).toHaveText("@typography");
      await expect(conversation.locator(":scope > span").nth(1)).toHaveText("Reference target");
      await expect(conversation.locator('[data-product-icon="conversation"]')).toHaveCount(0);
      const sessionColor = await sessionHandle.evaluate(node => getComputedStyle(node).color);
      expect(await minimumHandleContrast(sessionHandle)).toBeGreaterThanOrEqual(4.5);
      for (const [option, id, name] of [[app, "@drawio", "Draw.io"], [mcp, "@linear", "Linear"]] as const) {
        await expect(option.locator(":scope > span").nth(0)).toHaveText(id);
        await expect(option.locator(":scope > span").nth(1).locator("img, svg")).toBeVisible();
        await expect(option.getByText(name, { exact: true })).toBeVisible();
      }
      const longHandle = page.getByRole("option", { name: /@mimamimamimamima/i }).getByText("@mimamimamimamima", { exact: true });
      await expect(longHandle).toBeVisible();
      expect(await longHandle.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
      const palette = page.getByRole("listbox", { name: "Mentions" });
      expect(await palette.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath("mention-order.png") });
      await input.fill("@adobe");
      const longApp = page.getByRole("option", { name: /@adobe-express-docs Adobe Express Developer/i });
      const longAppHandle = longApp.getByText("@adobe-express-docs", { exact: true });
      const longAppName = longApp.getByText("Adobe Express Developer", { exact: true });
      await expect(longAppHandle).toBeVisible();
      await expect(longAppName).toBeVisible();
      expect(await longAppHandle.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
      expect(await longAppName.evaluate(node => node.clientWidth)).toBeGreaterThanOrEqual(64);
      expect(await longApp.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath("long-mention.png") });
      await input.fill("@typography ");
      await expect(page.getByTestId("composer-session-mention-typography")).toHaveCSS("color", sessionColor);
      await input.fill("@draw");
      await input.press("Tab");
      await expect(page.getByTestId("composer-cli-mention-drawio")).toHaveText("@\u00a0Draw.io");
      await expect(page.getByTestId("composer-cli-mention-logo-drawio")).toBeVisible();
      await expectMatchingInputLayers(input);
    });

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
      await expect(externalLink).toHaveCSS("color", theme === "light" ? "rgb(3, 105, 161)" : "rgb(186, 230, 253)");

      const input = page.getByRole("textbox", { name: "Message input", exact: true });
      const overlay = page.locator(".thread-composer-input > div[aria-hidden]");
      const text = "/goal like $workflow 和 $skill-creator，检查中文 English 与换行。";
      await input.focus();
      await input.pressSequentially("/goal ");
      const composerCommand = page.getByTestId("composer-slash-command");
      await expect(composerCommand).toHaveText("/goal");
      await expect(composerCommand).toHaveCSS("color", "rgb(244, 169, 73)");
      await expect(composerCommand).toHaveCSS("font-weight", "400");
      await expectMatchingInputLayers(input);
      await input.pressSequentially(text.slice("/goal ".length));
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
      const command = page.getByTestId("message-slash-command");
      const sentSkill = page.getByTestId("message-skill-reference-workflow");
      await expect(command).toHaveText("/goal");
      await expect(command).toHaveCSS("color", await sentSkill.evaluate(node => getComputedStyle(node).color));
      await expect(command).toHaveCSS("font-weight", "400");
      await expect(command.locator("span")).toHaveText("/");
      await expect(command.locator("span")).toHaveCSS("opacity", "0.9");
      await expect(page.locator("[data-user-text-bubble]").last().locator("p")).toHaveText(text);
      await page.screenshot({ path: info.outputPath("slash-command-and-skill.png") });

      const shellCommand = '  !echo "hello! $workflow @typography"\nWrite-Output "命令输出"';
      await input.fill(shellCommand);
      const bang = page.getByTestId("composer-shell-prefix");
      await expect(bang).toHaveText("!");
      await expect(bang).toHaveCSS("color", await page.getByTestId("message-skill-reference-workflow").evaluate(node => getComputedStyle(node).color));
      await expect(bang).toHaveCSS("font-weight", "400");
      await expectMatchingInputLayers(input);
      await input.press("ControlOrMeta+a");
      await input.press("ControlOrMeta+c");
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(shellCommand);
      await input.press("ArrowRight");
      await page.screenshot({ path: info.outputPath("composer-bang.png") });
      const prefixColor = await bang.evaluate(node => getComputedStyle(node).color);
      await page.getByRole("button", { name: "Run Shell command", exact: true }).click();
      const sentPrefix = page.getByTestId("message-shell-prefix");
      await expect(sentPrefix).toHaveText("!");
      await expect(sentPrefix).toHaveCSS("color", prefixColor);
      await expect(sentPrefix).toHaveCSS("font-weight", "400");
      const sentCommand = page.locator("[data-user-text-bubble]").last().locator("p");
      expect(await sentCommand.textContent()).toBe(shellCommand.trim());
      await sentCommand.click();
      await sentCommand.evaluate(node => {
        const range = document.createRange();
        range.selectNodeContents(node);
        const selection = window.getSelection()!;
        selection.removeAllRanges();
        selection.addRange(range);
      });
      await page.keyboard.press("ControlOrMeta+c");
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(shellCommand.trim().replaceAll("\n", EOL));
      await page.evaluate(() => window.getSelection()?.removeAllRanges());
      await page.screenshot({ path: info.outputPath("sent-bang.png") });

      const output = page.getByTestId("plain-code-fallback");
      const literal = "  __pycache__\n```mermaid\nflowchart LR\n```\n![preview](local.png)\n<b>raw</b>\n";
      expect(await output.textContent()).toBe(literal);
      await expect(output.locator("img, b")).toHaveCount(0);
      await page.getByRole("button", { name: "Copy code", exact: true }).click();
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(literal.replaceAll("\n", EOL));
      expect(errors).toEqual([]);
    });
  }
}
