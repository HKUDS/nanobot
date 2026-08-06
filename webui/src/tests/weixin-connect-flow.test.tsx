import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WeixinConnectFlow } from "../../../nanobot/channels/weixin/webui/WeixinConnectFlow";
import i18n from "@/i18n";

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

    expect(await screen.findByText("WeChat is connected.")).toBeInTheDocument();
    expect(screen.queryByText("Verified connection")).not.toBeInTheDocument();
    expect(api.pollChannelConnect).toHaveBeenLastCalledWith(
      "token",
      "weixin",
      "session-verify",
      "",
      { verify_code: "1234" },
    );
    expect(api.pollChannelConnect).toHaveBeenCalledTimes(1);
  });

  it("localizes a successful backend status instead of rendering its English message", async () => {
    await i18n.changeLanguage("zh-CN");
    api.startChannelConnect.mockResolvedValue({
      session_id: "session-connected",
      status: "succeeded",
      message: "WeChat is connected.",
    });

    render(
      <WeixinConnectFlow
        token="token"
        idleLabel="连接微信"
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

    fireEvent.click(screen.getByRole("button", { name: "连接微信" }));

    expect(await screen.findByText("微信已连接。")).toBeInTheDocument();
    expect(screen.queryByText("WeChat is connected.")).not.toBeInTheDocument();
  });

  it("preserves a backend failure diagnostic", async () => {
    api.startChannelConnect.mockResolvedValue({
      session_id: "session-failed",
      status: "failed",
      message: "WeChat reports an existing binding, but no local credentials were found.",
    });

    render(
      <WeixinConnectFlow
        token="token"
        idleLabel="连接微信"
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

    fireEvent.click(screen.getByRole("button", { name: "连接微信" }));

    expect(await screen.findByText(
      "WeChat reports an existing binding, but no local credentials were found.",
    )).toBeInTheDocument();
  });
});
