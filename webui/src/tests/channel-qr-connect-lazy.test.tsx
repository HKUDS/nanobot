import { Buffer } from "node:buffer";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import type { QRCodeToDataURLOptions } from "qrcode";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChannelQrConnectFlowViewProps } from "@/components/settings/channels/ChannelQrConnectFlowView";
import type { ChannelConnectPayload } from "@/lib/types";

const props: ChannelQrConnectFlowViewProps = {
  connect: null,
  busy: false,
  error: null,
  onStart: () => {},
  onCancel: () => {},
  onPoll: async () => null,
  labels: {
    qrAlt: "Connection QR code",
    scanTitle: "Scan to connect",
    scanDescription: "Scan with your app",
    waiting: "Waiting",
    connected: "Connected",
    stopped: "Stopped",
    connecting: "Connecting",
    scanAgain: "Scan again",
    connect: "Connect",
  },
};

const firstUrl = "https://example.com/connect/first";
const nextUrl = "https://example.com/connect/next";
const currentImage = "data:image/png;base64,current";
const qrOptions = {
  width: 184,
  margin: 1,
  color: { dark: "#111827", light: "#ffffff" },
};

function pending(qr_url?: string): ChannelConnectPayload {
  return { session_id: "qr-session", status: "pending", qr_url };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function mockQrModule(ready: Promise<void> = Promise.resolve()) {
  const toDataURL = vi.fn<(text: string, options: QRCodeToDataURLOptions) => Promise<string>>()
    .mockResolvedValue(currentImage);
  const load = vi.fn(async () => {
    await ready;
    return { default: { toDataURL } };
  });
  vi.doMock("qrcode", load);
  return { toDataURL, load };
}

async function loadView() {
  const { ChannelQrConnectFlowView } = await import("@/components/settings/channels/ChannelQrConnectFlowView");
  return ChannelQrConnectFlowView;
}

beforeEach(() => { vi.resetModules(); });
afterEach(() => {
  cleanup();
  vi.doUnmock("qrcode");
  vi.restoreAllMocks();
});

describe("channel QR encoder loading", () => {
  it("loads and encodes only when a visible QR URL is available", async () => {
    const { toDataURL, load } = mockQrModule();
    toDataURL.mockImplementation(async (text, options) => {
      const actual = await vi.importActual<typeof import("qrcode")>("qrcode");
      return actual.toDataURL(text, options);
    });
    const View = await loadView();
    const view = render(<View {...props} />);
    await vi.dynamicImportSettled();
    expect(load).not.toHaveBeenCalled();
    expect(toDataURL).not.toHaveBeenCalled();

    view.rerender(<View {...props} connect={pending()} />);
    await vi.dynamicImportSettled();
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");
    expect(load).not.toHaveBeenCalled();
    expect(toDataURL).not.toHaveBeenCalled();

    view.rerender(<View {...props} connect={pending(firstUrl)} showQrCode={false} />);
    await vi.dynamicImportSettled();
    expect(screen.getByRole("status")).toHaveTextContent("Waiting");
    expect(screen.getByText("Scan with your app")).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();
    expect(toDataURL).not.toHaveBeenCalled();

    view.rerender(<View {...props} connect={pending(firstUrl)} />);
    const image = await screen.findByRole("img", { name: "Connection QR code" });
    expect(load).toHaveBeenCalledOnce();
    expect(toDataURL).toHaveBeenCalledOnce();
    expect(toDataURL).toHaveBeenCalledWith(firstUrl, qrOptions);
    expect(image).toHaveClass("h-[184px]", "w-[184px]");
    expect(screen.getByRole("status")).toHaveTextContent("Waiting");
    const source = image.getAttribute("src")!;
    expect(source).toMatch(/^data:image\/png;base64,/);
    const png = Buffer.from(source.split(",")[1], "base64");
    expect(png.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
    expect(png.readUInt32BE(16)).toBe(184);
    expect(png.readUInt32BE(20)).toBe(184);
  });

  it.each(["removed", "hidden", "unmounted"] as const)(
    "does not encode if the QR is %s while the library loads",
    async (change) => {
      const ready = deferred<void>();
      const { toDataURL, load } = mockQrModule(ready.promise);
      const View = await loadView();
      const view = render(<View {...props} connect={pending(firstUrl)} />);
      await waitFor(() => expect(load).toHaveBeenCalledOnce());
      if (change === "unmounted") {
        view.unmount();
      } else {
        view.rerender(<View {...props}
          connect={pending(change === "removed" ? undefined : firstUrl)}
          showQrCode={change !== "hidden"} />);
      }

      await act(async () => {
        ready.resolve(undefined);
        await vi.dynamicImportSettled();
      });
      expect(toDataURL).not.toHaveBeenCalled();
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    },
  );

  it.each(["result", "failure"] as const)(
    "ignores a late encoder %s after a newer QR is displayed",
    async (outcome) => {
      const stale = deferred<string>();
      const current = deferred<string>();
      const { toDataURL } = mockQrModule();
      toDataURL.mockReturnValueOnce(stale.promise).mockReturnValueOnce(current.promise);
      const View = await loadView();
      const view = render(<View {...props} connect={pending(firstUrl)} />);
      await waitFor(() => expect(toDataURL).toHaveBeenCalledTimes(1));
      view.rerender(<View {...props} connect={pending(nextUrl)} />);
      await waitFor(() => expect(toDataURL).toHaveBeenCalledTimes(2));
      await act(async () => { current.resolve(currentImage); });
      expect(screen.getByRole("img")).toHaveAttribute("src", currentImage);

      await act(async () => {
        if (outcome === "result") stale.resolve("data:image/png;base64,stale");
        else stale.reject(new Error("Old QR encoding failed"));
      });
      expect(screen.getByRole("img")).toHaveAttribute("src", currentImage);
      expect(screen.getByRole("status")).toHaveTextContent("Waiting");
    },
  );

  it("does not resurrect a hidden QR from a late encoder result when shown again", async () => {
    const stale = deferred<string>();
    const current = deferred<string>();
    const { toDataURL } = mockQrModule();
    toDataURL.mockReturnValueOnce(stale.promise).mockReturnValueOnce(current.promise);
    const View = await loadView();
    const view = render(<View {...props} connect={pending(firstUrl)} />);
    await waitFor(() => expect(toDataURL).toHaveBeenCalledTimes(1));
    view.rerender(<View {...props} connect={pending(firstUrl)} showQrCode={false} />);
    await act(async () => { stale.resolve("data:image/png;base64,stale"); });
    view.rerender(<View {...props} connect={pending(firstUrl)} />);
    await waitFor(() => expect(toDataURL).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");

    await act(async () => { current.resolve(currentImage); });
    expect(screen.getByRole("img")).toHaveAttribute("src", currentImage);
  });

  it.each(["loading", "encoding"] as const)("keeps the existing placeholder on %s failure", async (stage) => {
    const { toDataURL } = mockQrModule();
    if (stage === "loading") {
      vi.doMock("qrcode", () => { throw new Error("QR chunk unavailable"); });
    } else {
      toDataURL.mockRejectedValue(new Error("QR encoding failed"));
    }
    const View = await loadView();
    render(<View {...props} connect={pending(firstUrl)} />);
    await act(async () => { await vi.dynamicImportSettled(); });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
