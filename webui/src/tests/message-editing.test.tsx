import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { MessageEditingProvider } from "@/components/thread/MessageEditing";
import { ClientProvider } from "@/providers/ClientProvider";
import { NanobotClient } from "@/lib/nanobot-client";
import type { UIMessage } from "@/lib/types";
import { fetchLatestWebuiThread } from "@/lib/latest-thread-request";

vi.mock("@/lib/latest-thread-request", () => ({ fetchLatestWebuiThread: vi.fn() }));

const message: UIMessage = { id: "history-original", role: "user", content: "original question", turnId: "old-turn", createdAt: 1 };
const revision = "source-snapshot";
afterEach(() => vi.restoreAllMocks());

function setup(options: { busy?: boolean; revision?: string | null; messages?: UIMessage[]; onBegin?: (messageId: string) => void } = {}) {
  const client = new NanobotClient({ url: "ws://test", reconnect: false });
  vi.mocked(fetchLatestWebuiThread).mockResolvedValue({ schemaVersion: 1, projection: "events", events: [], source_revision: revision });
  const requests = vi.spyOn(client, "requestMutation").mockResolvedValue({ accepted: true });
  const send = vi.spyOn(client, "sendMessage");
  const tree = (busy = options.busy ?? false, messages = options.messages ?? [message]) => <ClientProvider client={client} token="test">
    <MessageEditingProvider chatId="same-chat" busy={busy} enabled sourceRevision={options.revision === undefined ? revision : options.revision} onBegin={options.onBegin}>
      <ThreadMessages editScope="websocket:same-chat" messages={messages} hiddenUserMessageCount={24} />
    </MessageEditingProvider>
    <textarea aria-label="Composer draft" defaultValue="untouched bottom draft" />
  </ClientProvider>;
  const view = render(tree());
  return { ...view, client, requests, send, tree };
}

function openMenu() {
  fireEvent.click(document.querySelector<HTMLElement>("[data-message-block-menu-trigger]")!);
  return screen.getByRole("button", { name: "Edit message" });
}

