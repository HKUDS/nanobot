import { afterEach, describe, expect, it, vi } from "vitest";

import { getBasePath } from "@/lib/base-path";
import { deriveWsUrl } from "@/lib/bootstrap";

function stubLocation(loc: Partial<Location>): void {
  vi.stubGlobal("window", { location: loc });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getBasePath", () => {
  it("returns '' at the web root (direct / native access)", () => {
    stubLocation({ pathname: "/" });
    expect(getBasePath()).toBe("");
  });

  it("derives a sub-path mount served with a trailing slash", () => {
    stubLocation({ pathname: "/nanobot/" });
    expect(getBasePath()).toBe("/nanobot");
  });

  it("derives the parent directory when served as a document path", () => {
    stubLocation({ pathname: "/nanobot/index.html" });
    expect(getBasePath()).toBe("/nanobot");
  });

  it("derives a deep sub-path mount (e.g. behind a reverse proxy)", () => {
    stubLocation({ pathname: "/apps/nanobot/" });
    expect(getBasePath()).toBe("/apps/nanobot");
  });

  it("derives the Home Assistant Ingress prefix", () => {
    stubLocation({ pathname: "/api/hassio_ingress/AbC-123/" });
    expect(getBasePath()).toBe("/api/hassio_ingress/AbC-123");
  });
});

describe("deriveWsUrl under a sub-path", () => {
  it("prefixes the WebSocket URL with the served base path (wss)", () => {
    stubLocation({
      protocol: "https:",
      host: "example.com",
      port: "",
      pathname: "/api/hassio_ingress/AbC-123/",
    } as Partial<Location>);
    expect(deriveWsUrl("/", "tok")).toBe(
      "wss://example.com/api/hassio_ingress/AbC-123/?token=tok",
    );
  });

  it("leaves the WebSocket URL unprefixed at the web root", () => {
    stubLocation({
      protocol: "https:",
      host: "example.com",
      port: "",
      pathname: "/",
    } as Partial<Location>);
    expect(deriveWsUrl("/ws", "tok")).toBe(
      "wss://example.com/ws?token=tok",
    );
  });

  it("ignores the server ws_url under a sub-path and uses the location prefix", () => {
    stubLocation({
      protocol: "https:",
      host: "example.com",
      port: "",
      pathname: "/nanobot/",
    } as Partial<Location>);
    expect(deriveWsUrl("/", "tok", "wss://example.com/")).toBe(
      "wss://example.com/nanobot/?token=tok",
    );
  });

  it("honors the server ws_url at the web root", () => {
    stubLocation({
      protocol: "https:",
      host: "example.com",
      port: "",
      pathname: "/",
    } as Partial<Location>);
    expect(deriveWsUrl("/", "tok", "wss://other.example/")).toBe(
      "wss://other.example/?token=tok",
    );
  });
});
