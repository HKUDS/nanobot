import { describe, expect, it } from "vitest";

import {
  formatCompactWebUrl,
  parsePublicHttpUrl,
  parseSafeActivityHttpUrl,
} from "@/components/thread/activity/web-url";

describe("activity web URLs", () => {
  it("keeps public HTTP URLs and removes query noise from their label", () => {
    const url = parsePublicHttpUrl("https://www.example.com/docs/?token=private#section");
    expect(url).not.toBeNull();
    expect(formatCompactWebUrl(url!)).toBe("example.com/docs");
  });

  it.each([
    "http://localhost:3000",
    "http://service.internal",
    "http://printer.lan",
    "http://127.0.0.1",
    "http://10.0.0.1",
    "http://169.254.169.254/latest/meta-data",
    "http://172.16.0.1",
    "http://192.168.1.1",
    "http://[::1]",
    "http://[::ffff:127.0.0.1]",
    "https://user:password@example.com",
  ])("rejects private or credential-bearing target %s", (value) => {
    expect(parsePublicHttpUrl(value)).toBeNull();
  });

  it("normalizes credential-bearing public URLs for safe activity display", () => {
    const url = parseSafeActivityHttpUrl(
      "https://user:password@example.com/docs?access_token=private#section",
    );
    expect(url?.href).toBe("https://example.com/docs");
    expect(formatCompactWebUrl(url!)).toBe("example.com/docs");
  });
});
