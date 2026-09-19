import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import { FeishuConnectFlow } from "../../../nanobot/channels/feishu/webui/FeishuConnectFlow";

const { requestMutation } = vi.hoisted(() => ({ requestMutation: vi.fn() }));

vi.mock("@/providers/ClientProvider", () => {
  const client = { requestMutation };
  return { useClient: () => ({ client }) };
});

const labels = {
  qrAlt: "Connection QR code",
  scanTitle: "Scan to connect",
  scanDescription: "Scan with your app",
  waiting: "Waiting",
  connected: "Connected",
  stopped: "Stopped",
  connecting: "Connecting",
  scanAgain: "Scan again",
  connect: "Connect",
};

beforeEach(() => {
  requestMutation.mockReset().mockResolvedValue({
    session_id: "link-1",
    status: "succeeded",
  });
});

afterEach(cleanup);

describe("channel QR connect parameters", () => {
  it("forwards current channel parameters without restarting on rerender and preserves forced retries", async () => {
    const props = {
      token: "tok",
      channelName: "plugin-chat",
      autoStart: true,
      forceOnRepeat: true,
      labels,
      onFeaturesUpdate: vi.fn(),
    };
    const view = render(<ChannelQrConnectFlow {...props} startParams={{ region: "eu" }} />);
    await waitFor(() => expect(requestMutation).toHaveBeenCalledTimes(1));
    expect(requestMutation).toHaveBeenLastCalledWith(
      "settings.channel.connect.start",
      { channel: "plugin-chat", region: "eu" },
      150_000,
    );
    await screen.findByText("Connected");

    view.rerender(<ChannelQrConnectFlow {...props} startParams={{ region: "us" }} />);
    expect(requestMutation).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Scan again" }));
    await waitFor(() => expect(requestMutation).toHaveBeenCalledTimes(2));
    expect(requestMutation).toHaveBeenLastCalledWith(
      "settings.channel.connect.start",
      { channel: "plugin-chat", region: "us", force: true },
      150_000,
    );
  });

  it("preserves the Feishu-owned registration domain and instance creation mode", async () => {
    render(
      <FeishuConnectFlow
        token="tok"
        instanceId="support"
        mode="create"
        connectRequestId={1}
        onFeaturesUpdate={vi.fn()}
      />,
    );
    await waitFor(() => expect(requestMutation).toHaveBeenCalledWith(
      "settings.channel.connect.start",
      { channel: "feishu", domain: "feishu", instance_id: "support", mode: "create" },
      150_000,
    ));
  });
});
