import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import postcss from "postcss";
import tailwindcss from "tailwindcss";
import loadConfig from "tailwindcss/loadConfig";
import { normalizePath, preprocessCSS, resolveConfig } from "vite";

export async function compiledGlobalCss(rawContent?: string) {
  const root = process.cwd();
  const inlineConfig = rawContent === undefined
    ? { configFile: false as const, root }
    : {
      configFile: false as const,
      root,
      css: {
        postcss: {
          plugins: [
            tailwindcss({
              ...loadConfig(resolve(root, "tailwind.config.js")),
              content: [{ raw: rawContent }],
            }),
          ],
        },
      },
    };
  const config = await resolveConfig(inlineConfig, "build", "test");
  const entry = normalizePath(resolve(config.root, "src/globals.css"));
  const { code } = await preprocessCSS(await readFile(entry, "utf8"), entry, config);
  return postcss.parse(code, { from: entry });
}
