import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";

import {
  entryLazyFeatureImports,
  gzipWebuiAssets,
  webuiManualChunk,
  writeCompressedWebuiAssets,
} from "../../vite.config";

describe("gzipWebuiAssets", () => {
  it("compresses finalized files after Rollup writes the bundle", () => {
    const plugin = gzipWebuiAssets();
    expect(plugin.generateBundle).toBeUndefined();
    expect(plugin.writeBundle).toBeTypeOf("function");

    const outputDir = mkdtempSync(path.join(tmpdir(), "nanobot-vite-gzip-"));
    try {
      const assetPath = path.join(outputDir, "assets", "index-final.js");
      mkdirSync(path.dirname(assetPath), { recursive: true });
      const finalized = Buffer.from(
        "const __vite__mapDeps = ['assets/lazy-feature.js'];\n".repeat(200),
      );
      writeFileSync(assetPath, finalized);

      writeCompressedWebuiAssets(outputDir, ["assets/index-final.js"]);

      expect(gunzipSync(readFileSync(`${assetPath}.gz`))).toEqual(finalized);
    } finally {
      rmSync(outputDir, { recursive: true, force: true });
    }
  });
});

describe("entryLazyFeatureImports", () => {
  it("allows the core runtime but rejects heavy lazy feature chunks", () => {
    expect(entryLazyFeatureImports(["assets/react-vendor-abc.js"])).toEqual([]);
    expect(entryLazyFeatureImports([
      "assets/markdown-vendor-abc.js",
      "assets/syntax-highlight-def.js",
      "assets/katex-ghi.js",
    ])).toEqual([
      "assets/markdown-vendor-abc.js",
      "assets/syntax-highlight-def.js",
      "assets/katex-ghi.js",
    ]);
  });
});

describe("webuiManualChunk", () => {
  it("keeps the React runtime outside lazy feature chunks", () => {
    expect(webuiManualChunk("/repo/node_modules/react/index.js")).toBe("react-vendor");
    expect(webuiManualChunk("/repo/node_modules/react-dom/client.js")).toBe("react-vendor");
    expect(webuiManualChunk("/repo/node_modules/scheduler/index.js")).toBe("react-vendor");
    expect(webuiManualChunk("/repo/node_modules/clsx/dist/clsx.mjs")).toBe("react-vendor");
    expect(webuiManualChunk("\0vite/preload-helper.js")).toBe("react-vendor");
  });

  it("keeps Refractor's selector parser in the syntax highlighting chunk", () => {
    expect(
      webuiManualChunk("/repo/node_modules/hast-util-parse-selector/index.js"),
    ).toBe("syntax-highlight");
  });

  it("keeps markdown-only hast utilities in the markdown chunk", () => {
    expect(
      webuiManualChunk("/repo/node_modules/hast-util-to-jsx-runtime/lib/index.js"),
    ).toBe("markdown-vendor");
  });

  it("keeps Streamdown and its repair helper in the markdown chunk", () => {
    expect(webuiManualChunk("/repo/node_modules/streamdown/dist/index.js")).toBe(
      "markdown-vendor",
    );
    expect(webuiManualChunk("/repo/node_modules/remend/dist/index.js")).toBe(
      "markdown-vendor",
    );
  });

  it("leaves Streamdown's optional renderers as lazy chunks", () => {
    expect(
      webuiManualChunk("/repo/node_modules/streamdown/dist/mermaid-ABC.js"),
    ).toBeUndefined();
    expect(
      webuiManualChunk("/repo/node_modules/streamdown/dist/highlighted-body-ABC.js"),
    ).toBeUndefined();
  });

  it("leaves language grammars as independently loaded chunks", () => {
    expect(webuiManualChunk("/repo/node_modules/refractor/lang/python.js")).toBeUndefined();
  });
});
