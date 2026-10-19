import { expect, test, type Locator } from "@playwright/test";

async function loadedImage(image: Locator) {
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
}

test("same-source completion loads a real Pele image only after generation, with source/copy/viewer controls", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/browser/fixture.html?case=diagrams&stream");
  await expect(page.getByText("开始：接收用户请求", { exact: false })).toBeVisible();
  expect(requests.some((url) => /pele\.worker|node_modules\/pele\//.test(url))).toBe(false);
  await page.getByRole("button", { name: "Complete message" }).click();
  const block = page.getByTestId("mermaid-block");
  const image = block.locator("img");
  await loadedImage(image);
  expect(requests.some((url) => url.includes("pele.worker"))).toBe(true);
  const content = await image.evaluate(async (element: HTMLImageElement) => fetch(element.src).then((response) => response.text()));
  expect(content).toContain("<path");
  expect(content).toContain("接收用户请求");
  const copyButton = block.getByRole("button", { name: "Copy source" });
  await copyButton.hover();
  await expect(page.getByRole("tooltip", { name: "Copy source", exact: true })).toBeVisible();
  await copyButton.click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain("flowchart LR");
  await block.getByRole("button", { name: "Source", exact: true }).click();
  await expect(block.locator("pre")).toContainText("检查权限");
  await block.getByRole("button", { name: "Diagram", exact: true }).click();
  await loadedImage(image);
  const opener = block.getByRole("button", { name: "Enlarge diagram" });
  await opener.hover();
  await expect(page.getByRole("tooltip", { name: "Enlarge diagram", exact: true })).toBeVisible();
  await page.mouse.move(0, 0, { steps: 10 });
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await opener.focus();
  await expect(page.getByRole("tooltip", { name: "Enlarge diagram", exact: true })).toBeVisible();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await expect(dialog.getByRole("button", { name: "Fit image" })).toHaveText("150%");
  const viewport = dialog.getByTestId("image-viewport");
  await viewport.focus();
  await page.keyboard.press("0");
  await expect(dialog.getByRole("button", { name: "Fit image" })).toHaveText("100%");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(opener).toBeFocused();
  await page.screenshot({ path: test.info().outputPath("flowchart-light.png"), fullPage: true });
});

test("flowchart, sequence and state images remain readable across theme and narrow-width changes", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1400 });
  await page.goto("/browser/fixture.html?case=diagrams&multiple");
  const blocks = page.getByTestId("mermaid-block");
  const images = blocks.locator("img");
  await expect(images).toHaveCount(3);
  for (const image of await images.all()) await loadedImage(image);
  const before = await images.evaluateAll((elements) => elements.map((element) => (element as HTMLImageElement).src));
  await page.getByRole("button", { name: "Toggle theme" }).click();
  await expect.poll(() => images.evaluateAll((elements) => elements.map((element) => (element as HTMLImageElement).src))).not.toEqual(before);
  await page.screenshot({ path: test.info().outputPath("multiple-dark-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  for (const block of await blocks.all()) { await block.scrollIntoViewIfNeeded(); await loadedImage(block.locator("img")); }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("multiple-dark-mobile.png"), fullPage: true });
});

test("twelve visible small diagrams render together and recolor without exhausting the shared budget", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 2300 });
  await page.goto("/browser/fixture.html?case=diagrams&many");
  const blocks = page.getByTestId("mermaid-block");
  const images = blocks.locator("img");
  await expect(blocks).toHaveCount(12);
  await expect(images).toHaveCount(12);
  for (const image of await images.all()) await loadedImage(image);
  await expect(blocks.last()).toBeInViewport();
  const before = await images.evaluateAll((elements) => elements.map((element) => (element as HTMLImageElement).src));
  await page.getByRole("button", { name: "Toggle theme" }).click();
  await expect.poll(() => images.evaluateAll((elements, previous) => elements.length === previous.length
    && elements.every((element, index) => {
      const image = element as HTMLImageElement;
      return image.src !== previous[index] && image.complete && image.naturalWidth > 0;
    }), before)).toBe(true);
  await expect(blocks.getByRole("status")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("twelve-diagrams-dark.png"), fullPage: true });
  await blocks.first().getByRole("button", { name: "Source", exact: true }).click();
  await expect(images).toHaveCount(11);
  await blocks.first().getByRole("button", { name: "Diagram", exact: true }).click();
  await expect(images).toHaveCount(12);
  await loadedImage(blocks.first().locator("img"));
});

test("syntax and source limits stay local; replacing source and switching conversations discards old images", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=diagrams&type=invalid&edit");
  const block = page.getByTestId("mermaid-block");
  await expect(block.getByRole("status")).toContainText("syntax");
  await expect(block.locator("pre")).toContainText("A[Unclosed");
  await page.getByRole("textbox", { name: "Diagram source" }).fill(`flowchart LR\n${" ".repeat(50_001)}`);
  await expect(block.getByRole("status")).toContainText("limit");
  await page.getByRole("textbox", { name: "Diagram source" }).fill("flowchart LR\nA[First] --> B[Result]");
  await loadedImage(block.locator("img"));
  await block.getByRole("button", { name: "Enlarge diagram" }).click();
  await page.getByRole("dialog").press("Escape");
  await page.getByRole("button", { name: "Switch conversation" }).click();
  await loadedImage(block.locator("img"));
  const svg = await block.locator("img").evaluate(async (element: HTMLImageElement) => fetch(element.src).then((response) => response.text()));
  expect(svg).toContain("处理中");
  expect(svg).not.toContain("First");
});

