import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ChannelValidationPayload,
  NanobotChannelInstanceInfo,
} from "@/lib/types";

import {
  isVisibleTelegramInstance,
  nextTelegramInstanceId,
  TelegramConnectionCheck,
  TelegramCredentialsForm,
} from "../../webui/TelegramBotsPanel";

const apiMocks = vi.hoisted(() => ({
  configureChannel: vi.fn(),
  validateChannel: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    configureChannel: apiMocks.configureChannel,
    validateChannel: apiMocks.validateChannel,
  };
});

const defaultFields = [
  "channels.telegram.name",
  "channels.telegram.groupPolicy",
];

function telegramInstance(
  overrides: Partial<NanobotChannelInstanceInfo> = {},
): NanobotChannelInstanceInfo {
  return {
    id: "default",
    name: "nanobot",
    enabled: false,
    configured: false,
    config_values: {
      "channels.telegram.name": "nanobot",
      "channels.telegram.groupPolicy": "mention",
    },
    configured_fields: defaultFields,
    ...overrides,
  };
}

describe("TelegramBotsPanel", () => {
  beforeEach(() => {
    apiMocks.configureChannel.mockReset();
    apiMocks.validateChannel.mockReset();
  });

  it("reuses the virtual default instance for the first bot", () => {
    const virtualDefault = telegramInstance();

    expect(isVisibleTelegramInstance(virtualDefault)).toBe(false);
    expect(nextTelegramInstanceId([virtualDefault])).toBe("default");
  });

  it("keeps a customized incomplete instance visible", () => {
    const customDefault = telegramInstance({
      name: "Support bot",
      config_values: {
        "channels.telegram.name": "Support bot",
        "channels.telegram.groupPolicy": "mention",
      },
    });

    expect(isVisibleTelegramInstance(customDefault)).toBe(true);
  });

  it("does not save a new token when Telegram verification is unavailable", async () => {
    apiMocks.validateChannel.mockResolvedValue({
      name: "telegram",
      status: "configured",
      checks: [],
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    } satisfies ChannelValidationPayload);
    const user = userEvent.setup();
    render(
      <TelegramCredentialsForm
        token="api-token"
        instanceId="default"
        submitLabel="Check and connect"
        tx={(_key, fallback) => fallback}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    await user.type(
      screen.getByLabelText("Bot token", { selector: "input" }),
      "123456:abcdefghijklmnopqrstuvwxyz",
    );
    await user.click(screen.getByRole("button", { name: "Check and connect" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Telegram could not verify this token right now. Try again before connecting.",
    );
    expect(apiMocks.configureChannel).not.toHaveBeenCalled();
  });

  it("clears a checked identity when refreshed instance data arrives", async () => {
    const validation: ChannelValidationPayload = {
      name: "telegram",
      status: "connected",
      checks: [],
      identity: { name: "old_bot" },
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    };
    apiMocks.validateChannel.mockResolvedValue(validation);
    const user = userEvent.setup();
    const instance = telegramInstance({ configured: true });
    const { rerender } = render(
      <TelegramConnectionCheck token="api-token" instance={instance} />,
    );

    await user.click(screen.getByRole("button", { name: "Check connection" }));
    expect(await screen.findByText("Connected as @old_bot.")).toBeInTheDocument();

    rerender(
      <TelegramConnectionCheck
        token="api-token"
        instance={{ ...instance }}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText("Connected as @old_bot.")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Verify the saved token with Telegram.")).toBeInTheDocument();
  });
});
