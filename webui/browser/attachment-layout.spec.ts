import { readFile } from "node:fs/promises";
import { expect, test, type Locator, type Page } from "@playwright/test";

const archiveBytes = Buffer.from("504b0506000000000000000000000000000000000000", "hex");

async function openAttachments(page: Page, width = 1024, theme = "light", locale = "en") {
  await page.setViewportSize({ width, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: theme === "dark" ? "dark" : "light" });
  await page.addInitScript((language) => localStorage.setItem("nanobot.locale", language), locale);
  await page.goto("/browser/fixture.html?case=attachments");
  await expect(page.getByRole("region", { name: "Assistant mixed attachments" }).locator("img")).toHaveCount(3);
  // The root element does not necessarily exist during addInitScript.
  await page.evaluate((dark) => document.documentElement.classList.toggle("dark", dark), theme === "dark");
  expect(await page.locator("html").evaluate((element) => element.classList.contains("dark"))).toBe(theme === "dark");
  const brightness = await page.locator("body").evaluate((element) => {
    const channels = getComputedStyle(element).backgroundColor.match(/[\d.]+/g)!.slice(0, 3).map(Number);
    return channels.reduce((sum, channel) => sum + channel, 0) / 3;
  });
  if (theme === "dark") expect(brightness, "dark theme must render a dark background").toBeLessThan(100);
  else expect(brightness, "light theme must render a light background").toBeGreaterThan(200);
}

