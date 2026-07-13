import { describe, expect, it } from "vitest";

import { SLACK_SOCKET_MODE_MANIFEST } from "@/components/settings/channels/catalog";

describe("Slack setup manifest", () => {
  it.each(["app_mention", "message.channels", "message.groups", "message.im", "message.mpim"])(
    "subscribes to %s",
    (event) => expect(SLACK_SOCKET_MODE_MANIFEST).toContain(`      - ${event}`),
  );

  it.each([
    "app_mentions:read",
    "channels:history",
    "channels:read",
    "chat:write",
    "files:read",
    "files:write",
    "groups:history",
    "groups:read",
    "im:history",
    "im:write",
    "mpim:history",
    "reactions:write",
    "users:read",
  ])("requests the %s scope", (scope) => {
    expect(SLACK_SOCKET_MODE_MANIFEST).toContain(`      - ${scope}`);
  });
});
