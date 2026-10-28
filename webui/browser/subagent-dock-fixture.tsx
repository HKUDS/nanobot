import { useEffect, useRef, useState } from "react";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { settings } from "@/dev/gallery/settings";
import { setAppLanguage } from "@/i18n";
import { normalizeLocale } from "@/i18n/config";
import { ClientProvider } from "@/providers/ClientProvider";
import type { SubagentTaskSnapshot, ThreadProjectionEvent } from "@/lib/types";
import { createStreamClient } from "@/tests/stream-client";

const { client, receive } = createStreamClient();
const chatId = "dock-preview";
const turnId = "preview-turn";
const createdAt = Date.now() / 1000;
let streamLength = 0;
let inputNumber = 0;
const saveTasks = new URLSearchParams(location.search).has("saved");
const taskStorageKey = "fixture.subagent-dock.tasks";
const taskLabels = new URLSearchParams(location.search).has("long-labels")
  ? ["核对多轮任务完成后的归档位置、长标题换行与独立详情入口", "Review_the_responsive_subtask_panel_and_keyboard_focus_without_interrupting_running_work", "整理交互建议"]
  : ["检查项目实现", "核对回归测试", "整理交互建议"];
const tasks: SubagentTaskSnapshot[] = taskLabels.map((label, index) => ({
  task_id: `preview-${index}`, revision: 1, label, task_description: `这是虚构的演示任务：${label}。不会读取项目或调用模型。`,
  origin_turn_id: turnId, origin_message_id: "preview-prompt", created_at: createdAt + index, completed_at: null,
  state: index === 2 ? "queued" : "running", phase: "awaiting_model", elapsed_seconds: 20 + index * 3, iteration: 1,
  tool_events: index === 0 ? [{ name: "read_file", status: "running" }] : index === 1 ? [{ name: "exec", status: "running" }] : [],
  usage: null, receipts: {}, result: null, partial: false, stop_reason: null, error: null,
}));
const history: ThreadProjectionEvent[] = [
  { event: "user_message", chat_id: chatId, projection_id: "preview-prompt", turn_id: turnId, text: "请让三个子任务分别检查实现、测试和交互。主对话继续讨论，不要等它们全部结束。", starts_turn: true },
  { event: "message", chat_id: chatId, projection_id: "preview-answer", turn_id: turnId,
    text: "已经安排。你可以继续在这里交流，子任务会独立推进。\n\n**随时查看，不必回翻聊天**\n\n输入区上方的子任务入口会留在原位。点开可以查看每一路任务的状态、真实工具活动和最终结果。\n\n" + "主对话仍然可以正常输出和滚动。任务列表与消息区分别滚动，展开详情也不会取消正在执行的任务。\n\n".repeat(12) },
];

function updateTask(index: number, patch: Partial<SubagentTaskSnapshot>) {
  const previous = tasks[index];
  const next = { ...previous, ...patch, revision: (previous.revision ?? 0) + 1 };
  tasks[index] = next;
  if (saveTasks) sessionStorage.setItem(taskStorageKey, JSON.stringify(tasks));
  receive({ event: "subagent_task", chat_id: chatId, task: next });
}

