import { describe, expect, it } from "vitest";
import { changeProxyAddress, changeProxyAuthentication, splitProxyUrl } from "@/lib/proxy-url";

describe("Proxy URL credentials", () => {
  it("separates encoded credentials without changing the address or decoded content", () => {
    const raw = "socks5://user%40org:p%3Aa%2F%25%2B%E5%AF%86@[::1]:1080/";
    const parts = splitProxyUrl(raw);
    expect(parts.address).toBe("socks5://[::1]:1080/");
    expect(parts.username).toBe("user@org");
    expect(parts.password).toBe("p:a/%+密");
    expect(changeProxyAuthentication(raw, parts.username, parts.password)).toBe(raw);
  });

  it("preserves unchanged credential escapes while changing host", () => {
    expect(changeProxyAddress("http://u%73er:p%61ss@old:8080", "https://new:8443"))
      .toBe("https://u%73er:p%61ss@new:8443");
  });

  it("encodes typed separators, whitespace, percent, plus and Unicode once", () => {
    const raw = changeProxyAuthentication("http://proxy:8080", "u:@ /%+名", "p:@ /%+密");
    expect(raw).toBe("http://u%3A%40%20%2F%25%2B%E5%90%8D:p%3A%40%20%2F%25%2B%E5%AF%86@proxy:8080");
    expect(splitProxyUrl(raw).password).toBe("p:@ /%+密");
  });

  it("updates only the edited credential and supports username-only authentication", () => {
    const raw = changeProxyAuthentication("http://user@proxy:8080", "user", "");
    expect(raw).toBe("http://user@proxy:8080");
    expect(changeProxyAuthentication(raw, "user", "password")).toBe("http://user:password@proxy:8080");
    expect(changeProxyAuthentication("http://u:p%61ss@proxy", "new", "pass")).toBe("http://new:p%61ss@proxy");
  });

  it("preserves raw environment references rather than encoding or resolving them", () => {
    expect(changeProxyAuthentication("${SCHEME}://${USER}:${PASSWORD}@proxy:8080", "${USER}", "new:@"))
      .toBe("${SCHEME}://${USER}:new%3A%40@proxy:8080");
    expect(changeProxyAddress("http://${PROXY_AUTH}@old:8080", "http://new:8080"))
      .toBe("http://${PROXY_AUTH}@new:8080");
    expect(splitProxyUrl("${FULL_PROXY}").address).toBe("${FULL_PROXY}");
    expect(changeProxyAddress("http://u:p@old", "${FULL_PROXY}")).toBe("${FULL_PROXY}");
  });

  it("uses pasted URL authentication and removes it only on explicit clearing", () => {
    expect(changeProxyAddress("http://old:pw@proxy", "http://new:secret@next"))
      .toBe("http://new:secret@next");
    expect(changeProxyAuthentication("http://u:p@proxy", "", "")).toBe("http://proxy");
    expect(changeProxyAddress("http://u:p@proxy", "")).toBe("");
  });

  it("does not throw or rewrite an existing malformed percent escape on an address edit", () => {
    expect(splitProxyUrl("http://u:p%invalid@old").password).toBe("p%invalid");
    expect(changeProxyAddress("http://u:p%invalid@old", "http://new")).toBe("http://u:p%invalid@new");
  });
});
