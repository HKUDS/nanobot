import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type { SessionMention, SlashCommand, WebUIIngressLimits } from "@/lib/types";
import { ComposerDraftStore } from "@/lib/composer-draft";
import { formatQuotedUserMessage } from "@/lib/user-message-quote";

vi.mock("@/lib/imageEncode", () => ({
  encodeImage: vi.fn(async () => ({
    ok: true,
    dataUrl: "data:image/png;base64,aW1hZ2U=",
    bytes: 5,
    normalized: false,
  })),
}));

const STORAGE_KEY = "nanobot.webui.composerQueuedGuidance.v1:chat-a";
const PNG = { dataUrl: "data:image/png;base64,aW1hZ2U=", kind: "image", name: "first.png" };
const DOCUMENT = { dataUrl: "data:text/plain;base64,aGVsbG8=", kind: "file", name: "second.txt" };

function limits(attachments: Partial<WebUIIngressLimits["attachments"]> = {}, maxTextBytes = 65536): WebUIIngressLimits {
  return {
    transport: { max_frame_bytes: 1024 * 1024, envelope_reserve_bytes: 1024 },
    message: { max_text_bytes: maxTextBytes },
    attachments: { max_count: 4, max_file_bytes: 6 * 1024 * 1024, max_total_bytes: 24 * 1024 * 1024, ...attachments },
  };
}