test("author directives, links, HTML and external images cannot execute or fetch resources", async ({ page }) => {
  const external: string[] = [];
  const dialogs: string[] = [];
  page.on("request", (request) => { if (/^https?:/.test(request.url()) && !request.url().startsWith("http://127.0.0.1:")) external.push(request.url()); });
  page.on("dialog", (dialog) => { dialogs.push(dialog.message()); void dialog.dismiss(); });
  await page.goto("/browser/fixture.html?case=diagrams&edit");
  const source = [
    '%%{init: {"securityLevel":"loose","themeVariables":{"fontFamily":"evil"}}}%%',
    'flowchart LR',
    'A["<img src=https://example.invalid/spy onerror=alert(1)>"] --> B["<script>alert(2)</script>"]',
    'click A "https://example.invalid/click"',
  ].join("\n");
  await page.getByRole("textbox", { name: "Diagram source" }).fill(source);
  const block = page.getByTestId("mermaid-block");
  await expect.poll(() => block.evaluate((element) => {
    const image = element.querySelector("img");
    if (image) return image.complete && image.naturalWidth > 0;
    const status = element.querySelector('[role="status"]');
    return !!status && !status.textContent?.includes("Preparing");
  })).toBe(true);
  expect(external).toEqual([]);
  expect(dialogs).toEqual([]);
  expect(page.url()).toContain("case=diagrams");
  if (await block.locator("img").count()) {
    const svg = await block.locator("img").evaluate(async (element: HTMLImageElement) => fetch(element.src).then((response) => response.text()));
    expect(svg).not.toMatch(/<(?:script|image|foreignObject|a)\b/i);
  }
});

test("a real blocked Worker hits its deadline while sibling diagrams finish", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1400 });
  let held = false;
  await page.route("**/pele.worker.ts?*", async (route) => {
    if (held) { await route.continue(); return; }
    held = true;
    await route.fulfill({ contentType: "application/javascript", body: 'self.onmessage = () => { postMessage({kind:"started"}); while (true) {} };' });
  });
  await page.goto("/browser/fixture.html?case=diagrams&multiple");
  const blocks = page.getByTestId("mermaid-block");
  await expect(page.getByText("The diagram took too long", { exact: false })).toBeVisible();
  await expect(blocks.locator("img")).toHaveCount(2);
  for (const image of await blocks.locator("img").all()) await loadedImage(image);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(blocks.locator("img")).toHaveCount(3);
  for (const image of await blocks.locator("img").all()) await loadedImage(image);
});


test("an enlarged diagram keeps its camera through resize and recoloring", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=diagrams");
  const block = page.getByTestId("mermaid-block");
  await loadedImage(block.locator("img"));
  await block.getByRole("button", { name: "Enlarge diagram" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  const fit = dialog.getByRole("button", { name: "Fit image" });
  await expect(fit).toHaveText("150%");
  const before = await dialog.locator("img").getAttribute("src");
  await page.setViewportSize({ width: 720, height: 850 });
  await expect(dialog).toBeVisible();
  await expect(fit).toHaveText("150%");
  await expect(dialog.locator("img")).toHaveAttribute("src", before!);
  // Change the trusted document palette without closing the reader.
  await page.evaluate(() => document.documentElement.classList.toggle("dark"));
  await expect(dialog.locator("img")).not.toHaveAttribute("src", before!);
  await expect(fit).toHaveText("150%");
  await dialog.press("Escape");
  await expect(dialog).not.toBeVisible();
  await loadedImage(block.locator("img"));
});

test("published Pele renders Chinese subgraph, wrapping, emoji and measured emphasis", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=diagrams&edit");
  const source = 'flowchart TD\nsubgraph 审核流程[中文子图：权限审核与结果交付]\nA["接收用户请求并检查工作区权限，保留中文长标签与 emoji ✅"] --> B["生成结果，并返回说明"]\nend\nclassDef measured font-size:18px,font-weight:bold,font-style:italic\nclass B measured';
  await page.getByRole("textbox", { name: "Diagram source" }).fill(source);
  const image = page.getByTestId("mermaid-block").locator("img");
  await loadedImage(image);
  const svg = await image.evaluate(async (element: HTMLImageElement) => fetch(element.src).then((response) => response.text()));
  expect(svg).toContain("中文子图");
  expect(svg).toContain("emoji ✅");
  expect(svg).toContain('font-weight="var(--_w)"');
  await page.screenshot({ path: test.info().outputPath("chinese-subgraph.png"), fullPage: true });
});