export function installSubagentDockApi() {
  const stored = saveTasks ? sessionStorage.getItem(taskStorageKey) : null;
  if (stored) tasks.splice(0, tasks.length, ...JSON.parse(stored) as SubagentTaskSnapshot[]);
  else if (new URLSearchParams(location.search).has("archived")) {
    tasks.forEach((task, index) => {
      tasks[index] = { ...task, state: "done", phase: "done", elapsed_seconds: [9, 89, 1234][index], completed_at: createdAt + 30, tool_events: [] };
    });
  } else if (new URLSearchParams(location.search).has("past")) {
    tasks.push(...Array.from({ length: 40 }, (_, index) => ({
      ...tasks[0], task_id: `past-${index}`, label: `Past check ${index}`, state: "done" as const,
      origin_message_id: null, origin_turn_id: "past-turn", created_at: createdAt - 100 + index,
      completed_at: createdAt - 50 + index, tool_events: [], result: "Saved past result",
    })));
  }
  const original = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return original(input, init);
    if (url.pathname === "/api/settings") return Response.json(settings);
    if (url.pathname === "/api/commands") return Response.json({ commands: [
      { command: "/history", title: "Chat history", description: "Show recent messages", icon: "history", lifecycle: "side_channel", accepts_args: true },
    ] });
    if (url.pathname.endsWith("/subagents")) return Response.json({ tasks: url.pathname.includes(encodeURIComponent(`websocket:${chatId}`)) ? tasks : [] });
    if (url.pathname.includes("/subagents/") && url.pathname.endsWith("/webui-thread")) {
      const task = tasks.find(item => url.pathname.includes(`/${item.task_id}/`))!;
      return Response.json({ schemaVersion: 3, projection: "events", events: [
        { event: "user_message", chat_id: task.task_id, projection_id: `${task.task_id}-prompt`, turn_id: "child", starts_turn: true, text: task.task_description },
        { event: "message", chat_id: task.task_id, projection_id: `${task.task_id}-answer`, turn_id: "child", text: task.result ?? "正在检查。这是隔离的演示内容，没有真实文件操作。" },
      ] });
    }
    if (url.pathname.includes("/webui-thread")) return Response.json({ schemaVersion: 3, projection: "events", events: history });
    return Response.json({}, { status: 404 });
  };
  client.requestMutation = async <T,>(action: string, payload?: Record<string, unknown>): Promise<T> => {
    if (action !== "subagent.cancel") throw new Error(`Unexpected preview mutation: ${action}`);
    const index = tasks.findIndex(task => task.task_id === payload?.task_id);
    updateTask(index, { state: "cancelled", phase: "cancelled", tool_events: [], completed_at: Date.now() / 1000 });
    return tasks[index] as T;
  };
}

