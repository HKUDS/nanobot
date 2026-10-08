import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AutomationDetailDialog, AutomationsSettings } from "@/components/settings/system/AutomationsSettings";
import { fetchAutomationChats } from "@/lib/api";
import { setAppLanguage } from "@/i18n";
import type { AutomationChatsPayload, ChatSummary, SessionAutomationJob } from "@/lib/types";

vi.mock("@/lib/api", () => ({ fetchAutomationChats: vi.fn() }));
const source = { id: "source", title: "My planning", channel: "websocket" };
const target = { id: "target", title: "Product team", channel: "telegram" };
const choices: AutomationChatsPayload = { revision: "rev-1", current: source, chats: [source, target] };
const job: SessionAutomationJob = {
  id: "daily", name: "Daily report", enabled: true, chat_binding_revision: "rev-1",
  schedule: { kind: "every", every_ms: 86400000 }, state: {},
  payload: { message: "Summarize the work." }, origin: { ...source, session_key: "websocket:source" },
};
const props = { open: true, locale: "en", actionKey: null, error: null,
  onOpenChange: vi.fn(), onAction: vi.fn(), onRequestEdit: vi.fn(), onRequestDelete: vi.fn() };
beforeEach(() => { vi.mocked(fetchAutomationChats).mockResolvedValue(choices); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function choose() {
  const control = await screen.findByRole("combobox", { name: "Run and reply in" });
  await waitFor(() => expect(control).toBeEnabled());
  fireEvent.keyDown(control, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name: /Product team/ }));
  await screen.findByRole("heading", { name: "Change chat" });
}

it("keeps the original route until acknowledgement and saves the reviewed prompt", async () => {
  let finish!: () => void;
  const save = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
  const user = userEvent.setup();
  const { rerender } = render(<AutomationDetailDialog {...props} job={job} onChangeChat={save} />);
  await choose();
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole("group", { name: "Now" })).toHaveTextContent("My planning");
  expect(screen.queryByRole("textbox", { name: "Task instructions" })).not.toBeInTheDocument();
  expect(screen.getByText(job.payload.message)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Edit instructions" }));
  expect(screen.getByRole("textbox", { name: "Task instructions" })).toHaveFocus();
  await user.clear(screen.getByRole("textbox", { name: "Task instructions" }));
  await user.type(screen.getByRole("textbox", { name: "Task instructions" }), "New instructions");
  await user.click(screen.getByRole("button", { name: "Save and change" }));
  expect(save).toHaveBeenCalledWith(job, { target_id: "target", revision: "rev-1", message: "New instructions" });
  expect(screen.getByRole("button", { name: "Changing…" })).toBeDisabled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  let refresh!: (value: AutomationChatsPayload) => void;
  vi.mocked(fetchAutomationChats).mockImplementation(() => new Promise(resolve => { refresh = resolve; }));
  await act(async () => {
    rerender(<AutomationDetailDialog {...props} job={{ ...job, chat_binding_revision: "rev-2" }} onChangeChat={save} />);
    finish();
  });
  expect(await screen.findByRole("status")).toHaveTextContent("Applies from the next run");
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("Product team");
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toBeDisabled();
  await act(async () => refresh({ ...choices, current: target, revision: "rev-2" }));
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveFocus();
  expect(props.onAction).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Change back to “My planning”" }));
  expect(save).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("group", { name: "Now" })).toHaveTextContent("Product team");
  expect(screen.getByRole("combobox", { name: "Change to" })).toHaveTextContent("My planning");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("Product team");
  await user.click(screen.getByRole("button", { name: "Change back to “My planning”" }));
  await user.click(screen.getByRole("button", { name: "Confirm change" }));
  expect(save.mock.calls[1]).toEqual([
    expect.objectContaining({ chat_binding_revision: "rev-2" }),
    { target_id: "source", revision: "rev-2", message: job.payload.message },
  ]);
  await act(async () => finish());
});

