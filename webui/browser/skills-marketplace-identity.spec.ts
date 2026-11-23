import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  for (const theme of ["light", "dark"]) {
    for (const locale of ["en", "zh-CN"]) {
      test(`marketplace source states remain distinct at ${width}px in ${theme} ${locale}`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width, height: 900 });
        await page.addInitScript((language) => localStorage.setItem("nanobot.locale", language), locale);
        const labels = locale === "en"
          ? { installed: "Installed", conflict: "Name already in use", unknown: "Installed source unknown", search: "Search skills", trending: "Popular skills", install: "Install", cancel: "Cancel" }
          : { installed: "已安装", conflict: "技能名称已占用", unknown: "已装技能来源未知", search: "搜索技能", trending: "热门技能", install: "安装", cancel: "取消" };
        const rows = ["installed", "conflict", "unknown", "available"].map((status, index) => ({
          id: `owner-${index}/skills/agent-browser`, skill_id: "agent-browser", name: "agent-browser",
          source: `owner-${index}/skills`, provider: "skills_sh", installs: 120,
          url: `https://skills.sh/owner-${index}/skills/agent-browser`,
          installed: status === "installed", installation_status: status,
          install_supported: true, metric: "installs_total",
        }));
        let trendReads = 0;
        await page.route("**/api/webui/skills/trending?**", (route) => route.fulfill({
          json: { period: "mixed", provider: "all", install_supported: true, skills: rows },
        }));
        await page.route("**/api/webui/skills/search?**", (route) => route.fulfill({
          json: { query: "agent-browser", provider: "all", install_supported: true, skills: rows },
        }));
        await page.route("**/api/webui/skills/trends?**", (route) => {
          trendReads += 1;
          return route.fulfill({ json: { trends: {} } });
        });
        await page.goto("/browser/fixture.html?case=skeleton&surface=marketplace");
        await page.locator("html").evaluate((element, dark) => element.classList.toggle("dark", dark), theme === "dark");
        expect(await page.locator("html").evaluate((element) => element.classList.contains("dark"))).toBe(theme === "dark");
        await expect(page.getByRole("button", { name: `${labels.installed} agent-browser`, exact: true })).toHaveCount(1);
        await expect(page.getByRole("button", { name: `${labels.conflict} agent-browser` })).toHaveCount(2);
        await expect(page.getByText(labels.unknown, { exact: true })).toBeVisible();
        await page.getByRole("textbox", { name: labels.search }).fill("agent-browser");
        await expect(page.getByRole("heading", { name: labels.trending })).toHaveCount(0);
        await page.getByRole("button", { name: `${labels.install} agent-browser`, exact: true }).click();
        await expect(page.getByRole("alertdialog")).toContainText("owner-3/skills");
        await page.getByRole("button", { name: labels.cancel, exact: true }).click();
        await expect(page.getByRole("alertdialog")).toHaveCount(0);
        await expect(page.locator('.fixed[data-state="closed"]')).toHaveCount(0);
        await expect(page.getByRole("button", { name: `${labels.install} agent-browser`, exact: true })).toBeFocused();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(trendReads).toBe(1);
        await page.screenshot({ path: testInfo.outputPath("marketplace.png"), fullPage: true });
      });
    }
  }
}
