import {
  act,
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ComposerDraftStore } from "@/lib/composer-draft";
import type { EncodeResponse } from "@/lib/imageEncode";
import type { WebUIIngressLimits } from "@/lib/types";

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

function pdfFile(name = "report.pdf", size = 8) {
  return new File([new Uint8Array(size)], name, { type: "application/pdf" });
}

function csvFile(name = "report.csv", type = "application/vnd.ms-excel") {
  return new File(["name,value\nnanobot,1"], name, { type });
}

function resolveReady(file: File): Extract<EncodeResponse, { ok: true }> {
  return {
    id: "stub",
    ok: true,
    dataUrl: `data:image/png;base64,${btoa(file.name)}`,
    bytes: file.size,
    normalized: false,
  };
}

function ingressLimits({
  maxFrameBytes = 36 * 1024 * 1024,
  maxTextBytes = 64 * 1024,
  maxFileBytes = 6 * 1024 * 1024,
  maxTotalBytes = 24 * 1024 * 1024,
}: {
  maxFrameBytes?: number;
  maxTextBytes?: number;
  maxFileBytes?: number;
  maxTotalBytes?: number;
} = {}): WebUIIngressLimits {
  return {
    transport: {
      max_frame_bytes: maxFrameBytes,
      envelope_reserve_bytes: 64 * 1024,
    },
    message: { max_text_bytes: maxTextBytes },
    attachments: {
      max_count: 4,
      max_file_bytes: maxFileBytes,
      max_total_bytes: maxTotalBytes,
    },
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
  it("previews a picked image with size details on hover and includes its data url on send", async () => {
    const user = userEvent.setup();
    const file = pngFile("a.png", 100);
    encodeImage.mockResolvedValueOnce({ ...resolveReady(file), normalized: true, bytes: 50 });
    const onSend = vi.fn();

    render(<ThreadComposer onSend={onSend} />);

    const input = screen
      .getByLabelText(/message input/i)
      .closest("form")!
      .querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    expect(screen.getByRole("img", { name: "a.png" })).toHaveAttribute("src", expect.stringContaining("blob:"));
    await user.hover(screen.getByRole("button", { name: "a.png" }));
    const details = await screen.findByRole("tooltip");
    expect(details).toHaveTextContent("a.png");
    expect(details).toHaveTextContent("100 B → 50 B (auto)");
    expect(screen.getByRole("button", { name: "Remove attachment" })).toHaveAccessibleDescription("a.png");

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

  it("identifies same-type files through focus/tap details and removes only the chosen attachment", async () => {
    const user = userEvent.setup();
    const first = new File(['{"theme":"light"}'], "render-config.json", { type: "application/json" });
    const second = new File(['{"theme":"dark"}'], "another-config.json", { type: "application/json" });
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} />);
    const textarea = screen.getByLabelText(/message input/i);
    const input = textarea.closest("form")!.querySelector('input[type="file"]')!;
    await act(async () => fireEvent.change(input, { target: { files: [first, second] } }));
    const cards = screen.getAllByTestId("composer-chip");
    expect(cards.map((card) => card.textContent)).toEqual(["JSON", "JSON"]);
    const firstInfo = within(cards[0]).getByRole("button", { name: first.name });
    act(() => firstInfo.focus());
    expect(await screen.findByRole("tooltip")).toHaveTextContent(first.name);
    expect(screen.getByRole("tooltip")).toHaveTextContent(`${first.size} B`);
    await user.keyboard("{Escape}");
    await user.click(within(cards[1]).getByRole("button", { name: second.name }));
    expect(await screen.findByRole("dialog", { name: second.name })).toHaveTextContent(second.name);
    await user.keyboard("{Escape}");
    await user.click(within(cards[1]).getByRole("button", { name: "Remove attachment" }));
    expect(screen.getAllByTestId("composer-chip")).toHaveLength(1);
    expect(screen.getByRole("button", { name: first.name })).toBeVisible();
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend.mock.calls[0][1].map((attachment: { media: { name: string } }) => attachment.media.name)).toEqual([first.name]);
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
      expect(screen.getByTestId("composer-chip")).toHaveTextContent("PDF"),
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
        expect(screen.getByRole("button", { name: "report.csv" })).toHaveAccessibleDescription(expect.stringContaining("B")),
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

  it("rejects an oversized document before adding a chip", async () => {
    const file = pdfFile("oversized.pdf", 6 * 1024 * 1024 + 1);

    render(<ThreadComposer onSend={vi.fn()} />);

    const input = screen
      .getByLabelText(/message input/i)
      .closest("form")!
      .querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    expect(screen.getByRole("alert")).toHaveTextContent("File is too large");
    expect(screen.queryByTestId("composer-chip")).not.toBeInTheDocument();
  });

  it("does not count binary attachments against the WebSocket frame limit", async () => {
    const first = pdfFile("first.pdf", 400 * 1024);
    const second = pdfFile("second.pdf", 400 * 1024);

    render(
      <ThreadComposer
        onSend={vi.fn()}
        ingressLimits={ingressLimits({ maxFrameBytes: 1024 * 1024 })}
      />,
    );

    const input = screen
      .getByLabelText(/message input/i)
      .closest("form")!
      .querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
      fireEvent.change(input, { target: { files: [first, second] } });
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("composer-chip")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "first.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "second.pdf" })).toBeInTheDocument();
  });

  it("enforces the decoded attachment-total policy independently", async () => {
    const first = pdfFile("first.pdf", 400 * 1024);
    const second = pdfFile("second.pdf", 400 * 1024);

    render(
      <ThreadComposer
        onSend={vi.fn()}
        ingressLimits={ingressLimits({ maxTotalBytes: 700 * 1024 })}
      />,
    );

    const input = screen
      .getByLabelText(/message input/i)
      .closest("form")!
      .querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
      fireEvent.change(input, { target: { files: [first, second] } });
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Attachments are too large together",
    );
    expect(screen.getAllByTestId("composer-chip")).toHaveLength(1);
  });

  it("enforces the text-byte policy without changing attachment limits", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        ingressLimits={ingressLimits({ maxTextBytes: 4 })}
      />,
    );

    const textarea = screen.getByLabelText(/message input/i);
    fireEvent.change(textarea, { target: { value: "你好" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Message text is too large (max 4 B)",
    );
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
      expect(screen.getByRole("button", { name: "pasted.pdf" })).toBeInTheDocument(),
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
      expect(screen.getByRole("button", { name: "dropped.pdf" })).toBeInTheDocument(),
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

    expect(screen.getByRole("img", { name: "slow.png" })).toBeInTheDocument();
    expect(screen.getByLabelText("Encoding…")).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Remove attachment" }));
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("hi", undefined, undefined);
  });
});


