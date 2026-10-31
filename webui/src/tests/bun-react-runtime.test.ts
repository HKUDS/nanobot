import { execFileSync, spawnSync } from "node:child_process";
import { expect, it } from "vitest";

const root = process.cwd();
const bunError = spawnSync("bun", ["--version"], { timeout: 10_000 }).error;
const bunAvailable = !(bunError && "code" in bunError && bunError.code === "ENOENT");

it.skipIf(!bunAvailable)("Bun loads React runtime code for the packaged Vite SSR build", () => {
  // Type-only aliases previously made Bun execute @types/react/index.d.ts.
  // npm-only development can skip this; native-package CI installs pinned Bun.
  const html = execFileSync("bun", ["--eval", `
    import { createElement } from "react";
    import { renderToStaticMarkup } from "react-dom/server";
    import { jsx } from "react/jsx-runtime";
    console.log(renderToStaticMarkup(createElement("div", null, jsx("span", {children: "ready"}))));
  `], { cwd: root, encoding: "utf8", timeout: 10_000 });
  expect(html.trim()).toBe("<div><span>ready</span></div>");
});
