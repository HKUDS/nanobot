import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import type { ChannelConnectPayload } from "@/lib/types";

const api = vi.hoisted(() => ({
  cancelChannelConnect: vi.fn(),
  pollChannelConnect: vi.fn(),
  startChannelConnect: vi.fn(),
}));

vi.mock("@/lib/api", () => api);
vi.mock("@/hooks/usePageVisibility", () => ({
  usePageVisibility: () => true,
}));
vi.mock("qrcode", () => ({
  default: {
    toDataURL: vi.fn(async () => "data:image/png;base64,qr"),
  },
}));

const labels = {
  qrAlt: "Login QR",
  scanTitle: "Scan QR",
  scanDescription: "Scan to continue.",
  waiting: "Waiting",
  connected: "Connected",
  stopped: "Stopped",
  connecting: "Connecting",
  scanAgain: "Scan again",
  connect: "Connect",
};

describe("ChannelQrConnectFlow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not let an in-flight poll overwrite a successful cancellation", async () => {
    let resolvePoll: ((value: ChannelConnectPayload) => void) | undefined;
    api.startChannelConnect.mockResolvedValue({
      session_id: "session-1",
      status: "pending",
      qr_url: "https://qr.test/session-1",
      interval_ms: 5000,
    });
    api.pollChannelConnect.mockImplementation(
      () => new Promise<ChannelConnectPayload>((resolve) => {
        resolvePoll = resolve;
      }),
    );
    api.cancelChannelConnect.mockImplementation(async () => {
      queueMicrotask(() => resolvePoll?.({
        session_id: "session-1",
        status: "expired",
        message: "Expired stale poll",
      }));
      return {
        session_id: "session-1",
        status: "cancelled",
        message: "Cancelled cleanly",
      };
    });

    render(
      <ChannelQrConnectFlow
        token="token"
        channelName="weixin"
        labels={labels}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("Scan QR")).toBeInTheDocument();
    await waitFor(() => expect(api.pollChannelConnect).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(await screen.findByText("Cancelled cleanly")).toBeInTheDocument();
    expect(screen.queryByText("Expired stale poll")).not.toBeInTheDocument();
  });

  it("pauses automatic polling while submitting a verification challenge", async () => {
    api.startChannelConnect.mockResolvedValue({
      session_id: "session-verify",
      status: "pending",
      qr_url: "https://qr.test/session-verify",
      interval_ms: 5000,
    });
    api.pollChannelConnect
      .mockResolvedValueOnce({
        session_id: "session-verify",
        status: "pending",
        challenge: "verify_code",
        message: "Enter the number shown in WeChat.",
      })
      .mockResolvedValueOnce({
        session_id: "session-verify",
        status: "succeeded",
        message: "Verified connection",
      });

    render(
      <ChannelQrConnectFlow
        token="token"
        channelName="weixin"
        labels={labels}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("Verification required")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Code"), {
      target: { value: "1234" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByText("Verified connection")).toBeInTheDocument();
    expect(api.pollChannelConnect).toHaveBeenLastCalledWith(
      "token",
      "weixin",
      "session-verify",
      "",
      { verifyCode: "1234" },
    );
    expect(api.pollChannelConnect).toHaveBeenCalledTimes(2);
  });
});
