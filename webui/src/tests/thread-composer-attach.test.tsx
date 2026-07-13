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

const encodeImage = vi.fn<(file: File) => Promise<EncodeResponse>>();

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

function pdfFile(name = "report.pdf") {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

function csvFile(name = "report.csv", type = "application/vnd.ms-excel") {
  return new File(["name,value\nnanobot,1"], name, { type });
}

function resolveReady(file: File): EncodeResponse {
  return {
    id: "stub",
    ok: true,
    dataUrl: `data:image/png;base64,${btoa(file.name)}`,
    mime: "image/png",
    bytes: file.size,
    origBytes: file.size,
    normalized: false,
  };
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

describe("ThreadComposer — attachments", () => {
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

  it("attaches a picked PDF and includes its data url on send", async () => {
    const file = pdfFile();
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
      expect(screen.getByTestId("composer-chip")).toHaveTextContent("report.pdf"),
    );

    const textarea = screen.getByLabelText(/message input/i);
    fireEvent.change(textarea, { target: { value: "summarize" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(encodeImage).not.toHaveBeenCalled();
    const [content, attachments] = onSend.mock.calls[0];
    expect(content).toBe("summarize");
    expect(attachments).toHaveLength(1);
    expect(attachments[0].media.data_url).toContain("data:application/pdf;base64,");
    expect(attachments[0].media.name).toBe("report.pdf");
    expect(attachments[0].preview.kind).toBe("file");
  });

  it.each(["application/vnd.ms-excel", "image/png"])(
    "normalizes document MIME from the file extension when the browser reports %s",
    async (browserMime) => {
      const file = csvFile("report.csv", browserMime);
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
        expect(screen.getByTestId("composer-chip")).toHaveTextContent("report.csv"),
      );

      const textarea = screen.getByLabelText(/message input/i);
      fireEvent.change(textarea, { target: { value: "summarize" } });
      fireEvent.keyDown(textarea, { key: "Enter" });

      const [, attachments] = onSend.mock.calls[0];
      expect(attachments[0].media.data_url).toMatch(/^data:text\/csv;base64,/);
      expect(encodeImage).not.toHaveBeenCalled();
    },
  );

  it("rejects empty attachments before sending them to the gateway", async () => {
    const file = new File([], "empty.csv", { type: "application/vnd.ms-excel" });
    const onSend = vi.fn();

    render(<ThreadComposer onSend={onSend} />);

    const input = screen
      .getByLabelText(/message input/i)
      .closest("form")!
      .querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    expect(screen.getByText("Empty files cannot be attached")).toBeInTheDocument();
    expect(screen.queryByTestId("composer-chip")).not.toBeInTheDocument();
    expect(encodeImage).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("accepts supported documents from paste and drop", async () => {
    const pasted = pdfFile("pasted.pdf");
    const dropped = pdfFile("dropped.pdf");
    const onSend = vi.fn();

    render(<ThreadComposer onSend={onSend} />);

    const textarea = screen.getByLabelText(/message input/i);
    const form = textarea.closest("form")!;

    await act(async () => {
      fireEvent.paste(textarea, {
        clipboardData: {
          files: [pasted],
          items: [{
            kind: "file",
            type: pasted.type,
            getAsFile: () => pasted,
          }],
          types: ["Files"],
          getData: () => "",
        },
      });
    });

    await waitFor(() =>
      expect(screen.getByText("pasted.pdf")).toBeInTheDocument(),
    );

    await act(async () => {
      fireEvent.drop(form, {
        dataTransfer: {
          files: [dropped],
          items: [],
          types: ["Files"],
          dropEffect: "copy",
        },
      });
    });

    await waitFor(() =>
      expect(screen.getByText("dropped.pdf")).toBeInTheDocument(),
    );
    expect(screen.getAllByTestId("composer-chip")).toHaveLength(2);
    expect(encodeImage).not.toHaveBeenCalled();
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

  it("keeps a plain-text paste untouched without adding a chip", async () => {
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