it("uses Chinese for the task menu and the change/cancel path", async () => {
  await setAppLanguage("zh-CN");
  const user = userEvent.setup();
  const save = vi.fn();
  render(<AutomationDetailDialog {...props} locale="zh-CN" job={job} onChangeChat={save} />);
  await user.click(screen.getByRole("button", { name: "更多操作" }));
  expect(screen.getByRole("menuitem", { name: "停用" })).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "删除" })).toBeInTheDocument();
  await user.keyboard("{Escape}");
  const picker = screen.getByRole("combobox", { name: "运行与回复" });
  await waitFor(() => expect(picker).toBeEnabled());
  fireEvent.keyDown(picker, { key: "ArrowDown" });
  await user.click(await screen.findByRole("option", { name: /Product team/ }));
  expect(screen.getByRole("heading", { name: "更换聊天" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "确认并更换" })).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "任务说明" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "修改说明" }));
  expect(screen.getByRole("textbox", { name: "任务说明" })).toHaveFocus();
  expect(screen.getByText("说明会与聊天更换一起保存。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存并更换" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.getByRole("heading", { name: "Daily report" })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "运行与回复" })).toHaveFocus();
  expect(save).not.toHaveBeenCalled();
});

it("keeps change-back available when another proposed change is cancelled", async () => {
  const user = userEvent.setup();
  const save = vi.fn().mockResolvedValue(undefined);
  const { rerender } = render(<AutomationDetailDialog {...props} job={job} onChangeChat={save} />);
  await choose();
  vi.mocked(fetchAutomationChats).mockResolvedValue({ ...choices, current: target, revision: "rev-2" });
  await user.click(screen.getByRole("button", { name: "Confirm change" }));
  rerender(<AutomationDetailDialog {...props} job={{ ...job, chat_binding_revision: "rev-2" }} onChangeChat={save} />);
  const changeBack = await screen.findByRole("button", { name: "Change back to “My planning”" });
  await waitFor(() => expect(changeBack).toBeEnabled());
  fireEvent.keyDown(screen.getByRole("combobox", { name: "Run and reply in" }), { key: "ArrowDown" });
  await user.click(await screen.findByRole("option", { name: /My planning/ }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("Product team");
  expect(screen.getByRole("button", { name: "Change back to “My planning”" })).toBeEnabled();
  expect(save).toHaveBeenCalledTimes(1);
});

it("removes an obsolete save confirmation after another client changes the chat", async () => {
  const user = userEvent.setup();
  const save = vi.fn().mockResolvedValue(undefined);
  const { rerender } = render(<AutomationDetailDialog {...props} job={job} onChangeChat={save} />);
  await choose();
  vi.mocked(fetchAutomationChats).mockResolvedValue({ ...choices, current: target, revision: "rev-2" });
  await user.click(screen.getByRole("button", { name: "Confirm change" }));
  rerender(<AutomationDetailDialog {...props} job={{ ...job, chat_binding_revision: "rev-2" }} onChangeChat={save} />);
  expect(await screen.findByRole("status")).toHaveTextContent("Product team");

  vi.mocked(fetchAutomationChats).mockResolvedValue({ ...choices, revision: "rev-3" });
  rerender(<AutomationDetailDialog {...props} job={{ ...job, chat_binding_revision: "rev-3" }} onChangeChat={save} />);
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Run and reply in" })).toBeEnabled());
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("My planning");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Change back/ })).not.toBeInTheDocument();
  expect(save).toHaveBeenCalledTimes(1);
});