describe("local attachment paths and video ingress", () => {
  const local = { path: "C:\\project\\my clip.mp4", name: "my clip.mp4", size: 12,
    mime: "video/mp4", kind: "video" as const, url: "/api/media/sig/local" };

  it("leaves a path pasted into a bang command as Shell text", () => {
    const inspect = vi.fn().mockResolvedValue(local);
    render(<ThreadComposer onSend={vi.fn()} onInspectAttachment={inspect} />);
    const input = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "!cat " } });
    input.setSelectionRange(5, 5);
    const event = createEvent.paste(input, { clipboardData: { items: [], getData: () => local.path } });
    fireEvent(input, event);
    expect(event.defaultPrevented).toBe(false);
    expect(inspect).not.toHaveBeenCalled();
  });

  it("keeps a pending path literal when its draft becomes a bang command", async () => {
    let complete!: (attachment: typeof local) => void;
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} onInspectAttachment={() => new Promise((resolve) => { complete = resolve; })} />);
    const input = screen.getByLabelText(/message input/i);
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => local.path } });
    fireEvent.change(input, { target: { value: `!${local.path}` } });
    await act(async () => complete(local));
    expect(input).toHaveValue(`!${local.path}`);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith(`!${local.path}`, undefined, { sideChannel: true, userShell: true });
  });

  it("confirms a large pasted video path and sends only the borrowed reference", async () => {
    const inspect = vi.fn().mockResolvedValue({ ...local, size: 64 * 1024 * 1024 + 1 });
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} onInspectAttachment={inspect} />);
    const input = screen.getByLabelText(/message input/i);
    fireEvent.change(input, { target: { value: "keep this " } });
    (input as HTMLTextAreaElement).setSelectionRange(10, 10);
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => '"C:\\project\\my clip.mp4"' } });
    await waitFor(() => expect(screen.getByRole("button", { name: "my clip.mp4" })).toBeInTheDocument());
    expect(input).toHaveValue("keep this ");
    expect(inspect).toHaveBeenCalledWith(local.path);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend.mock.calls[0][1][0].media).toEqual({ path: local.path, name: local.name });
  });

  it.each(["append", "prepend"])("keeps %s text written while the pasted path is being checked", async (edit) => {
    let complete!: (attachment: typeof local) => void;
    const inspect = vi.fn(() => new Promise<typeof local>((resolve) => { complete = resolve; }));
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} onInspectAttachment={inspect} />);
    const input = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => local.path } });
    const typed = edit === "append" ? `${local.path} describe it` : `请看 ${local.path}`;
    fireEvent.change(input, { target: { value: typed, selectionStart: typed.length } });
    await act(async () => complete(local));
    await screen.findByTestId("composer-chip");
    expect(input).toHaveValue(edit === "append" ? " describe it" : "请看 ");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend.mock.calls[0][0]).toBe(edit === "append" ? "describe it" : "请看");
    expect(onSend.mock.calls[0][1][0].media).toEqual({ path: local.path, name: local.name });
  });

  it.each(["edit", "remove"])("does not attach a path after the user chooses to %s it during inspection", async (edit) => {
    let complete!: (attachment: typeof local) => void;
    render(<ThreadComposer onSend={vi.fn()} onInspectAttachment={() => new Promise((resolve) => { complete = resolve; })} />);
    const input = screen.getByLabelText(/message input/i);
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => local.path } });
    const typed = edit === "edit" ? local.path.replace("clip", "other") : "keep my new text";
    fireEvent.change(input, { target: { value: typed } });
    await act(async () => complete(local));
    expect(screen.queryByTestId("composer-chip")).not.toBeInTheDocument();
    expect(input).toHaveValue(typed);
    expect(screen.getByRole("button", { name: /send message/i })).toBeEnabled();
  });

  it("does not steal toolbar focus when a pending path is confirmed", async () => {
    let complete!: (attachment: typeof local) => void;
    render(<ThreadComposer onSend={vi.fn()} onInspectAttachment={() => new Promise((resolve) => { complete = resolve; })} />);
    const input = screen.getByLabelText(/message input/i);
    await waitFor(() => expect(input).toHaveFocus());
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => local.path } });
    const attach = screen.getByRole("button", { name: /attach/i });
    attach.focus();
    expect(attach).toHaveFocus();
    await act(async () => complete(local));
    await screen.findByTestId("composer-chip");
    expect(attach).toHaveFocus();
  });

  it("lets an IME composition finish before converting its pasted path", async () => {
    let complete!: (attachment: typeof local) => void;
    render(<ThreadComposer onSend={vi.fn()} onInspectAttachment={() => new Promise((resolve) => { complete = resolve; })} />);
    const input = screen.getByLabelText(/message input/i);
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => local.path } });
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: `${local.path}你` } });
    await act(async () => complete(local));
    expect(screen.queryByTestId("composer-chip")).not.toBeInTheDocument();
    fireEvent.compositionEnd(input);
    await screen.findByTestId("composer-chip");
    expect(input).toHaveValue("你");
  });

  it("ignores an inspection reply after the workspace scope changes", async () => {
    let complete!: (attachment: typeof local) => void;
    const inspect = () => new Promise<typeof local>((resolve) => { complete = resolve; });
    const view = render(<ThreadComposer onSend={vi.fn()} onInspectAttachment={inspect} workspaceScope={{ project_path: "C:\\project", access_mode: "full" }} />);
    const input = screen.getByLabelText(/message input/i);
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => local.path } });
    view.rerender(<ThreadComposer onSend={vi.fn()} onInspectAttachment={inspect} workspaceScope={{ project_path: "C:\\project", access_mode: "restricted" }} />);
    await act(async () => complete(local));
    expect(screen.queryByTestId("composer-chip")).not.toBeInTheDocument();
    expect(input).toHaveValue(local.path);
    expect(screen.getByRole("button", { name: /send message/i })).toBeEnabled();
  });

  it("keeps mixed local and uploaded attachment order across draft remounts", async () => {
    encodeImage.mockImplementation(async (file) => resolveReady(file));
    const firstLocal = { ...local, path: "C:\\project\\first.png", name: "first.png", kind: "image" as const, mime: "image/png" };
    const lastLocal = { ...firstLocal, path: "C:\\project\\last.png", name: "last.png" };
    const inspect = vi.fn().mockResolvedValueOnce(firstLocal).mockResolvedValueOnce(lastLocal);
    const store = new ComposerDraftStore();
    const onSend = vi.fn();
    const composer = () => <ThreadComposer draftKey="mixed-order" draftStore={store} onSend={onSend} onInspectAttachment={inspect} />;
    const view = render(composer());
    const input = screen.getByLabelText(/message input/i);
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => firstLocal.path } });
    await screen.findByRole("img", { name: firstLocal.name });
    fireEvent.change(input.closest("form")!.querySelector('input[type="file"]')!, { target: { files: [pngFile("middle.png")] } });
    await screen.findByRole("img", { name: "middle.png" });
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => lastLocal.path } });
    await screen.findByRole("img", { name: lastLocal.name });
    fireEvent.change(input, { target: { value: "compare the first, second and third images" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /send message/i })).toBeEnabled());
    expect(screen.getAllByRole("img").map((image) => image.getAttribute("alt"))).toEqual([
      "first.png", "middle.png", "last.png",
    ]);
    view.unmount();
    render(composer());
    await waitFor(() => expect(screen.getByRole("button", { name: /send message/i })).toBeEnabled());
    fireEvent.keyDown(screen.getByLabelText(/message input/i), { key: "Enter" });
    expect(onSend.mock.calls[0][1].map((item: { media: { name: string } }) => item.media.name)).toEqual([
      "first.png", "middle.png", "last.png",
    ]);
  });

  it.each([
    [404, "file not found"],
    [403, "file is outside the current workspace"],
  ] as const)("retains pasted text on %s, showing only actionable errors", async (status, message) => {
    const inspect = vi.fn().mockRejectedValue(Object.assign(new Error(message), { status }));
    render(<ThreadComposer onSend={vi.fn()} onInspectAttachment={inspect} />);
    const input = screen.getByLabelText(/message input/i);
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => "./missing.mp4" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /send message/i })).toBeEnabled());
    expect(input).toHaveValue("./missing.mp4");
    if (status === 404) expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    else expect(screen.getByRole("alert")).toHaveTextContent(message);
    for (const text of ["some pasted text", "look at ./missing.mp4 please", "https://host/clip.mp4", "const path = './clip.mp4'", "line one\n./clip.mp4"]) {
      fireEvent.paste(input, {
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
          getData: () => text,
        },
      });
    }
    expect(inspect).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("composer-chip")).not.toBeInTheDocument();
    expect(encodeImage).not.toHaveBeenCalled();
  });

  it("does not charge large local documents against a picked document's upload budget", async () => {
    const onSend = vi.fn();
    const document = { ...local, path: "C:\\project\\large.pdf", name: "large.pdf", mime: "application/pdf", kind: "file" as const, size: 64 * 1024 * 1024 + 1 };
    render(<ThreadComposer onSend={onSend} onInspectAttachment={vi.fn().mockResolvedValue(document)} ingressLimits={ingressLimits({ maxFileBytes: 8, maxTotalBytes: 8 })} />);
    const input = screen.getByLabelText(/message input/i);
    fireEvent.paste(input, { clipboardData: { items: [], getData: () => document.path } });
    await screen.findByRole("button", { name: document.name });
    const picker = input.closest("form")!.querySelector('input[type="file"]')!;
    fireEvent.change(picker, { target: { files: [pdfFile("upload.pdf", 8)] } });
    await waitFor(() => expect(screen.getByRole("button", { name: /send message/i })).toBeEnabled());
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("", [
      expect.objectContaining({ media: { path: document.path, name: document.name } }),
      expect.objectContaining({ media: expect.objectContaining({ name: "upload.pdf", data_url: expect.any(String) }) }),
    ], undefined);
  });

  it("explains the size and limit of a rejected browser video without losing the draft", () => {
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} />);
    const input = screen.getByLabelText(/message input/i);
    fireEvent.change(input, { target: { value: "keep this text" } });
    const file = new File([new Uint8Array(21 * 1024 * 1024)], "large.mp4", { type: "video/mp4" });
    fireEvent.change(input.closest("form")!.querySelector('input[type="file"]')!, { target: { files: [file] } });
    expect(screen.getByRole("alert")).toHaveTextContent("21.0 MiB");
    expect(screen.getByRole("alert")).toHaveTextContent("20.0 MiB");
    expect(input).toHaveValue("keep this text");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("uploads picked video bytes with the existing independent video size/count allowance", async () => {
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} ingressLimits={ingressLimits({ maxFileBytes: 3 })} />);
    const input = screen.getByLabelText(/message input/i);
    const picker = input.closest("form")!.querySelector('input[type="file"]')!;
    fireEvent.change(picker, { target: { files: [new File(["movie"], "clip.mov", { type: "" })] } });
    await waitFor(() => expect(screen.getByRole("button", { name: /send message/i })).toBeEnabled());
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend.mock.calls[0][1][0].media).toEqual({ data_url: `data:video/quicktime;base64,${btoa("movie")}`, name: "clip.mov" });
  });
});
