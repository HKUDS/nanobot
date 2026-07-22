import { describe, expect, it } from "vitest";

import { webuiManualChunk } from "../../vite.config";

describe("webuiManualChunk", () => {
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