it("cancels a chat change without saving the edited instructions", async () => {
  const user = userEvent.setup();
  const save = vi.fn();
  render(<AutomationDetailDialog {...props} job={job} onChangeChat={save} />);
  await choose();
  await user.click(screen.getByRole("button", { name: "Edit instructions" }));
  await user.clear(screen.getByRole("textbox", { name: "Task instructions" }));
  await user.type(screen.getByRole("textbox", { name: "Task instructions" }), "Discard this draft");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("My planning");
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveFocus();
  await choose();
  expect(screen.queryByRole("textbox", { name: "Task instructions" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Edit instructions" }));
  expect(screen.getByRole("textbox", { name: "Task instructions" })).toHaveValue("Summarize the work.");
});

it("keeps a rejected draft and its original revision across polling", async () => {
  const user = userEvent.setup();
  const save = vi.fn().mockRejectedValue(new Error("automation_chat_conflict"));
  const { rerender } = render(<AutomationDetailDialog {...props} job={job} onChangeChat={save} />);
  await choose();
  await user.click(screen.getByRole("button", { name: "Edit instructions" }));
  await user.type(screen.getByRole("textbox", { name: "Task instructions" }), " Reviewed");
  rerender(<AutomationDetailDialog {...props} job={{ ...job, chat_binding_revision: "rev-2" }} onChangeChat={save} />);
  await user.click(screen.getByRole("button", { name: "Save and change" }));
  expect(save.mock.calls[0][1].revision).toBe("rev-1");
  expect(await screen.findByRole("alert")).toHaveTextContent("draft is kept");
  expect(screen.getByRole("textbox", { name: "Task instructions" })).toHaveValue("Summarize the work. Reviewed");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("My planning");
});

it("does not send the new request to an old host and locks a pending task", async () => {
  const save = vi.fn();
  const { rerender } = render(<AutomationDetailDialog {...props} job={{ ...job, chat_binding_revision: undefined }} onChangeChat={save} />);
  expect(fetchAutomationChats).not.toHaveBeenCalled();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  rerender(<AutomationDetailDialog {...props} job={{ ...job, state: { pending: true } }} onChangeChat={save} />);
  expect(await screen.findByRole("combobox", { name: "Run and reply in" })).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
});

it("keeps the reviewed chat identity when refreshed choices no longer contain it", async () => {
  const user = userEvent.setup();
  const save = vi.fn();
  const { rerender } = render(<AutomationDetailDialog {...props} job={job} onChangeChat={save} />);
  await choose();
  await user.click(screen.getByRole("button", { name: "Edit instructions" }));
  await user.type(screen.getByRole("textbox", { name: "Task instructions" }), " Reviewed");
  vi.mocked(fetchAutomationChats).mockResolvedValue({
    revision: "rev-2", current: { ...source, title: "Renamed planning" }, chats: [source],
  });
  rerender(<AutomationDetailDialog {...props} job={{ ...job, chat_binding_revision: "rev-2" }} onChangeChat={save} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("no longer available");
  expect(screen.getByRole("combobox", { name: "Change to" })).toHaveTextContent("Product team");
  expect(screen.getByRole("group", { name: "Now" })).toHaveTextContent("My planning");
  expect(screen.getByRole("textbox", { name: "Task instructions" })).toHaveValue("Summarize the work. Reviewed");
  expect(screen.getByRole("button", { name: "Save and change" })).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("Renamed planning");
});

it("keeps the current chat visible when discovery fails and permits a retry", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchAutomationChats).mockRejectedValueOnce(new Error("offline"));
  render(<AutomationDetailDialog {...props} job={job} onChangeChat={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "Retry loading chats" }));
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Run and reply in" })).toBeEnabled());
  expect(fetchAutomationChats).toHaveBeenCalledTimes(2);
});

const webTarget = { ...target, channel: "websocket" };
const namedSessions: ChatSummary[] = [source, webTarget].map((chat) => ({
  key: `websocket:${chat.id}`, channel: "websocket", chatId: chat.id,
  title: chat.title, preview: "", createdAt: null, updatedAt: null,
  handle: { id: chat.id, name: chat.id === source.id ? "nime" : "jeno" },
}));

function NamedChats({ titles, onSave, task = job }: {
  titles: Record<string, string>;
  onSave: React.ComponentProps<typeof AutomationsSettings>["onChangeChat"];
  task?: SessionAutomationJob;
}) {
  return <AutomationsSettings payload={{ jobs: [task] }} sessions={namedSessions} titleOverrides={titles}
    loading={false} filter="all" actionKey={null} error={null} returnToDetailJob={task}
    onFilterChange={vi.fn()} onAction={vi.fn()} onRequestEdit={vi.fn()} onRequestDelete={vi.fn()}
    onChangeChat={onSave} />;
}

it("uses live sidebar names through loading, review, save and change-back without changing identity", async () => {
  const user = userEvent.setup();
  const save = vi.fn().mockResolvedValue(undefined);
  let resolve!: (value: AutomationChatsPayload) => void;
  vi.mocked(fetchAutomationChats).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  const titles = { "websocket:source": "推特大战场", "websocket:target": "产品讨论" };
  const { rerender } = render(<NamedChats titles={titles} onSave={save} />);
  expect(await screen.findByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("推特大战场");
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveAttribute("aria-busy", "true");
  await act(async () => resolve({ ...choices, chats: [source, webTarget] }));
  const control = screen.getByRole("combobox", { name: "Run and reply in" });
  expect(control).toHaveTextContent("推特大战场");
  expect(control).toHaveAttribute("aria-busy", "false");
  fireEvent.keyDown(control, { key: "ArrowDown" });
  expect(await screen.findByRole("option", { name: /推特大战场/ })).toBeInTheDocument();
  await user.click(screen.getByRole("option", { name: /产品讨论/ }));
  expect(screen.getByRole("group", { name: "Now" })).toHaveTextContent("推特大战场");
  const renamed = { "websocket:source": "工作笔记", "websocket:target": "研发讨论" };
  rerender(<NamedChats titles={renamed} onSave={save} />);
  expect(screen.getByRole("group", { name: "Now" })).toHaveTextContent("工作笔记");
  expect(screen.getByRole("combobox", { name: "Change to" })).toHaveTextContent("研发讨论");
  expect(save).not.toHaveBeenCalled();
  expect(fetchAutomationChats).toHaveBeenCalledTimes(1);
  vi.mocked(fetchAutomationChats).mockResolvedValue({ ...choices, current: webTarget, chats: [source, webTarget] });
  await user.click(screen.getByRole("button", { name: "Confirm change" }));
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ id: job.id }), {
    target_id: "target", revision: "rev-1", message: job.payload.message,
  });
  expect(await screen.findByRole("status")).toHaveTextContent("研发讨论");
  await user.click(await screen.findByRole("button", { name: "Change back to “工作笔记”" }));
  expect(screen.getByRole("group", { name: "Now" })).toHaveTextContent("研发讨论");
  expect(screen.getByRole("combobox", { name: "Change to" })).toHaveTextContent("工作笔记");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(save).toHaveBeenCalledTimes(1);
  expect(job.origin?.session_key).toBe("websocket:source");
  expect(choices.current?.title).toBe("My planning");
});

it("distinguishes identical renamed chats by handle and uses the original title when the override is removed", async () => {
  const user = userEvent.setup();
  const save = vi.fn();
  vi.mocked(fetchAutomationChats).mockResolvedValue({ ...choices, chats: [source, webTarget] });
  const { rerender } = render(<NamedChats titles={{ "websocket:source": "日报", "websocket:target": "日报" }} onSave={save} />);
  const control = await screen.findByRole("combobox", { name: "Run and reply in" });
  await waitFor(() => expect(control).toBeEnabled());
  expect(control).toHaveTextContent("日报 · @nime");
  fireEvent.keyDown(control, { key: "ArrowDown" });
  expect(await screen.findByRole("option", { name: /日报 · @nime/ })).toBeInTheDocument();
  await user.click(screen.getByRole("option", { name: /日报 · @jeno/ }));
  expect(screen.getByRole("combobox", { name: "Change to" })).toHaveTextContent("日报 · @jeno");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  rerender(<NamedChats titles={{}} onSave={save} />);
  expect(screen.getByRole("combobox", { name: "Run and reply in" })).toHaveTextContent("My planning");
  expect(save).not.toHaveBeenCalled();
});
