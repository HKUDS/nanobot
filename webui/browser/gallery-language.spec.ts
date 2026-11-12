import { expect, test } from "@playwright/test";

const locales = [
  { code: "en", label: "English", title: "Component gallery", search: "Search components", preview: "Component preview" },
  { code: "zh-CN", label: "简体中文", title: "组件图鉴", search: "搜索组件", preview: "组件预览" },
  { code: "zh-TW", label: "繁體中文", title: "元件圖鑑", search: "搜尋元件", preview: "元件預覽" },
  { code: "fr", label: "Français", title: "Galerie de composants", search: "Rechercher des composants", preview: "Aperçu du composant" },
  { code: "ja", label: "日本語", title: "コンポーネントギャラリー", search: "コンポーネントを検索", preview: "コンポーネントのプレビュー" },
  { code: "ko", label: "한국어", title: "컴포넌트 갤러리", search: "컴포넌트 검색", preview: "컴포넌트 미리보기" },
  { code: "es", label: "Español", title: "Galería de componentes", search: "Buscar componentes", preview: "Vista previa del componente" },
  { code: "pt-BR", label: "Português (Brasil)", title: "Galeria de componentes", search: "Buscar componentes", preview: "Prévia do componente" },
  { code: "vi", label: "Tiếng Việt", title: "Thư viện thành phần", search: "Tìm thành phần", preview: "Xem trước thành phần" },
  { code: "id", label: "Bahasa Indonesia", title: "Galeri komponen", search: "Cari komponen", preview: "Pratinjau komponen" },
];

for (const locale of locales) {
  test(`gallery switches to ${locale.code} without replacing preview state`, async ({ page }) => {
    await page.setViewportSize({ width: locale.code === "en" || locale.code.startsWith("zh") ? 1280 : 390, height: 960 });
    let inventoryRequests = 0;
    page.on("request", (request) => { if (new URL(request.url()).pathname === "/__nanobot_components") inventoryRequests += 1; });
    await page.goto("/gallery.html#component=webui%2Fsrc%2Fcomponents%2Fui%2Finput.tsx");
    const input = page.getByRole("region", { name: "Component preview", exact: true }).getByRole("textbox").first();
    await input.fill("Keep this draft 中文");
    const originalInput = await input.elementHandle();
    const code = await page.locator(".gallery-code").first().innerText();
    const originalHash = new URL(page.url()).hash;

    await page.locator(".gallery-header").getByRole("combobox").click();
    await page.getByRole("option", { name: locale.label, exact: true }).click();

    await expect(page.getByRole("heading", { name: locale.title, exact: true })).toBeVisible();
    await expect(page.getByRole("searchbox", { name: locale.search })).toBeVisible();
    await expect(page.getByRole("region", { name: locale.preview, exact: true }).getByRole("textbox").first()).toHaveValue("Keep this draft 中文");
    expect(await originalInput!.evaluate((element) => element.isConnected)).toBe(true);
    expect(new URL(page.url()).hash).toBe(originalHash);
    await expect(page.locator(".gallery-code").first()).toHaveText(code);
    expect(inventoryRequests).toBe(1);
    await expect(page.locator("html")).toHaveAttribute("lang", locale.code);
    expect(await page.evaluate(() => localStorage.getItem("nanobot.locale"))).toBe(locale.code);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

    await page.reload();
    await expect(page.getByRole("heading", { name: locale.title, exact: true })).toBeVisible();
    await expect(page.locator(".gallery-header").getByRole("combobox")).toHaveText(locale.label);
  });
}

