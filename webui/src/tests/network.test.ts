import { describe, expect, it } from "vitest";

import { isLoopbackHost } from "@/lib/network";

describe("isLoopbackHost", () => {
  it.each(["localhost", "LOCALHOST.", "127.0.0.1", "127.0.0.2", "::1", "[::1]"])(
    "accepts explicit loopback host %s",
    (host) => expect(isLoopbackHost(host)).toBe(true),
  );

  it.each(["0.0.0.0", "::", "192.168.1.10", "api.internal", "example.com"])(
    "rejects network host %s",
    (host) => expect(isLoopbackHost(host)).toBe(false),
  );
});
