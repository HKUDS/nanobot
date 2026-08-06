import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WeixinConnectFlow } from "../../../nanobot/channels/weixin/webui/WeixinConnectFlow";

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

describe("WeixinConnectFlow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("owns verification challenge rendering and submission", async () => {
    api.startChannelConnect.mockResolvedValue({
      session_id: "session-verify",
      status: "pending",
      qr_url: "https://qr.test/session-verify",
      interval_ms: 5000,
      challenge: "verify_code",
      message: "Enter the number shown in WeChat.",
    });
    api.pollChannelConnect.mockResolvedValue({
      session_id: "session-verify",
      status: "succeeded",
      message: "Verified connection",
    });

    render(
      <WeixinConnectFlow
        token="token"
        feature={{
          name: "weixin",
          display_name: "WeChat",
          type: "channel",
          enabled: true,
          installed: true,
          ready: true,
          status: "enabled",
          install_supported: true,
          requires_restart: false,
        }}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("Verification required")).toBeInTheDocument();
    expect(api.pollChannelConnect).not.toHaveBeenCalled();

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
      { verify_code: "1234" },
    );
    expect(api.pollChannelConnect).toHaveBeenCalledTimes(1);
  });
});
