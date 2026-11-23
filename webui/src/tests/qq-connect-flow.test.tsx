import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import QRCode from "qrcode";

import i18n from "@/i18n";
import type { ChannelConnectPayload, NanobotFeatureInfo } from "@/lib/types";

import { QQConnectFlow } from "../../../nanobot/channels/qq/webui/QQConnectFlow";
import { QQConnectFlowView } from "../../../nanobot/channels/qq/webui/QQConnectFlowView";

const { requestMutation } = vi.hoisted(() => ({ requestMutation: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => {
  const client = { requestMutation };
  return { useClient: () => ({ client }) };
});

const pending: ChannelConnectPayload = {
  session_id: "qq-test",
  status: "pending",
  qr_url: "https://example.invalid/qq-bind",
  retrying: false,
};
const actions = () => ({
  busy: false,
  error: null,
  onStart: vi.fn(),
  onCancel: vi.fn(),
  onPoll: vi.fn(async () => null),
  onManualSetup: vi.fn(),
});

beforeEach(() => requestMutation.mockReset());
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

it("keeps the QR and manual setup available while retrying, then returns to waiting", async () => {
  const props = actions();
  const { rerender } = render(<QQConnectFlowView {...props} connect={pending} />);
  const qr = await screen.findByRole("img", { name: "QQ binding QR code" });
  expect(screen.getByRole("status")).toHaveTextContent("Waiting for scan…");
  rerender(<QQConnectFlowView {...props} connect={{ ...pending, retrying: true }} />);
  expect(screen.getByRole("status")).toHaveTextContent("Retrying…");
  expect(qr).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Enter credentials manually" }));
  expect(props.onManualSetup).toHaveBeenCalledOnce();
  rerender(<QQConnectFlowView {...props} connect={pending} />);
  expect(screen.getByRole("status")).toHaveTextContent("Waiting for scan…");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(props.onCancel).toHaveBeenCalledOnce();
});

it.each([
  ["expired", "二维码已过期", "刷新二维码"],
  ["failed", "绑定失败", "重试"],
  ["cancelled", "已取消", "绑定机器人"],
] as const)("shows a localized %s state and a working recovery action", async (status, label, action) => {
  await i18n.changeLanguage("zh-CN");
  const props = actions();
  render(<QQConnectFlowView {...props} connect={{ ...pending, status, message: "Raw portal response" }} />);
  expect(screen.getByRole("status")).toHaveTextContent(label);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.queryByText("Raw portal response")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: action }));
  expect(props.onStart).toHaveBeenCalledOnce();
});

it("offers retry after QR preparation fails without showing a successful binding", () => {
  const props = { ...actions(), error: "Unable to start QQ QR login: portal error" };
  render(<QQConnectFlowView {...props} connect={null} autoStart />);
  expect(screen.getByRole("alert")).toHaveTextContent("Binding failed");
  expect(screen.queryByText("Configured")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(props.onStart).toHaveBeenCalledOnce();
});

it("clears a transport retry indication when polling recovers before the scan finishes", async () => {
  const feature: NanobotFeatureInfo = {
    name: "qq", display_name: "QQ", type: "channel", enabled: false,
    configured: false, installed: true, ready: false, status: "not_enabled",
    install_supported: true, requires_restart: false,
  };
  requestMutation.mockResolvedValueOnce({ ...pending, interval_ms: 2500 })
    .mockRejectedValueOnce(new Error("connection interrupted"))
    .mockResolvedValueOnce(pending);
  vi.spyOn(QRCode, "toDataURL").mockImplementation(async () => "data:image/png;base64,preview");
  vi.useFakeTimers();
  await act(async () => {
    render(<QQConnectFlow token="test" feature={feature} onFeaturesUpdate={vi.fn()} />);
  });
  expect(screen.getByRole("status")).toHaveTextContent("Waiting for scan…");
  await act(async () => { await vi.advanceTimersByTimeAsync(900); });
  expect(screen.getByRole("status")).toHaveTextContent("Retrying…");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
  expect(screen.getByRole("status")).toHaveTextContent("Waiting for scan…");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(requestMutation).toHaveBeenCalledTimes(3);
});

it("keeps cancellation errors distinct from poll recovery and clears them after cancelling", async () => {
  const feature: NanobotFeatureInfo = {
    name: "qq", display_name: "QQ", type: "channel", enabled: false,
    configured: false, installed: true, ready: false, status: "not_enabled",
    install_supported: true, requires_restart: false,
  };
  requestMutation.mockResolvedValueOnce({ ...pending, interval_ms: 2500 })
    .mockRejectedValueOnce(new Error("connection interrupted"))
    .mockRejectedValueOnce(new Error("cancel request failed"))
    .mockRejectedValueOnce(new Error("connection still interrupted"))
    .mockResolvedValueOnce(pending)
    .mockResolvedValueOnce({ session_id: pending.session_id, status: "cancelled", retrying: false });
  vi.spyOn(QRCode, "toDataURL").mockImplementation(async () => "data:image/png;base64,preview");
  vi.useFakeTimers();
  await act(async () => {
    render(<QQConnectFlow token="test" feature={feature} onFeaturesUpdate={vi.fn()} />);
  });
  await act(async () => { await vi.advanceTimersByTimeAsync(900); });
  expect(screen.getByRole("status")).toHaveTextContent("Retrying…");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Cancel" })); });
  expect(screen.getByRole("alert")).toHaveTextContent("Could not cancel");
  await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
  expect(screen.getByRole("alert")).toHaveTextContent("Could not cancel");
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(screen.getByRole("alert")).toHaveTextContent("Could not cancel");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Cancel" })); });
  expect(screen.getByRole("status")).toHaveTextContent("Cancelled");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Bind QQ bot" })).toBeEnabled();
});
