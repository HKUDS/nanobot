import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`preserves dollar references while streaming at ${width}px`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/browser/fixture.html?case=markdown-dollar-refs");
    const reply = page.getByRole("region", { name: "Reported assistant reply" });
    const formulas = page.getByRole("region", { name: "Inline formulas" });
    const precedence = page.getByRole("region", { name: "Code and math precedence" });
    async function expectPrecedence() {
      await expect(precedence.locator("strong")).toHaveText(["$ref", "$ref"]);
      await expect(precedence.locator("code")).toHaveText(["$defs / definitions", "$defs", "$th", "code"]);
      await expect(precedence.locator("annotation")).toHaveText(["f(`x')"]);
      await expect(precedence.locator(".katex-error")).toHaveCount(0);
    }
    await expectPrecedence();
    await expect(formulas.locator("annotation")).toHaveText(["n", "\\text{`value`}"]);
    await expect(formulas.locator(".katex-error")).toHaveCount(0);
    for (let step = 0; step < 5; step++) {
      await expect(reply.locator("strong").filter({ hasText: "已经有一份完整的 $ref 解析器" })).toHaveCount(1);
      await expect(reply.locator(".katex")).toHaveCount(0);
      if (step < 4) await page.getByRole("button", { name: "Advance stream" }).click();
    }
    await expect(reply.locator("code").filter({ hasText: "_resolve_local_schema_ref" })).toHaveCount(1);
    await expect(reply.locator("code").filter({ hasText: "$defs" }).first()).toHaveText("$defs");
    await expect(reply).toContainText("用一个词总结这个 PR");
    await page.getByRole("button", { name: "Complete" }).click();
    await expect(reply.locator("[data-assistant-selectable=true]")).toHaveCount(1);
    await expect(reply.locator("strong").filter({ hasText: "已经有一份完整的 $ref 解析器" })).toHaveCount(1);
    await expect(reply.locator(".katex")).toHaveCount(0);
    await expectPrecedence();
    expect(errors).toEqual([]);
    if (width === 1280) await page.screenshot({ path: info.outputPath("reported-message.png"), fullPage: true });
  });
}
