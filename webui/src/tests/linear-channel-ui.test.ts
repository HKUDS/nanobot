import { describe, expect, it } from "vitest";

import { linearManifestUrl } from "../../../nanobot/channels/linear/webui/LinearConnectFlow";

describe("Linear channel UI", () => {
  it("creates a private mention-only Agent app manifest with exact callback routes", () => {
    const url = new URL(
      linearManifestUrl(
        "https://nanobot.example.com",
        "/linear/webhook",
        "/linear/oauth/callback",
      ),
    );
    const manifest = JSON.parse(url.searchParams.get("manifest") ?? "{}") as {
      distribution?: string;
      oauth?: { redirect_uris?: string[] };
      webhook?: { url?: string; resourceTypes?: string[] };
    };

    expect(url.origin + url.pathname).toBe(
      "https://linear.app/settings/api/applications/new",
    );
    expect(manifest.distribution).toBe("private");
    expect(manifest.oauth?.redirect_uris).toEqual([
      "https://nanobot.example.com/linear/oauth/callback",
    ]);
    expect(manifest.webhook?.url).toBe(
      "https://nanobot.example.com/linear/webhook",
    );
    expect(manifest.webhook?.resourceTypes).toEqual([
      "AgentSessionEvent",
      "PermissionChange",
      "OAuthAuthorization",
    ]);
    expect(manifest.webhook?.resourceTypes).not.toContain("Comment");
  });
});