function enter(text: string): void {
  const input = screen.getByLabelText("Message input");
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

function mention(name: string): SessionMention {
  return { name, session_key: `websocket:${name}`, title: name };
}

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("merged waiting messages", () => {
  it("restores legacy entries as one message with all attachments, quotes and stable session targets", () => {
    const alpha = mention("alpha");
    const beta = mention("beta");
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { id: "first", text: "1 @alpha", images: [PNG], quotedContext: "first quote", sessionMentions: [alpha] },
      { id: "second", text: "2 @alpha @beta", images: [DOCUMENT], quotedContext: "second quote", sessionMentions: [alpha, beta] },
    ]));
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" isStreaming />);
    const pending = screen.getByRole("group", { name: "Waiting to send" });
    expect(within(pending).getAllByRole("button", { name: "Send now" })).toHaveLength(1);
    expect(pending).toHaveTextContent("first.png, second.txt");
    fireEvent.click(within(pending).getByRole("button", { name: "Send now" }));
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith("1 @alpha\n2 @alpha @beta", [
      expect.objectContaining({ media: { data_url: PNG.dataUrl, name: PNG.name }, preview: expect.objectContaining({ kind: "image" }) }),
      expect.objectContaining({ media: { data_url: DOCUMENT.dataUrl, name: DOCUMENT.name }, preview: expect.objectContaining({ kind: "file" }) }),
    ], {
      continueActiveTurn: true,
      quotedContext: "first quote\n\nsecond quote",
      sessionMentions: [alpha, beta],
    });
  });

  it("preserves merged text longer than the former per-entry storage truncation across remounts", () => {
    const onSend = vi.fn();
    const first = render(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" isStreaming />);
    const texts = ["a".repeat(3000), "b".repeat(3000)];
    texts.forEach(enter);
    first.unmount();
    render(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" isStreaming />);
    fireEvent.click(screen.getByRole("button", { name: "Send now" }));
    expect(onSend).toHaveBeenCalledWith(texts.join("\n"), undefined, { continueActiveTurn: true });
  });

  it("leaves an over-limit UTF-8 append in the input without changing the pending content", () => {
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} isStreaming ingressLimits={limits({}, 6)} />);
    enter("一");
    enter("二");
    expect(screen.getByLabelText("Message input")).toHaveValue("二");
    expect(screen.getByRole("group", { name: "Waiting to send" })).toHaveTextContent("一");
    expect(screen.getByText(/Message text is too large/)).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("counts the combined formatted quotes and separators against the text limit", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { id: "first", text: "1", quotedContext: "first quote" },
    ]));
    const bytes = new TextEncoder().encode(formatQuotedUserMessage("1\n2", "first quote\n\nsecond quote")).length;
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" isStreaming quotedContext="second quote" ingressLimits={limits({}, bytes - 1)} />);
    enter("2");
    expect(screen.getByLabelText("Message input")).toHaveValue("2");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)[0]).toMatchObject({ text: "1", quotedContext: "first quote" });
    expect(screen.getByText(/Message text is too large/)).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
  });

  it.each([
    { policy: { max_count: 1 }, error: "Max 1 attachments per message" },
    { policy: { max_total_bytes: 9 }, error: "Attachments are too large together" },
  ])("retains both pending and current attachments when merging exceeds $policy", async ({ policy, error }) => {
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:queued-test") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    const onSend = vi.fn();
    const view = render(<ThreadComposer onSend={onSend} isStreaming ingressLimits={limits(policy)} />);
    const picker = view.container.querySelector<HTMLInputElement>('input[type="file"]')!;
    for (const [index, name] of ["first.png", "second.png"].entries()) {
      fireEvent.change(picker, { target: { files: [new File(["image"], name, { type: "image/png" })] } });
      await waitFor(() => expect(screen.queryByLabelText("Encoding…")).not.toBeInTheDocument());
      enter(String(index + 1));
    }
    expect(screen.getByLabelText("Message input")).toHaveValue("2");
    expect(screen.getByTestId("composer-chip")).toHaveTextContent("second.png");
    expect(screen.getByRole("group", { name: "Waiting to send" })).toHaveTextContent("first.png");
    expect(screen.getByText(error, { exact: false })).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("lets users edit an oversized legacy aggregate without dropping excess attachments", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { id: "first", text: "1", images: [PNG] },
      { id: "second", text: "2", images: [DOCUMENT] },
    ]));
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" ingressLimits={limits({ max_count: 1 })} />);
    fireEvent.click(screen.getByRole("button", { name: "Send now" }));
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText("Max 1 attachments per message")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit message" }));
    expect(screen.getByLabelText("Message input")).toHaveValue("1\n2");
    expect(screen.getAllByTestId("composer-chip")).toHaveLength(2);
    fireEvent.click(within(screen.getAllByTestId("composer-chip")[0]).getByRole("button", { name: "Remove attachment" }));
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(onSend).toHaveBeenCalledWith("1\n2", [expect.objectContaining({ media: expect.objectContaining({ name: "second.txt" }) })], undefined);
  });

  it("keeps all edited legacy attachments through a topic round trip", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { id: "first", text: "1", images: [PNG] },
      { id: "second", text: "2", images: [DOCUMENT] },
    ]));
    const draftStore = new ComposerDraftStore();
    const props = { onSend: vi.fn(), pendingQueueKey: "chat-a", draftKey: "chat-a", draftStore, ingressLimits: limits({ max_count: 1 }) };
    const view = render(<ThreadComposer {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit message" }));
    view.unmount();
    render(<ThreadComposer {...props} />);
    await waitFor(() => expect(screen.queryByLabelText("Encoding…")).not.toBeInTheDocument());
    expect(screen.getAllByTestId("composer-chip")).toHaveLength(2);
    expect(draftStore.get("chat-a")?.files.map((file) => file.name)).toEqual(["first.png", "second.txt"]);
  });

  it("retains a merged rejected send after leaving the topic during upload", async () => {
    let reject!: (reason: Error) => void;
    const onSend = vi.fn(() => new Promise<boolean>((_, no) => { reject = no; }));
    const props = { onSend, pendingQueueKey: "chat-a", isStreaming: true };
    const view = render(<ThreadComposer {...props} />);
    enter("1");
    fireEvent.change(screen.getByLabelText("Message input"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    view.unmount();
    await act(async () => { reject(new Error("Upload failed")); });
    render(<ThreadComposer {...props} />);
    expect(screen.getByRole("group", { name: "Waiting to send" })).toHaveTextContent("1 2");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)[0]).toMatchObject({ text: "1\n2", autoPaused: true });
  });

  it("shares pending acceptance across remounts and clears only the accepted message", async () => {
    let accept!: (accepted: boolean) => void;
    const onSend = vi.fn(() => new Promise<boolean>((yes) => { accept = yes; }));
    const props = { onSend, pendingQueueKey: "chat-a", isStreaming: true };
    const view = render(<ThreadComposer {...props} />);
    enter("1"); enter("2");
    fireEvent.click(screen.getByRole("button", { name: "Send now" }));
    view.unmount();
    render(<ThreadComposer {...props} />);
    expect(screen.getByRole("button", { name: "Send now" })).toBeDisabled();
    await act(async () => { accept(true); });
    expect(screen.queryByRole("group", { name: "Waiting to send" })).not.toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("preserves the paused pending message when /stop is submitted with the send button", () => {
    const onStop = vi.fn();
    const onSend = vi.fn();
    const slashCommands: SlashCommand[] = [{ command: "/stop", title: "Stop", description: "Stop", icon: "square", lifecycle: "stop_active_turn", acceptsArgs: false }];
    const props = { onSend, onStop, pendingQueueKey: "chat-a", isStreaming: true, activeTurnId: "turn-a", slashCommands };
    const view = render(<ThreadComposer {...props} />);
    enter("1"); enter("2");
    fireEvent.change(screen.getByLabelText("Message input"), { target: { value: "/stop" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("group", { name: "Waiting to send" })).toHaveTextContent("1 2");
    view.rerender(<ThreadComposer {...props} isStreaming={false} completedTurnIds={["turn-a"]} />);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("keeps a new quote-only selection when editing the complete pending message", () => {
    const onQuotedContextChange = vi.fn();
    const props = { onSend: vi.fn(), isStreaming: true, onQuotedContextChange };
    const view = render(<ThreadComposer {...props} />);
    enter("1");
    view.rerender(<ThreadComposer {...props} quotedContext="new selection" />);
    fireEvent.click(screen.getByRole("button", { name: "Edit message" }));
    expect(screen.getByLabelText("Message input")).toHaveValue("1");
    expect(onQuotedContextChange).toHaveBeenLastCalledWith("new selection");
  });

  it("auto-sends attachment-only guidance after completion", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { id: "first", text: "", images: [PNG], autoAfterTurnId: "turn-a" },
      { id: "second", text: "", images: [DOCUMENT], autoAfterTurnId: "turn-a" },
    ]));
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" completedTurnIds={["turn-a"]} />);
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith("", [
      expect.objectContaining({ media: expect.objectContaining({ name: "first.png" }) }),
      expect.objectContaining({ media: expect.objectContaining({ name: "second.txt" }) }),
    ]);
  });

  it("retains a ninth session target in the input instead of silently dropping its reference", () => {
    const mentions = Array.from({ length: 8 }, (_, index) => mention(`target${index}`));
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { id: "first", text: mentions.map((item) => `@${item.name}`).join(" "), sessionMentions: mentions },
    ]));
    const onSend = vi.fn();
    render(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" isStreaming sessions={[{
      key: "websocket:target8", channel: "websocket", chatId: "target8", title: "Ninth chat", preview: "",
      createdAt: null, updatedAt: null, handle: { id: `handle_${"a".repeat(32)}`, name: "target8" },
    }]} />);
    fireEvent.change(screen.getByLabelText("Message input"), { target: { value: "@target8" } });
    fireEvent.mouseDown(screen.getByRole("option", { name: /target8/i }));
    fireEvent.keyDown(screen.getByLabelText("Message input"), { key: "Enter" });
    expect(screen.getByLabelText("Message input")).toHaveValue("@target8 ");
    expect(screen.getByText("A message can mention up to 8 chats")).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("keeps all legacy session targets after editing and refreshing an over-limit draft", () => {
    const targets = Array.from({ length: 9 }, (_, index) => mention(`target${index}`));
    const text = targets.map((item) => `@${item.name}`).join(" ");
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { id: "first", text: text.slice(0, text.lastIndexOf(" ")), sessionMentions: targets.slice(0, 8) },
      { id: "second", text: "@target8", sessionMentions: targets.slice(8) },
    ]));
    const onSend = vi.fn();
    const props = { onSend, pendingQueueKey: "chat-a", draftKey: "chat-a", persistDraft: true };
    const view = render(<ThreadComposer {...props} draftStore={new ComposerDraftStore()} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit message" }));
    view.unmount();
    const refreshed = new ComposerDraftStore();
    expect(refreshed.get("chat-a", true)?.sessionMentions).toEqual(targets);
    render(<ThreadComposer {...props} draftStore={refreshed} />);
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(screen.getByText("A message can mention up to 8 chats")).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("retains the whole message after a rejected immediate send", () => {
    const onSend = vi.fn(() => false);
    const view = render(<ThreadComposer onSend={onSend} isStreaming activeTurnId="turn-a" pendingQueueKey="chat-a" />);
    enter("1"); enter("2");
    fireEvent.keyDown(screen.getByLabelText("Message input"), { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("group", { name: "Waiting to send" })).toHaveTextContent("1 2");
    view.rerender(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" completedTurnIds={["turn-a"]} />);
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("does not automatically re-arm stopped content when another input is appended", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { id: "first", text: "stopped", autoPaused: true },
    ]));
    const onSend = vi.fn();
    const view = render(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" isStreaming activeTurnId="turn-a" />);
    enter("new input");
    view.rerender(<ThreadComposer onSend={onSend} pendingQueueKey="chat-a" completedTurnIds={["turn-a"]} />);
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Send now" }));
    expect(onSend).toHaveBeenCalledWith("stopped\nnew input");
  });
});
