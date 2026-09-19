import { describe, expect, it } from "vitest";

import i18n from "@/i18n";
import { resolveModelRequestFailureCopy } from "@/lib/model-request-failure";

describe("model request failure copy", () => {
  it("maps every sanitized provider error category to a specific cause", () => {
    const titles = ["billing", "connection", "timeout", "rate_limit", "server", "unknown"].map(
      (errorKind) => resolveModelRequestFailureCopy({ errorKind }, i18n.t).title,
    );

    expect(titles).toEqual([
      "Model provider quota is unavailable",
      "Could not connect to the model provider",
      "Model provider request timed out",
      "Model provider rate limit reached",
      "Model provider service error",
      "Model provider request failed",
    ]);
  });

  it("reports the final attempt and a concrete recovery action", () => {
    expect(resolveModelRequestFailureCopy(
      { errorKind: "connection", attempts: 4 },
      i18n.t,
    ).body).toBe(
      "The request still failed on attempt 4, so retries stopped. "
      + "Check the provider configuration or service status, then try again.",
    );
  });

  it("provides billing recovery without claiming a retry occurred", () => {
    expect(resolveModelRequestFailureCopy(
      { errorKind: "billing" },
      i18n.t,
    ).body).toBe(
      "Add credit or check billing for the provider account, then try again.",
    );
  });

  it("does not claim retries stopped without an attempt count", () => {
    const body = resolveModelRequestFailureCopy({ errorKind: "unknown" }, i18n.t).body;

    expect(body).toBe(
      "Check the provider configuration or service status, then try again.",
    );
  });
});
