import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type { EncodeResponse } from "@/lib/imageEncode";

const encodeImage = vi.fn<[File], Promise<EncodeResponse>>();

vi.mock("@/lib/imageEncode", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/imageEncode")>();
  return {
    ...actual,
    encodeImage: (file: File) => encodeImage(file),
  };
});

function pngFile(name = "a.png", size = 10) {
  return new File([new Uint8Array(size)], name, { type: "image/png" });
}

function resolveReady(file: File): EncodeResponse {
  return {
    id: "stub",
    ok: true,
    dataUrl: `data:image/png;base64,${btoa(file.name)}`,
    mimeType: "image/png",
    bytes: file.size,
    normalized: false,
  } as EncodeResponse;
}

beforeEach(() => {
  encodeImage.mockReset();
  let id = 0;
  // Tests never read the preview URL contents so a stable blob: stub is fine.
  if (!(globalThis.URL as unknown as { createObjectURL?: unknown }).createObjectURL) {
    (globalThis.URL as unknown as { createObjectURL: (b: Blob) => string }).createObjectURL =
      () => `blob:mock/${++id}`;
  }
  if (!(globalThis.URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL) {
    (globalThis.URL as unknown as { revokeObjectURL: (u: string) => void }).revokeObjectURL =
      () => {};
  }
});

describe("ThreadComposer — image attachments", () => {
  it("attaches a picked image and includes its data url on send", async () => {
    const file = pngFile("a.png");
    encodeImage.mockResolvedValueOnce(resolveReady(file));
    const onSend = vi.fn();

    render(<ThreadComposer onSend={onSend} />);

    const input = screen
      .getByLabelText(/message input/i)
      .closest("form")!
      .querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    await waitFor(() =>
      expect(screen.getByTestId("composer-chip")).toBeInTheDocument(),
    );

    const textarea = screen.getByLabelText(/message input/i);
    fireEvent.change(textarea, { target: { value: "hi" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(onSend).toHaveBeenCalledTimes(1);
    const [content, images] = onSend.mock.calls[0];
    expect(content).toBe("hi");
    expect(images).toHaveLength(1);
    expect(images[0].media.data_url).toContain("data:image/png;base64,");
    expect(images[0].media.name).toBe("a.png");
  });

  it("blocks send while an image is still encoding", async () => {
    const file = pngFile("slow.png");
    let resolveEncode: (r: EncodeResponse) => void = () => {};
    encodeImage.mockReturnValueOnce(
      new Promise((r) => {
        resolveEncode = r;
      }),
    );
    const onSend = vi.fn();

    render(<ThreadComposer onSend={onSend} />);

    const fileInput = screen
      .getByLabelText(/message input/i)
      .closest("form")!
      .querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [file] } });
    });

    const textarea = screen.getByLabelText(/message input/i);
    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();

    await act(async () => {
      resolveEncode(resolveReady(file));
      await Promise.resolve();
    });
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("rejects a non-image paste silently without adding a chip", async () => {
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} />);
    const textarea = screen.getByLabelText(/message input/i);

    fireEvent.paste(textarea, {
      clipboardData: {
        files: [],
        items: [
          {
            kind: "string",
            type: "text/plain",
            getAsFile: () => null,
          },
        ],
        types: ["text/plain"],
        getData: () => "some pasted text",
      },
    });

    expect(screen.queryByTestId("composer-chip")).toBeNull();
    expect(encodeImage).not.toHaveBeenCalled();
  });

  it("surfaces an inline error when encoding fails", async () => {
    const file = pngFile("bad.png");
    encodeImage.mockResolvedValueOnce({
      id: "stub",
      ok: false,
      reason: "decode_failed",
    } as EncodeResponse);
    const onSend = vi.fn();

    render(<ThreadComposer onSend={onSend} />);
    const fileInput = screen
      .getByLabelText(/message input/i)
      .closest("form")!
      .querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [file] } });
    });

    await waitFor(() => {
      const chip = screen.getByTestId("composer-chip");
      expect(chip.textContent ?? "").toMatch(/decode|image/i);
    });

    const textarea = screen.getByLabelText(/message input/i);
    fireEvent.change(textarea, { target: { value: "hi" } });
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });
});