export function SubagentDockFixture({ parameters }: { parameters: URLSearchParams }) {
  const [topic, setTopic] = useState(chatId);
  const [active, setActive] = useState(true);
  const [dark, setDark] = useState(parameters.has("dark"));
  const [portal, setPortal] = useState<HTMLDivElement | null>(null);
  const timers = useRef<number[]>([]);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    void setAppLanguage(normalizeLocale(parameters.get("lang")));
  }, [dark, parameters]);
  useEffect(() => () => timers.current.forEach(window.clearTimeout), []);
  const finish = () => tasks.forEach((task, index) => {
    if (task.state === "running" || task.state === "queued") updateTask(index, {
      state: "done", phase: "done", tool_events: [], completed_at: Date.now() / 1000,
      result: index === 0 && parameters.has("image-result") ? "## Image result\n\n![Result image](https://example.com/dock-result.svg)"
        : index === 0 && parameters.has("markdown-result")
        ? "## 天气结果\n\n**北京**：约 **10°C**，有小雨。\n\n```text\nchecked_at: 2026-10-25T20:52:00+08:00\n```\n\n" + "这是完整的多行查询结果，保留原始段落、文字样式和详细说明，阅读时可以滚动任务列表。".repeat(30)
          + "\n\n- **南京**：约 18°C，有雾。\n- **天津**：约 12°C，多云。\n\n[天气来源](https://example.com/weather)\n\n最后一条完整结论：以上结果均可继续核对。"
        : ["已核对面板的位置与滚动边界。", "定向检查已完成，保留详情与单任务停止。", "建议让任务入口始终留在输入区附近。"][index % 3],
    });
  });
  const growReply = () => {
    streamLength += 12;
    const replyTurn = `long-reply-${streamLength}`;
    receive({ event: "goal_status", chat_id: chatId, turn_id: replyTurn, status: "running", started_at: Date.now() / 1000 });
    receive({ event: "delta", chat_id: chatId, turn_id: replyTurn, stream_id: "reply", text: "主助手继续输出较长的说明，子任务入口保持在输入框上方。\n\n".repeat(streamLength) });
    receive({ event: "stream_end", chat_id: chatId, turn_id: replyTurn, stream_id: "reply" });
    receive({ event: "turn_end", chat_id: chatId, turn_id: replyTurn });
  };
  return <ClientProvider client={client} token="fixture" webuiCapabilities={["webui.core.v1", "webui.subagents.v1", "webui.subagents.events.v1", "webui.subagents.history.v1"]}>
    <main className="thread-workspace flex min-w-0 flex-col overflow-hidden bg-background text-foreground" style={{ height: "var(--app-viewport-height, 100dvh)" }}>
      <nav aria-label="Preview controls" className="flex shrink-0 items-center gap-4 overflow-x-auto whitespace-nowrap border-b px-4 py-2 text-xs text-muted-foreground">
        <span>虚构任务预览</span>
        <button onClick={() => {
          growReply();
          updateTask(2, { state: "running", tool_events: [{ name: "web_fetch", status: "running" }] });
          timers.current.push(window.setTimeout(() => updateTask(0, { state: "done", tool_events: [], completed_at: Date.now() / 1000, result: "入口不会随主回复滚走。" }), 3000));
          timers.current.push(window.setTimeout(finish, 7000));
        }}>模拟运行</button>
        <button onClick={growReply}>追加长回复</button>
        <button onClick={() => updateTask(0, { state: "done", phase: "done", tool_events: [], completed_at: Date.now() / 1000, result: "第一项已完成并归档。" })}>完成第一项</button>
        <button onClick={finish}>全部完成</button>
        <button onClick={() => {
          inputNumber += 1;
          receive({ event: "user_message", chat_id: chatId, turn_id: `next-turn-${inputNumber}`, turn_seq: 1, starts_turn: true, text: `下一轮消息 ${inputNumber}` });
        }}>新一轮消息</button>
        <button onClick={() => updateTask(1, { state: "error", error: "演示：测试执行失败，请打开详情检查。", tool_events: [], completed_at: Date.now() / 1000 })}>模拟失败</button>
        <button onClick={() => {
          for (let index = 3; index < 23; index++) {
            if (tasks[index]) continue;
            tasks[index] = { ...tasks[0], task_id: `preview-${index}`, label: `额外检查 ${index}`, revision: 1, created_at: createdAt + index, state: "queued", completed_at: null, result: null, error: null, tool_events: [] };
            receive({ event: "subagent_task", chat_id: chatId, task: tasks[index] });
          }
        }}>增加任务</button>
        <button onClick={() => setTopic(topic === chatId ? "other-preview" : chatId)}>切换会话</button>
        <button onClick={() => setActive(value => !value)}>切换活动面板</button>
        <button onClick={() => setDark(value => !value)}>切换主题</button>
        <button onClick={() => location.reload()}>重播</button>
      </nav>
      <ThreadShell session={{ key: `websocket:${topic}`, channel: "websocket", chatId: topic, createdAt: null, updatedAt: null, preview: "" }}
        title="子任务交互预览" onToggleSidebar={() => {}} theme={dark ? "dark" : "light"} onToggleTheme={() => setDark(value => !value)}
        settingsSnapshot={settings} composerActive={active} composerPortalTarget={parameters.has("portal") ? portal : undefined}
        sessions={[{ key: "websocket:reference-preview", channel: "websocket", chatId: "reference-preview", title: "Reference conversation", preview: "", createdAt: null, updatedAt: null,
          handle: { id: "handle_00000000000000000000000000000001", name: "reference" } }]} />
      {parameters.has("portal") ? <div ref={setPortal} className="shrink-0 px-4 pb-4" data-testid="preview-composer-portal" /> : null}
    </main>
  </ClientProvider>;
}
