import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QRCode from "qrcode";

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

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("channel QR connect parameters", () => {
  it.each([false, true])("keeps QR generation enabled by default (minimal=%s)", async (minimalPending) => {
    const generateQr = vi.spyOn(QRCode, "toDataURL").mockResolvedValue("data:image/png;base64,preview");
    requestMutation.mockResolvedValueOnce({
      session_id: "qr-session", status: "pending", qr_url: "https://example.com/connect",
    });
    render(<ChannelQrConnectFlow token="tok" channelName="plugin-chat" labels={labels}
      minimalPending={minimalPending} onFeaturesUpdate={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Connect", exact: true }));
    expect(await screen.findByRole("img", { name: "Connection QR code" })).toHaveAttribute("src", "data:image/png;base64,preview");
    expect(generateQr).toHaveBeenCalledOnce();
  });

  it("does not generate or reserve space for QR when disabled, and still allows cancellation", async () => {
    const generateQr = vi.spyOn(QRCode, "toDataURL").mockRejectedValue(new Error("QR must not run"));
    requestMutation
      .mockResolvedValueOnce({ session_id: "browser-session", status: "pending", qr_url: "https://example.com/authorize" })
      .mockResolvedValueOnce({ session_id: "browser-session", status: "cancelled" });
    render(<ChannelQrConnectFlow token="tok" channelName="plugin-chat" showQrCode={false}
      labels={{ ...labels, scanTitle: "Authorize in browser", scanDescription: "Continue in the browser." }}
      onFeaturesUpdate={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Connect", exact: true }));
    expect(await screen.findByText("Continue in the browser.")).toBeVisible();
    expect(screen.getByText("Waiting")).toBeVisible();
    expect(generateQr).not.toHaveBeenCalled();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Authorize in browser").parentElement?.parentElement)
      .not.toHaveClass("sm:grid-cols-[auto_minmax(0,1fr)]");
    fireEvent.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    expect(await screen.findByText("Stopped")).toBeVisible();
    expect(requestMutation).toHaveBeenLastCalledWith("settings.channel.connect.cancel", {
      channel: "plugin-chat", session_id: "browser-session",
    }, 20_000);
  });

  it("polls browser-only authorization to completion without generating QR", async () => {
    const generateQr = vi.spyOn(QRCode, "toDataURL").mockResolvedValue("data:image/png;base64,unused");
    const onFeaturesUpdate = vi.fn();
    const features = { features: [], enabled_count: 0 };
    requestMutation
      .mockResolvedValueOnce({ session_id: "browser-session", status: "pending", qr_url: "https://example.com/authorize" })
      .mockResolvedValueOnce({ session_id: "browser-session", status: "succeeded", nanobot_features: features });
    render(<ChannelQrConnectFlow token="tok" channelName="plugin-chat" showQrCode={false}
      labels={labels} onFeaturesUpdate={onFeaturesUpdate} />);
    fireEvent.click(screen.getByRole("button", { name: "Connect", exact: true }));
    expect(await screen.findByText("Connected", {}, { timeout: 2000 })).toBeVisible();
    expect(onFeaturesUpdate).toHaveBeenCalledWith(features);
    expect(requestMutation).toHaveBeenLastCalledWith("settings.channel.connect.poll", {
      channel: "plugin-chat", session_id: "browser-session",
    }, 150_000);
    expect(generateQr).not.toHaveBeenCalled();
  });

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