async function bounds(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

async function expectFileDetails(page: Page, card: Locator, filename: string, width: number, description?: string) {
  const info = card.getByRole("button", { name: filename, exact: true });
  await info.hover();
  await expect(page.getByRole("tooltip")).toContainText(filename);
  await info.click();
  const details = page.getByRole("dialog", { name: filename, exact: true });
  const name = details.getByText(filename, { exact: true });
  await expect(name).toBeVisible();
  if (description) await expect(details.getByText(description, { exact: true })).toBeVisible();
  const box = await bounds(details);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(width);
  expect(await name.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await details.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(details).toHaveCount(0);
  await expect(info).toBeFocused();
  await page.mouse.move(0, 0);
}

for (const width of [1024, 360]) {
  for (const theme of ["light", "dark"]) {
    test(`mixed attachments stay compact, aligned and readable at ${width}px in ${theme}`, async ({ page }, testInfo) => {
      // The two widths also cover both localized download names, without a second matrix.
      const chinese = width === 360;
      await page.route("**/fixture/retry.webm", (route) => route.fulfill({ status: 503, body: "Temporarily unavailable" }));
      await openAttachments(page, width, theme, chinese ? "zh-CN" : "en");
      await expect(page.getByRole("button", { name: chinese ? "重试" : "Retry", exact: true })).toBeVisible();
      await expect.poll(() => page.locator("img").evaluateAll((images) => images.every((image) => image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0))).toBe(true);
      const video = page.getByRole("region", { name: "Playable video", exact: true }).locator("video");
      await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(1);
      await page.screenshot({ path: testInfo.outputPath("layout.png"), fullPage: true });
      await testInfo.attach("attachment layout", { path: testInfo.outputPath("layout.png"), contentType: "image/png" });
      await page.getByRole("region", { name: "Assistant mixed attachments" }).screenshot({ path: testInfo.outputPath("assistant-three-images-archive.png") });
      await testInfo.attach("three images and ZIP", { path: testInfo.outputPath("assistant-three-images-archive.png"), contentType: "image/png" });

      for (const role of ["Assistant", "User"]) {
        const region = page.getByRole("region", { name: `${role} mixed attachments`, exact: true });
        const card = region.locator("[data-file-attachment]");
        await expect(card).toHaveCount(1);
        const file = await bounds(card);
        const regionBox = await bounds(region);
        const imageBoxes = await region.locator("img").evaluateAll((images) => images.map((image) => {
          const rect = image.getBoundingClientRect();
          const { naturalWidth, naturalHeight } = image as HTMLImageElement;
          return { bottom: rect.bottom, left: rect.left, right: rect.right, naturalWidth, naturalHeight };
        }));
        await testInfo.attach(`${role} geometry`, { body: JSON.stringify({ file, region: regionBox, images: imageBoxes }, null, 2), contentType: "application/json" });
        expect(file.width, `${role} file card keeps its compact width`).toBe(96);
        expect(file.height, `${role} file card must not stretch to the image row height`).toBe(96);
        for (const image of imageBoxes) expect(image).toMatchObject({ naturalWidth: 320, naturalHeight: 200 });
        expect(file.y, `${role} file belongs below all images`).toBeGreaterThanOrEqual(Math.max(...imageBoxes.map((image) => image.bottom)));
        if (role === "Assistant") {
          expect(Math.abs(file.x - regionBox.x)).toBeLessThanOrEqual(1);
          expect(Math.abs(Math.min(...imageBoxes.map((image) => image.left)) - regionBox.x)).toBeLessThanOrEqual(2);
        } else {
          const right = regionBox.x + regionBox.width;
          expect(Math.abs(file.x + file.width - right)).toBeLessThanOrEqual(1);
          expect(Math.abs(Math.max(...imageBoxes.map((image) => image.right)) - right)).toBeLessThanOrEqual(2);
        }
        await expect(card.getByRole("link")).toHaveAccessibleName(`${chinese ? "下载" : "Download"} archive.zip`);
        await expect(card.getByText("ZIP", { exact: true })).toBeVisible();
      }

      const files = page.getByRole("region", { name: "Multiple files and long names" }).locator("[data-file-attachment]");
      await expect(files).toHaveCount(3);
      const userFiles = page.getByRole("region", { name: "User multiple files", exact: true });
      const userBubble = await bounds(userFiles.locator(":scope > div"));
      const userCards = userFiles.locator("[data-file-attachment]");
      await expect(userCards).toHaveCount(3);
      const userCardBoxes = await Promise.all((await userCards.all()).map(bounds));
      await testInfo.attach("User multiple files geometry", { body: JSON.stringify({ bubble: userBubble, files: userCardBoxes }, null, 2), contentType: "application/json" });
      for (const box of userCardBoxes) {
        expect(box.x, "user file stays inside its message bubble").toBeGreaterThanOrEqual(userBubble.x);
        expect(box.x + box.width, "user file stays inside its message bubble").toBeLessThanOrEqual(userBubble.x + userBubble.width + 1);
      }
      const availableCards = page.locator("[data-file-attachment]").filter({ has: page.locator("a[download]") });
      for (const card of await availableCards.all()) {
        const box = await bounds(card);
        expect(box.width).toBe(96);
        expect(box.height).toBe(96);
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        const download = card.locator("a[download]");
        const target = await bounds(download);
        expect(target.width).toBe(44);
        expect(target.height).toBe(44);
        expect(target.x).toBeGreaterThanOrEqual(box.x);
        expect(target.x + target.width).toBeLessThanOrEqual(box.x + box.width);
        expect(target.y).toBeGreaterThanOrEqual(box.y);
        expect(target.y + target.height).toBeLessThanOrEqual(box.y + box.height);
        const icon = download.locator("svg.lucide-download");
        await expect(icon).toBeVisible();
        const iconBox = await bounds(icon);
        expect(iconBox.width).toBeGreaterThanOrEqual(12);
        expect(iconBox.x).toBeGreaterThanOrEqual(target.x);
        expect(iconBox.x + iconBox.width).toBeLessThanOrEqual(target.x + target.width);
        expect(iconBox.y).toBeGreaterThanOrEqual(target.y);
        expect(iconBox.y + iconBox.height).toBeLessThanOrEqual(target.y + target.height);
      }
      for (const [index, filename, type] of [
        [0, "release-deliverables-with-a-very-long-English-filename-for-layout-regression.zip", "ZIP"],
        [1, "项目交付资料与详细验收记录包含中英文的超长文件名称-final-review.pdf", "PDF"],
      ] as const) {
        const card = files.nth(index);
        await expect(card.getByRole("button", { name: filename, exact: true })).toHaveText(type);
        await expectFileDetails(page, card, filename, width);
      }
      await expect(files.nth(2).getByRole("link")).toHaveAccessibleName(chinese ? "下载 文件附件" : "Download File attachment");
      for (const [label, filename, status] of [
        ["Pending attachment", "pending.zip", chinese ? "发送中" : "Sending"],
        ["Unavailable attachment", "unavailable.pdf", chinese ? "附件不可用" : "Attachment unavailable"],
      ]) {
        const region = page.getByRole("region", { name: label, exact: true });
        const card = region.locator("[data-file-attachment]");
        await expect(card.getByText(status, { exact: true })).toBeVisible();
        await expectFileDetails(page, card, filename, width, status);
        // A replay placeholder has no download capability until it has a URL.
        await expect(region.getByRole("link")).toHaveCount(0);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    });
  }
}

test("image lightbox and file download remain keyboard accessible", async ({ page }, testInfo) => {
  await page.route("**/fixture/retry.webm", (route) => route.fulfill({ status: 503, body: "Temporarily unavailable" }));
  await openAttachments(page);
  const region = page.getByRole("region", { name: "Assistant mixed attachments" });
  const firstImage = region.getByRole("button", { name: "View image: Coral study.svg", exact: true });
  await page.keyboard.press("Tab");
  await expect(firstImage).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Coral study.svg" })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("dialog", { name: "Blue study.svg" })).toBeVisible();
  await page.keyboard.press("End");
  await expect(page.getByRole("dialog", { name: "Green study.svg" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("lightbox.png") });
  await testInfo.attach("image lightbox", { path: testInfo.outputPath("lightbox.png"), contentType: "image/png" });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(firstImage).toBeFocused();
  for (const name of ["Blue study.svg", "Green study.svg"]) {
    await page.keyboard.press("Tab");
    await expect(region.getByRole("button", { name: `View image: ${name}`, exact: true })).toBeFocused();
  }
  await page.keyboard.press("Tab");
  const fileInfo = region.getByRole("button", { name: "archive.zip", exact: true });
  await expect(fileInfo).toBeFocused();
  expect(await fileInfo.evaluate((element) => element.matches(":focus-visible"))).toBe(true);
  await expect(page.getByRole("tooltip")).toContainText("archive.zip");
  await page.keyboard.press("Enter");
  const details = page.getByRole("dialog", { name: "archive.zip", exact: true });
  await expect(details.getByText("archive.zip", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(details).toHaveCount(0);
  await expect(fileInfo).toBeFocused();
  await page.keyboard.press("Tab");
  const downloadLink = region.getByRole("link", { name: "Download archive.zip", exact: true });
  await expect(downloadLink).toBeFocused();
  expect(await downloadLink.evaluate((element) => element.matches(":focus-visible"))).toBe(true);
  expect(await downloadLink.evaluate((element) => getComputedStyle(element).boxShadow)).not.toBe("none");
  await page.screenshot({ path: testInfo.outputPath("keyboard-focus.png") });
  await testInfo.attach("keyboard download focus", { path: testInfo.outputPath("keyboard-focus.png"), contentType: "image/png" });
  const downloadEvent = page.waitForEvent("download");
  await page.keyboard.press("Enter");
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("archive.zip");
  expect(await download.failure()).toBeNull();
  expect((await readFile((await download.path())!)).toString("hex")).toBe(archiveBytes.toString("hex"));
  await download.saveAs(testInfo.outputPath("archive.zip"));
  await expect(page).toHaveURL(/case=attachments$/);
});

test("native video controls play the clip and retry recovers a failed media request", async ({ page }, testInfo) => {
  const clip = await readFile("src/dev/gallery/fixtures/sample.webm");
  let available = false;
  let attempts = 0;
  await page.route("**/fixture/retry.webm", (route) => {
    attempts++;
    return available
      ? route.fulfill({ contentType: "video/webm", body: clip })
      : route.fulfill({ status: 503, body: "Temporarily unavailable" });
  });
  await openAttachments(page, 360);
  const ready = page.getByRole("region", { name: "Playable video", exact: true }).getByLabel("Video attachment: sample.webm", { exact: true });
  await expect(ready).toHaveJSProperty("controls", true);
  await expect.poll(() => ready.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2);
  await ready.focus();
  await page.keyboard.press("Space");
  await expect.poll(() => ready.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(0);
  await ready.evaluate((element: HTMLVideoElement) => element.pause());

  const retryRegion = page.getByRole("region", { name: "Retry video", exact: true });
  await expect(retryRegion.getByText("Attachment unavailable", { exact: true })).toBeVisible();
  await expect(retryRegion.getByRole("link")).toHaveCount(0);
  const failedAttempts = attempts;
  expect(failedAttempts).toBeGreaterThan(0);
  available = true;
  await retryRegion.getByRole("button", { name: "Retry", exact: true }).click();
  const recovered = retryRegion.getByLabel("Video attachment: retry.webm", { exact: true });
  await expect(recovered).toHaveJSProperty("controls", true);
  await expect.poll(() => recovered.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2);
  expect(attempts).toBeGreaterThan(failedAttempts);
  await recovered.focus();
  await page.keyboard.press("Space");
  await expect.poll(() => recovered.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(0);
  await expect(retryRegion.getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);
  await recovered.evaluate((element: HTMLVideoElement) => element.pause());
  await page.screenshot({ path: testInfo.outputPath("video-recovered.png"), fullPage: true });
  await testInfo.attach("video retry recovered", { path: testInfo.outputPath("video-recovered.png"), contentType: "image/png" });
});
