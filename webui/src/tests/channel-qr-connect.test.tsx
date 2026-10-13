import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QRCode from "qrcode";

import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import { FeishuConnectFlow } from "../../../nanobot/channels/feishu/webui/FeishuConnectFlow";
import { FeishuAssistantsPanel } from "../../../nanobot/channels/feishu/webui/FeishuAssistantsPanel";
import type { NanobotFeatureInfo } from "@/lib/types";

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
  it("adds an assistant without replacing existing ones, and supports cancellation and retry", async () => {
    const feature: NanobotFeatureInfo = {
      name: "feishu", display_name: "Feishu", type: "channel", webui: "webui/index.tsx",
      enabled: true, configured: true, installed: true, ready: true, status: "enabled",
      install_supported: true, requires_restart: false,
      instances: [{
        id: "default", name: "First assistant", enabled: true, configured: true,
        runtime_status: "running", config_values: {}, configured_fields: [],
      }],
    };
    const onFeaturesUpdate = vi.fn();
    const props = { token: "tok", feature, showBrandLogos: false, onFeaturesUpdate };
    const view = render(<FeishuAssistantsPanel {...props} />);
    requestMutation.mockResolvedValueOnce({
      session_id: "add-1", status: "pending", qr_url: "https://example.com/authorize",
    });
    fireEvent.click(screen.getByRole("button", { name: "Add another assistant" }));
    expect(await screen.findByText("Scan with Feishu")).toBeVisible();
    expect(requestMutation).toHaveBeenCalledWith("settings.channel.connect.start", {
      channel: "feishu", domain: "feishu", instance_id: "default", mode: "create",
    }, 150_000);
    expect(screen.getByText("First assistant")).toBeVisible();
    requestMutation.mockResolvedValueOnce({ session_id: "add-1", status: "cancelled" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    await screen.findByRole("button", { name: "Add another assistant" });
    expect(requestMutation).toHaveBeenLastCalledWith("settings.channel.connect.cancel", {
      channel: "feishu", session_id: "add-1",
    }, 20_000);
    expect(onFeaturesUpdate).not.toHaveBeenCalled();

    requestMutation.mockRejectedValueOnce(new Error("Authorization unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Add another assistant" }));
    expect(await screen.findByText("Authorization unavailable")).toBeVisible();
    const updated = { ...feature, instances: [...feature.instances!, {
      ...feature.instances![0], id: "assistant-new", name: "Second assistant",
    }] };
    const payload = { features: [updated], enabled_count: 1 };
    requestMutation.mockResolvedValueOnce({ status: "succeeded", nanobot_features: payload });
    fireEvent.click(screen.getByRole("button", { name: "Add another assistant" }));
    await waitFor(() => expect(onFeaturesUpdate).toHaveBeenCalledWith(payload));
    view.rerender(<FeishuAssistantsPanel {...props} feature={updated} />);
    expect(screen.getByText("First assistant")).toBeVisible();
    expect(screen.getByText("Second assistant")).toBeVisible();
    expect(screen.getByRole("button", { name: "Add another assistant" })).toBeEnabled();
    expect(screen.queryByText("Authorization unavailable")).not.toBeInTheDocument();
  });

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
