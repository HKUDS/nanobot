import { describe, expect, it } from "vitest";

import { normalizeExtensionRequestPath } from "@/lib/extension-client";

describe("extension request paths", () => {
  it("normalizes extension-relative requests to the extension API namespace", () => {
    expect(normalizeExtensionRequestPath("query-quota", "/metrics")).toBe(
      "/api/extensions/query-quota/metrics",
    );
    expect(normalizeExtensionRequestPath("query-quota", "metrics")).toBe(
      "/api/extensions/query-quota/metrics",
    );
  });

  it("keeps absolute extension API paths untouched", () => {
    expect(normalizeExtensionRequestPath("query-quota", "/api/extensions/query-quota/metrics")).toBe(
      "/api/extensions/query-quota/metrics",
    );
  });
});