test("gallery localizes an existing error and retries in the selected language", async ({ page }) => {
  await page.route("**/__nanobot_components", (route) => route.fulfill({ status: 503, body: "unavailable" }));
  await page.goto("/gallery.html");
  await expect(page.getByRole("alert")).toContainText("Could not load the inventory");
  await page.locator(".gallery-header").getByRole("combobox").click();
  await page.getByRole("option", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("无法加载组件目录");

  await page.unroute("**/__nanobot_components");
  await page.getByRole("button", { name: "刷新目录" }).click();
  await expect(page.getByRole("region", { name: "组件预览", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "全部源码", exact: true }).click();
  await page.getByRole("searchbox", { name: "搜索组件" }).fill("SettingsView");
  await page.locator('a[href="#component=webui%2Fsrc%2Fcomponents%2Fsettings%2FSettingsView.tsx"]').click();
  await expect(page.getByRole("heading", { name: "暂无独立预览", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "预览", exact: true }).click();
  await expect(page.getByRole("region", { name: "组件预览", exact: true })).toBeVisible();
});

test("gallery translates model labels and existing interaction feedback in a narrow dark view", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 960 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/gallery.html#component=webui%2Fsrc%2Fcomponents%2Fsettings%2Fshared%2FModelControls.tsx");
  const preview = page.locator(".gallery-preview");
  await expect(preview.getByText("Provider", { exact: true })).toBeVisible();
  await expect(preview.getByText("Model", { exact: true })).toBeVisible();
  await page.locator(".gallery-header").getByRole("combobox").click();
  await page.getByRole("option", { name: "简体中文", exact: true }).click();
  await expect(preview.getByText("提供商", { exact: true })).toBeVisible();
  await expect(preview.getByText("模型", { exact: true })).toBeVisible();
  await expect(preview.getByText("推理强度", { exact: true })).toBeVisible();
  await expect(page.locator("html")).toHaveClass(/dark/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await page.locator('a[href="#component=webui%2Fsrc%2Fcomponents%2Fui%2Fbutton.tsx"]').click();
  await preview.getByRole("button", { name: "destructive", exact: true }).click();
  await expect(preview.getByRole("status")).toHaveText("按钮点击次数：1");
  await page.locator(".gallery-header").getByRole("combobox").click();
  await page.getByRole("option", { name: "English", exact: true }).click();
  await expect(preview.getByRole("status")).toHaveText("Button clicks: 1");
});

test("gallery preserves history states and subagent retries when changing language", async ({ page }) => {
  await page.goto("/gallery.html#component=webui%2Fsrc%2Fcomponents%2Fthread%2FThreadHistoryStatus.tsx");
  const preview = page.locator(".gallery-preview");
  await expect(preview.getByRole("combobox", { name: "History state" })).toHaveText("loading");
  await preview.getByRole("combobox").click();
  await page.getByRole("option", { name: "exhausted", exact: true }).click();
  await expect(preview.getByText("No earlier messages", { exact: true })).toBeVisible();

  await page.locator(".gallery-header").getByRole("combobox").click();
  await page.getByRole("option", { name: "简体中文", exact: true }).click();
  await expect(preview.getByRole("combobox", { name: "历史状态" })).toHaveText("exhausted");
  await expect(preview.getByText("没有更早的消息", { exact: true })).toBeVisible();
  await preview.getByRole("combobox").click();
  await page.getByRole("option", { name: "error", exact: true }).click();
  await preview.getByRole("button", { name: "加载失败，重试" }).click();
  await expect(preview.getByRole("combobox")).toHaveText("loading");
  await expect(preview.getByText("重试次数：1", { exact: true })).toBeVisible();

  await page.locator('a[href="#component=webui%2Fsrc%2Fcomponents%2Fthread%2FSubagentThreadView.tsx"]').click();
  await preview.getByRole("combobox").click();
  await page.getByRole("option", { name: "error", exact: true }).click();
  await expect(preview.getByRole("button", { name: "加载失败，重试" })).toBeVisible();
  await page.locator(".gallery-header").getByRole("combobox").click();
  await page.getByRole("option", { name: "English", exact: true }).click();
  await expect(preview.getByRole("combobox")).toHaveText("error");
  await preview.getByRole("button", { name: "Loading failed. Retry" }).click();
  await expect(preview.getByRole("combobox")).toHaveText("ready");
  await expect(preview.getByText("Retries: 1", { exact: true })).toBeVisible();
});
