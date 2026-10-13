import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QRCode from "qrcode";

import type { NanobotFeatureInfo } from "@/lib/types";
import { WeixinConnectFlow } from "../../../nanobot/channels/weixin/webui/WeixinConnectFlow";
import { WeixinConnectFlowView } from "../../../nanobot/channels/weixin/webui/WeixinConnectFlowView";

const { requestMutation, useClientMock } = vi.hoisted(() => ({
  requestMutation: vi.fn(), useClientMock: vi.fn(),
}));
vi.mock("@/providers/ClientProvider", () => ({ useClient: useClientMock }));

const challenge = {
  session_id: "weixin-verification", status: "pending" as const,
  qr_url: "https://example.com/weixin", challenge: "verify_code" as const,
};
const feature: NanobotFeatureInfo = {
  name: "weixin", display_name: "WeChat", type: "channel", webui: "webui/index.tsx",
  enabled: false, configured: false, installed: true, ready: true, status: "not_enabled",
  install_supported: true, requires_restart: false,
};

beforeEach(() => {
  requestMutation.mockReset();
  useClientMock.mockReset().mockReturnValue({ client: { requestMutation } });
  vi.spyOn(QRCode, "toDataURL").mockResolvedValue("data:image/png;base64,preview");
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("WeChat verification views", () => {
  it("renders without a runtime client and retains the verification draft after a rejected code", async () => {
    const onPoll = vi.fn().mockResolvedValue({ ...challenge, verification_failed: true });
    const props = {
      connect: challenge, busy: false, error: null, minimalPending: true,
      onStart: vi.fn(), onCancel: vi.fn(), onPoll,
    };
    const view = render(<WeixinConnectFlowView {...props} />);
    const code = screen.getByRole("textbox", { name: "Code" });
    fireEvent.change(code, { target: { value: " 987654 " } });
    fireEvent.click(screen.getByRole("button", { name: "Verify", exact: true }));
    await waitFor(() => expect(onPoll).toHaveBeenCalledWith({ verify_code: "987654" }));
    view.rerender(<WeixinConnectFlowView {...props} connect={{ ...challenge, verification_failed: true }} busy />);
    expect(code).toHaveValue(" 987654 ");
    expect(code).toHaveAttribute("aria-invalid", "true");
    expect(code).toHaveAttribute("aria-describedby", screen.getByRole("alert").id);
    expect(screen.getByRole("button", { name: "Verify", exact: true })).toBeDisabled();
    expect(useClientMock).not.toHaveBeenCalled();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("pauses automatic polling for verification and submits the code through the real adapter", async () => {
    requestMutation.mockResolvedValueOnce(challenge);
    const onFeaturesUpdate = vi.fn();
    render(<WeixinConnectFlow token="tok" feature={feature} onFeaturesUpdate={onFeaturesUpdate} />);
    const code = await screen.findByRole("textbox", { name: "Code" });
    vi.useFakeTimers();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(requestMutation).toHaveBeenCalledTimes(1);
    expect(requestMutation).toHaveBeenCalledWith("settings.channel.connect.start", { channel: "weixin" }, 150_000);

    requestMutation.mockResolvedValueOnce({ ...challenge, verification_failed: true });
    fireEvent.change(code, { target: { value: "123456" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Verify", exact: true })); });
    expect(requestMutation).toHaveBeenLastCalledWith("settings.channel.connect.poll", {
      channel: "weixin", session_id: "weixin-verification", verify_code: "123456",
    }, 150_000);
    expect(code).toHaveValue("123456");
    expect(code).toHaveAttribute("aria-invalid", "true");

    const features = { features: [{ ...feature, configured: true }], enabled_count: 0 };
    requestMutation.mockResolvedValueOnce({ ...challenge, status: "succeeded", nanobot_features: features });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Verify", exact: true })); });
    expect(onFeaturesUpdate).toHaveBeenCalledWith(features);
    expect(screen.getByText("WeChat is connected.")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Code" })).not.toBeInTheDocument();
  });
});