async function openEditor() {
  fireEvent.click(openMenu());
  const input = screen.getByRole("textbox", { name: "Edit message" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Resend" })).toBeEnabled());
  return input;
}

describe("message editing", () => {
  it("edits inside the original user bubble and keeps its draft separate; cancel is read-only", async () => {
    const onBegin = vi.fn();
    const { requests, send } = setup({ onBegin });
    const bubble = screen.getByText("original question");
    const edit = openMenu();
    const menu = edit.closest("[data-message-block-menu-actions]")!;
    expect(within(menu as HTMLElement).getByRole("button", { name: "Copy" })).toBeVisible();
    expect(edit.querySelector('svg[data-product-icon="edit"]')).toBeTruthy();
    fireEvent.click(edit);
    const input = screen.getByRole("textbox", { name: "Edit message" }) as HTMLTextAreaElement;
    expect(input).toHaveFocus();
    expect(input.selectionStart).toBe("original question".length);
    expect(input.selectionEnd).toBe("original question".length);
    expect(bubble).toContainElement(input);
    expect(screen.getByRole("button", { name: "Resend" })).toHaveAccessibleDescription("Replaces the conversation from here.");
    expect(onBegin).toHaveBeenCalledTimes(1);
    expect(onBegin).toHaveBeenCalledWith("history-original");
    expect(input).toHaveValue("original question");
    fireEvent.change(input, { target: { value: "unconfirmed change" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox", { name: "Edit message" })).not.toBeInTheDocument();
    expect(bubble).toBe(screen.getByText("original question"));
    expect(screen.getByRole("textbox", { name: "Composer draft" })).toHaveValue("untouched bottom draft");
    expect(requests).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });

  it("keeps typing and cancellation available when the source read fails", async () => {
    const { requests } = setup({ revision: null });
    let fail!: (error: Error) => void;
    vi.mocked(fetchLatestWebuiThread).mockReturnValueOnce(new Promise((_, reject) => { fail = reject; }));
    fireEvent.click(openMenu());
    const input = screen.getByRole("textbox", { name: "Edit message" });
    fireEvent.change(input, { target: { value: "keep my unconfirmed edit" } });
    const review = screen.getByRole("button", { name: "Review latest conversation" });
    fireEvent.click(review);
    expect(review).toBeDisabled();
    expect(review).toHaveAttribute("aria-busy", "true");
    await act(async () => fail(new Error("history read failed")));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load the latest message version");
    expect(input).toHaveValue("keep my unconfirmed edit");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("original question")).toBeVisible();
    expect(requests).not.toHaveBeenCalled();
  });

  it("does not authorize a review response the transcript has not displayed", async () => {
    const { requests } = setup({ revision: null });
    fireEvent.click(openMenu());
    const input = screen.getByRole("textbox", { name: "Edit message" });
    fireEvent.change(input, { target: { value: "keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Review latest conversation" }));
    // This isolated editor's read succeeds, but its rendered transcript stays unversioned.
    expect(await screen.findByRole("alert")).toHaveTextContent("conversation changed");
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    expect(input).toHaveValue("keep this draft");
    expect(requests).not.toHaveBeenCalled();
  });

  it("confirms exactly once against the displayed snapshot and stable input ID", async () => {
    const { requests, send } = setup({ messages: [{ ...message, inputId: "input-1" }] });
    const input = await openEditor();
    fireEvent.change(input, { target: { value: "edited question" } });
    let accept!: (value: unknown) => void;
    requests.mockReturnValueOnce(new Promise((resolve) => { accept = resolve; }));
    const confirm = screen.getByRole("button", { name: "Resend" });
    fireEvent.click(confirm);
    expect(confirm).toHaveAttribute("aria-busy", "true");
    fireEvent.click(confirm);
    expect(requests).toHaveBeenCalledTimes(1);
    expect(requests.mock.calls[0]).toEqual(["chat.fork", {
      mode: "replace", chat_id: "same-chat", text: "edited question", turn_id: expect.any(String),
      source: { revision, id: "input-1" },
    }]);
    expect(send).not.toHaveBeenCalled();
    await act(async () => accept({ accepted: true }));
    expect(screen.queryByRole("textbox", { name: "Edit message" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Composer draft" })).toHaveValue("untouched bottom draft");
  });

  it("retains input and the request turn identity after a preaccept failure", async () => {
    const { requests } = setup();
    const input = await openEditor();
    fireEvent.change(input, { target: { value: "keep this edit" } });
    requests.mockRejectedValueOnce(new Error("Connection lost"));
    fireEvent.click(screen.getByRole("button", { name: "Resend" }));
    await screen.findByRole("alert");
    expect(input).toHaveValue("keep this edit");
    expect(input).toHaveAccessibleDescription(screen.getByRole("alert").textContent!);
    const submitted = requests.mock.calls[0][1];
    requests.mockResolvedValueOnce({ accepted: true });
    fireEvent.click(screen.getByRole("button", { name: "Resend" }));
    await waitFor(() => expect(requests).toHaveBeenCalledTimes(2));
    expect(requests.mock.calls[1][1]).toEqual(submitted);
  });

  it("keeps the unconfirmed input usable when another browser removes its source row", async () => {
    const { rerender, tree, requests } = setup();
    fireEvent.change(await openEditor(), { target: { value: "local edit still needs a decision" } });
    const replacement: UIMessage = { ...message, id: "new-source", content: "another browser replaced the history", turnId: "another-turn" };
    rerender(tree(false, [replacement]));
    expect(screen.getByRole("textbox", { name: "Edit message" })).toHaveValue("local edit still needs a decision");
    expect(screen.getByRole("alert")).toHaveTextContent("copy your draft");
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Edit message" }), { key: "Enter", ctrlKey: true });
    expect(screen.getByRole("button", { name: "Resend" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox", { name: "Edit message" })).not.toBeInTheDocument();
    expect(screen.getByText(replacement.content)).toBeVisible();
    expect(requests).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Composer draft" })).toHaveValue("untouched bottom draft");
  });

  it("disables every old user edit while the conversation is executing", () => {
    const { requests } = setup({ busy: true });
    expect(openMenu()).toBeDisabled();
    expect(requests).not.toHaveBeenCalled();
  });

  it.each([
    { media: [{ type: "image", url: "/signed-old-image", name: "photo.png" }] },
    { cliApps: [{ name: "app" }] },
    { mcpPresets: [{ name: "mcp" }] },
    { sessionMentions: [{ name: "another", session_key: "websocket:another", title: "Another" }] },
    { content: "/new" },
    { content: "> [!QUOTE]\n> quote\n\nreply" },
  ])("does not silently drop unsupported original metadata: %j", (extra) => {
    setup({ messages: [{ ...message, ...extra } as UIMessage] });
    expect(openMenu()).toBeDisabled();
  });

  it.each(["/new", "! destructive command", "ask @another"])("does not turn edited text into a control or mention: %s", async (text) => {
    const { requests } = setup();
    const input = await openEditor();
    fireEvent.change(input, { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: "Resend" }));
    expect(screen.getByRole("alert")).toBeVisible();
    expect(requests).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "plain replacement" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("submits with Cmd/Ctrl+Enter unless composing", async () => {
    const { requests } = setup();
    const input = await openEditor();
    fireEvent.change(input, { target: { value: "shortcut edit" } });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true, isComposing: true });
    expect(requests).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(requests).toHaveBeenCalledWith("chat.fork", {
      mode: "replace", chat_id: "same-chat", text: "shortcut edit", turn_id: expect.any(String),
      source: { revision, id: "user:old-turn" },
    }));
  });
});
