import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import postcss from "postcss";
import { normalizePath, preprocessCSS, resolveConfig } from "vite";

export async function compiledGlobalCss() {
  const config = await resolveConfig({}, "build", "test");
  const entry = normalizePath(resolve(config.root, "src/globals.css"));
  const { code } = await preprocessCSS(await readFile(entry, "utf8"), entry, config);
  return postcss.parse(code, { from: entry });
}
