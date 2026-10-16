import { useRef, useState } from "react";

import { FallbackResponseSources } from "@/components/ResponseSourceBadge";
import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { ComposerUsagePopover, type ComposerRoundUsage } from "@/components/thread/ComposerUsagePopover";
import { ContextCompactionNotice } from "@/components/thread/ContextCompactionNotice";
import { ModelFallbackNotice } from "@/components/thread/ModelFallbackNotice";
import { ModelPresetBadge, type ModelPresetOption } from "@/components/thread/ModelPresetBadge";
import { PromptNavigator } from "@/components/thread/PromptNavigator";
import { RecoveryNotice } from "@/components/thread/RecoveryNotice";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { ThreadHistoryStatus } from "@/components/thread/ThreadHistoryStatus";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { ThreadViewport, type ThreadViewportHandle } from "@/components/thread/ThreadViewport";
import { WorkspaceAccessToggle, WorkspaceProjectPicker } from "@/components/thread/WorkspaceControls";
import { WebSearchRun } from "@/components/thread/activity/WebSearchRun";
import { Button } from "@/components/ui/button";
import type { StreamError } from "@/lib/nanobot-client";
import { formatToolCallTrace } from "@/lib/tool-traces";
import type { RecoveryState, SlashCommand, ToolProgressEvent, UIContextCompaction, UIMessage, WorkspaceScopePayload, WorkspacesPayload } from "@/lib/types";
import { Sample, StatePicker, type ComponentExample } from "./example";

const createdAt = Date.UTC(2026, 0, 1, 12);
const presets: ModelPresetOption[] = [
  { name: "日常", provider: "openai", model: "gpt-4.1", contextWindowTokens: 1_047_576 },
  { name: "推理", provider: "anthropic", model: "claude-sonnet-4", reasoningEffort: "high", contextWindowTokens: 200_000 },
];
const rounds: ComposerRoundUsage[] = [
  { id: "gallery-round-1", timestamp: createdAt, inputTokens: 8_200, cachedTokens: 6_000, outputTokens: 620, generationMs: 3_100 },
  { id: "gallery-round-2", timestamp: createdAt + 60_000, inputTokens: 12_000, cachedTokens: 8_200, outputTokens: 980, generationMs: 5_400 },
  { id: "gallery-round-3", timestamp: createdAt + 120_000, inputTokens: 18_500, cachedTokens: 12_000, outputTokens: 1_240, generationMs: 7_200 },
];
const commands: SlashCommand[] = [
  { command: "/status", title: "会话状态", description: "查看当前会话状态", icon: "activity", lifecycle: "side_channel", acceptsArgs: false },
  { command: "/compact", title: "压缩上下文", description: "压缩当前会话上下文", icon: "archive", lifecycle: "finalize_active_turn", acceptsArgs: false },
  { command: "/help", title: "命令帮助", description: "查看可用命令", icon: "circle-help", lifecycle: "side_channel", acceptsArgs: false },
];
const projectScope: WorkspaceScopePayload = { project_path: "D:\\Projects\\nanobot", project_name: "nanobot", access_mode: "restricted" };
const workspaceCatalog: WorkspacesPayload = {
  schema_version: 1, default_access_mode: "default", default_scope: projectScope,
  recent_projects: [{ name: "nanobot", path: projectScope.project_path }, { name: "design-system", path: "D:\\Projects\\design-system" }],
  favorite_projects: [{ name: "nanobot", path: projectScope.project_path }],
  controls: { can_change_project: true },
};
const loadExampleProjects = () => Promise.resolve(workspaceCatalog);

const prompts: UIMessage[] = [
  { id: "gallery-prompt-1", role: "user", content: "整理组件的输入、状态和回调。", createdAt },
  { id: "gallery-answer-1", role: "assistant", content: "先从 **模型选择** 和 **消息输入** 开始。\n\n- 调用方提供数据\n- 组件显示状态\n- 回调更新当前选择", latencyMs: 4_200, createdAt: createdAt + 1_000 },
  { id: "gallery-prompt-2", role: "user", content: "给消息列表加入代码和引用示例。", createdAt: createdAt + 60_000 },
  { id: "gallery-answer-2", role: "assistant", content: "代码块支持复制：\n\n```tsx\n<ThreadMessages messages={messages} />\n```\n\n选中这段回复中的文字，可以试用引用操作。", latencyMs: 5_200, createdAt: createdAt + 61_000 },
  { id: "gallery-prompt-3", role: "user", content: "长会话如何跳转到之前的问题？", createdAt: createdAt + 120_000 },
  { id: "gallery-answer-3", role: "assistant", content: "打开问题导航后，可以搜索问题并跳转。\n\n滚动区域左侧的标记也对应每个问题。鼠标停留时会显示问题和回复摘要。", latencyMs: 2_600, createdAt: createdAt + 121_000 },
];
const longConversation: UIMessage[] = Array.from({ length: 8 }, (_, index) => [
  { id: `gallery-long-prompt-${index}`, role: "user" as const, content: `问题 ${index + 1}：${["模型配置", "工作目录", "消息排版", "工具活动"][index % 4]}如何展示？`, createdAt: createdAt + index * 60_000 },
  { id: `gallery-long-answer-${index}`, role: "assistant" as const, content: "组件接收已有状态，并把操作交给调用方。\n\n- 可以查看历史问题\n- 可以复制回复内容\n- 可以在回复后创建会话分支\n\n这段示例内容使预览产生真实滚动距离，便于体验问题标记和返回底部按钮。", latencyMs: 3_200, createdAt: createdAt + index * 60_000 + 1_000 },
]).flat();

function ComposerPreview() {
  const [mode, setMode] = useState<"thread" | "hero" | "streaming" | "disabled">("thread");
  const [preset, setPreset] = useState(presets[0].name);
  const [sent, setSent] = useState("");
  const [quoted, setQuoted] = useState<string | null>(null);
  const selected = presets.find((option) => option.name === preset) ?? presets[0];
  return <div className="space-y-4">
    <StatePicker label="输入状态" value={mode} options={["thread", "hero", "streaming", "disabled"]} onChange={setMode} />
    <Button variant="outline" size="sm" onClick={() => setQuoted("组件接收状态，并把操作交给调用方。")}>加入引用</Button>
    <ThreadComposer disabled={mode === "disabled"} isStreaming={mode === "streaming"} variant={mode === "hero" ? "hero" : "thread"}
      inputAriaLabel="示例消息" placeholder="输入消息，或输入 / 查看命令"
      modelLabel={selected.name} modelDetail={selected.model} modelProvider={selected.provider} modelPreset={preset}
      modelPresets={presets} onModelPresetChange={setPreset} slashCommands={commands}
      contextUsage={{ contextTokens: 18_500, contextWindowTokens: 200_000 }} recentRoundUsage={rounds}
      workspaceScope={projectScope} workspaceControlsHidden quotedContext={quoted} onQuotedContextChange={setQuoted}
      onStop={() => { setMode("thread"); setSent("已停止示例任务"); }}
      onSend={(content, attachments) => { setSent(`${content}${attachments?.length ? ` · ${attachments.length} 个附件` : ""}`); return true; }} />
    <p role="status" className="text-sm text-muted-foreground">{sent ? `提交内容：${sent}` : "试用消息提交、附件选择、模型切换和命令菜单。"}</p>
  </div>;
}

function ModelPresetPreview() {
  const [preset, setPreset] = useState(presets[0].name);
  const [mode, setMode] = useState<"ready" | "setup" | "hero">("ready");
  const [action, setAction] = useState("");
  const selected = presets.find((option) => option.name === preset) ?? presets[0];
  return <div className="space-y-4">
    <StatePicker label="模型控件状态" value={mode} options={["ready", "setup", "hero"]} onChange={setMode} />
    <ModelPresetBadge label={mode === "setup" ? "配置模型" : selected.name} modelPreset={preset} modelPresets={presets}
      provider={selected.provider} modelDetail={selected.model} isHero={mode === "hero"} needsSetup={mode === "setup"}
      onPresetChange={setPreset} onManageModels={() => setAction("打开模型管理")}
      onClick={() => setAction("打开模型设置")} />
    <p role="status" className="text-sm text-muted-foreground">{action || `当前预设：${preset}。打开菜单或用方向键切换。`}</p>
  </div>;
}

function UsagePreview() {
  const [mode, setMode] = useState<"normal" | "caution" | "critical" | "rounds_only" | "sheet">("normal");
  const tokens = mode === "critical" ? 192_000 : mode === "caution" ? 162_000 : 18_500;
  return <div className="space-y-4">
    <StatePicker label="用量状态" value={mode} options={["normal", "caution", "critical", "rounds_only", "sheet"]} onChange={setMode} />
    <ComposerUsagePopover context={mode === "rounds_only" ? null : { contextTokens: tokens, contextWindowTokens: 200_000 }}
      rounds={rounds} showLabel bottomSheet={mode === "sheet"} />
    <p className="text-sm text-muted-foreground">打开用量详情，查看上下文占用、缓存和各轮生成时间。</p>
  </div>;
}

function WorkspacePreview() {
  const [scope, setScope] = useState(projectScope);
  const [mode, setMode] = useState<"ready" | "disabled">("ready");
  return <div className="space-y-4">
    <StatePicker label="工作目录状态" value={mode} options={["ready", "disabled"]} onChange={setMode} />
    <div className="flex flex-wrap items-center gap-3">
      <WorkspaceProjectPicker isHero scope={scope} defaultScope={projectScope} controls={workspaceCatalog.controls}
        disabled={mode === "disabled"} onLoadProjects={loadExampleProjects} onChange={setScope} />
      <WorkspaceAccessToggle scope={scope} isHero disabled={mode === "disabled"} onChange={setScope} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{scope.project_path} · {scope.access_mode}</p>
  </div>;
}

function NavigatorPreview() {
  const [selected, setSelected] = useState("");
  return <div className="space-y-4">
    <div className="flex items-center gap-3"><PromptNavigator messages={prompts} onJumpToPrompt={setSelected} />
      <span className="text-sm text-muted-foreground">打开问题导航，搜索并选择问题。</span></div>
    <p role="status" className="text-sm text-muted-foreground">{prompts.find((message) => message.id === selected)?.content ?? "尚未选择问题"}</p>
  </div>;
}

function HeaderPreview() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [temporary, setTemporary] = useState(false);
  const [action, setAction] = useState("");
  return <div className="space-y-4">
    <div className="rounded-control border [--thread-header-position:relative]">
      <ThreadHeader title="组件使用示例" handle={{ id: "handle_11111111111111111111111111111111", name: "gallery" }}
        theme={theme} onToggleTheme={() => setTheme((value) => value === "light" ? "dark" : "light")}
        onToggleSidebar={() => setAction("切换侧栏")} temporaryChatEnabled={temporary} onTemporaryChatEnabledChange={setTemporary}
        promptNavigatorAction={<PromptNavigator messages={prompts} onJumpToPrompt={(id) => setAction(`跳转到 ${id}`)} />} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{action || "试用标题栏操作"} · {theme} · {temporary ? "临时会话" : "普通会话"}</p>
  </div>;
}

function MessagesPreview() {
  const [quoted, setQuoted] = useState("");
  const [fork, setFork] = useState<number | null>(null);
  return <div className="space-y-4">
    <div className="max-h-[30rem] overflow-y-auto rounded-control border px-4 py-5">
      <ThreadMessages messages={prompts} onQuoteSelection={setQuoted} onForkFromMessage={setFork} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{quoted ? `引用：${quoted}` : fork !== null ? `从第 ${fork + 1} 个问题创建分支` : "打开消息菜单，或选中回复文字后点击引用。"}</p>
  </div>;
}

function ViewportPreview() {
  const viewport = useRef<ThreadViewportHandle>(null);
  const [mode, setMode] = useState<"history" | "empty">("history");
  const [action, setAction] = useState("");
  return <div className="space-y-4">
    <StatePicker label="会话视图" value={mode} options={["history", "empty"]} onChange={setMode} />
    <div className="flex h-[28rem] flex-col overflow-hidden rounded-control border">
      <div className="shrink-0 border-b px-3 py-2"><PromptNavigator messages={mode === "history" ? longConversation : []}
        onJumpToPrompt={(id) => viewport.current?.jumpToUserPrompt(id)} /></div>
      <ThreadViewport ref={viewport} messages={mode === "history" ? longConversation : []} isStreaming={false}
        conversationKey={`gallery-${mode}`} conversationReady onForkFromMessage={(index) => setAction(`从问题 ${index + 1} 创建分支`)}
        emptyState={<p className="text-sm text-muted-foreground">输入消息开始会话</p>} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{action || "滚动查看问题标记，或用导航跳转并返回底部。"}</p>
  </div>;
}

function HistoryPreview() {
  const [mode, setMode] = useState<"loading" | "error" | "pulling">("error");
  const [retries, setRetries] = useState(0);
  return <div className="space-y-4">
    <StatePicker label="历史加载状态" value={mode} options={["loading", "error", "pulling"]} onChange={setMode} />
    <div className="relative h-20 rounded-control border">
      <ThreadHistoryStatus loading={mode === "loading"} error={mode === "error" ? "Example history unavailable" : null}
        pullDistance={mode === "pulling" ? 32 : 0} onRetry={() => { setRetries((value) => value + 1); setMode("loading"); }} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">重试次数：{retries}</p>
  </div>;
}

function RecoveryPreview() {
  const [mode, setMode] = useState<"awaiting_user" | "resuming" | "failed" | "unavailable">("awaiting_user");
  const [action, setAction] = useState("");
  const [visible, setVisible] = useState(true);
  const state: RecoveryState = { recovery_id: `gallery-recovery-${mode}`, status: mode === "unavailable" ? "failed" : mode, can_continue: mode !== "unavailable" };
  return <div className="space-y-4">
    <StatePicker label="恢复状态" value={mode} options={["awaiting_user", "resuming", "failed", "unavailable"]}
      onChange={(value) => { setMode(value); setVisible(true); setAction(""); }} />
    {visible ? <RecoveryNotice state={state} onContinue={() => { setVisible(false); setAction("继续示例任务"); return Promise.resolve(); }}
      onDismiss={() => { setVisible(false); setAction("已关闭恢复提示"); return Promise.resolve(); }} /> : null}
    <Button variant="outline" size="sm" onClick={() => { setVisible(true); setAction(""); }}>重置预览</Button>
    <p role="status" className="text-sm text-muted-foreground">{action || "选择恢复状态，再试用继续或关闭。"}</p>
  </div>;
}

function FallbackPreview() {
  const [mode, setMode] = useState<"fallback" | "reauth">("fallback");
  const [dismissed, setDismissed] = useState(false);
  const [action, setAction] = useState("");
  return <div className="space-y-4">
    <StatePicker label="模型回退状态" value={mode} options={["fallback", "reauth"]} onChange={(value) => { setMode(value); setDismissed(false); }} />
    {!dismissed ? <ModelFallbackNotice model="gpt-4.1" reauthProvider={mode === "reauth" ? "openai" : undefined}
      reauthProviderLabel={mode === "reauth" ? "OpenAI" : undefined} onDismiss={() => setDismissed(true)}
      onOpenSettings={() => setAction("打开模型设置")} /> : null}
    <Button variant="outline" size="sm" onClick={() => setDismissed(false)}>重新显示</Button>
    <p role="status" className="text-sm text-muted-foreground">{action || "试用模型设置入口与关闭按钮。"}</p>
  </div>;
}

function CompactionPreview() {
  const [phase, setPhase] = useState<UIContextCompaction["phase"]>("started");
  return <><StatePicker label="上下文压缩阶段" value={phase} options={["started", "succeeded", "failed", "cancelled"]} onChange={setPhase} />
    <ContextCompactionNotice compaction={{ id: "gallery-compaction", phase, announce: true }} /></>;
}

const errors: Record<StreamError["kind"], StreamError> = {
  message_too_big: { kind: "message_too_big" },
  workspace_scope_rejected: { kind: "workspace_scope_rejected" },
  turn_rejected: { kind: "turn_rejected", chatId: "gallery", turnId: "gallery-turn" },
  model_request_failed: { kind: "model_request_failed", chatId: "gallery", errorKind: "rate_limit", attempts: 3 },
};

function ErrorPreview() {
  const [kind, setKind] = useState<StreamError["kind"]>("model_request_failed");
  const [dismissed, setDismissed] = useState(false);
  return <div className="space-y-4">
    <StatePicker label="消息错误类型" value={kind} options={["message_too_big", "workspace_scope_rejected", "turn_rejected", "model_request_failed"]}
      onChange={(value) => { setKind(value); setDismissed(false); }} />
    {!dismissed ? <StreamErrorNotice error={errors[kind]} onDismiss={() => setDismissed(true)} /> : null}
    <Button variant="outline" size="sm" onClick={() => setDismissed(false)}>重新显示</Button>
  </div>;
}

function ClusterPreview() {
  const [status, setStatus] = useState<"running" | "done" | "error">("done");
  const [expanded, setExpanded] = useState(true);
  const [startedAt] = useState(Date.now);
  const event: ToolProgressEvent = { call_id: "gallery-read", name: "read_file", arguments: { path: "webui/src/components/thread/ThreadComposer.tsx" },
    phase: status === "running" ? "start" : status === "error" ? "error" : "end", error: status === "error" ? "File could not be read." : undefined };
  const trace = formatToolCallTrace(event) ?? "read_file()";
  const messages: UIMessage[] = [
    { id: "gallery-reasoning", role: "assistant", content: "", reasoning: "先核对组件接口，再查看消息和模型控件的组合方式。", reasoningStreaming: status === "running", isStreaming: status === "running", createdAt: startedAt },
    { id: "gallery-tool", role: "tool", kind: "trace", content: trace, traces: [trace], toolEvents: [event], createdAt: startedAt + 1_000 },
  ];
  return <><StatePicker label="活动状态" value={status} options={["running", "done", "error"]} onChange={setStatus} />
    <AgentActivityCluster messages={messages} isTurnStreaming={status === "running"} hasBodyBelow={false}
      startedAtMs={startedAt} turnLatencyMs={4_800} expanded={expanded} onExpandedChange={setExpanded} /></>;
}

function SearchActivityPreview() {
  const [status, setStatus] = useState<"running" | "done" | "error">("done");
  const [target, setTarget] = useState<"web" | "x">("web");
  return <><StatePicker label="搜索状态" value={status} options={["running", "done", "error"]} onChange={setStatus} />
    <StatePicker label="搜索来源" value={target} options={["web", "x"]} onChange={setTarget} />
    <WebSearchRun turnActive={status === "running"} run={{ key: "gallery-search", query: "React component composition", target, status,
      sources: status === "done" && target === "web" ? [{ title: "React · Passing props to a component", href: "https://react.dev/learn/passing-props-to-a-component", host: "react.dev", displayUrl: "react.dev/learn/passing-props-to-a-component" }] : [] }} /></>;
}

function ResponseSourcesPreview() {
  return <Sample label="点击回退标记查看响应时的预设、模型与供应商">
    <FallbackResponseSources sources={[
      { preset: "日常", model: "gpt-4.1", provider: "openai", fallback: true },
      { preset: "推理", model: "claude-sonnet-4", provider: "anthropic", fallback: true },
    ]} />
  </Sample>;
}

const components = "webui/src/components/";
export const conversationExamples: ComponentExample[] = [
  { title: "ThreadComposer · 消息输入", files: ["thread/ThreadComposer"], Preview: ComposerPreview,
    description: "直接试用消息提交、附件、命令和引用，并切换忙碌与禁用状态。", options: "onSend 返回成功后清空输入；isStreaming 控制停止与排队；variant 切换会话和欢迎页样式。示例提交保存在当前预览。",
    code: '<ThreadComposer onSend={send} modelPresets={presets} onModelPresetChange={setPreset} slashCommands={commands} />' },
  { title: "ModelPresetBadge · 模型预设", files: ["thread/ModelPresetBadge"], Preview: ModelPresetPreview,
    description: "打开模型菜单，体验预设切换、键盘操作和待配置状态。", options: "modelPresets 提供预设快照，modelPreset 与 onPresetChange 控制当前选择；needsSetup 显示配置入口。",
    code: '<ModelPresetBadge label={preset} modelPreset={preset} modelPresets={presets} onPresetChange={setPreset} isHero={false} />' },
  { title: "ComposerUsagePopover · 上下文用量", files: ["thread/ComposerUsagePopover"], Preview: UsagePreview,
    description: "查看上下文占用、缓存和生成时间，切换警戒状态与底部面板。", options: "context 提供上下文容量，rounds 提供各轮统计；bottomSheet 选择移动端面板。",
    code: '<ComposerUsagePopover context={{ contextTokens: 18500, contextWindowTokens: 200000 }} rounds={rounds} showLabel />' },
  { title: "WorkspaceControls · 工作目录", files: ["thread/WorkspaceControls"], Preview: WorkspacePreview,
    description: "选择示例项目，并切换当前预览的访问模式。", options: "scope 与 onChange 控制当前选择；onLoadProjects 提供示例目录列表。真实路径解析和权限执行由 gateway 负责。",
    code: '<WorkspaceProjectPicker isHero scope={scope} defaultScope={defaultScope} controls={controls} onLoadProjects={loadProjects} onChange={setScope} />\n<WorkspaceAccessToggle scope={scope} isHero onChange={setScope} />' },
  { title: "PromptNavigator · 问题导航", files: ["thread/PromptNavigator"], Preview: NavigatorPreview,
    description: "打开问题列表，搜索历史问题并查看跳转回调。", options: "messages 提供完整消息列表，组件提取用户问题；onJumpToPrompt 接收目标消息 ID。",
    code: '<PromptNavigator messages={messages} onJumpToPrompt={jumpToPrompt} />' },
  { title: "ThreadHeader · 会话标题栏", files: ["thread/ThreadHeader"], Preview: HeaderPreview,
    description: "试用侧栏、主题、临时会话和问题导航控件。", options: "title、handle、theme 与 temporaryChatEnabled 提供显示状态；各操作通过回调交给调用方。",
    code: '<ThreadHeader title="Component examples" theme={theme} onToggleTheme={toggleTheme} onToggleSidebar={toggleSidebar} />' },
  { title: "ThreadMessages · 消息列表", files: ["thread/ThreadMessages", "thread/AssistantSelectionAction"], Preview: MessagesPreview,
    description: "查看完整多轮消息组合，试用消息菜单、会话分支和选中文本引用。", options: "messages 为已投影消息；onForkFromMessage 接收用户问题索引，onQuoteSelection 接收所选回复文字。",
    code: '<ThreadMessages messages={messages} onForkFromMessage={forkFromMessage} onQuoteSelection={quoteText} />' },
  { title: "ThreadViewport · 会话滚动", files: ["thread/ThreadViewport", "thread/PromptRail"], Preview: ViewportPreview,
    description: "真实长会话滚动区，包含问题标记、导航跳转和返回底部。", options: "固定预览容器高度；messages 驱动历史显示，ref.jumpToUserPrompt 执行定位；emptyState 提供空会话内容。",
    code: '<div className="flex h-96 flex-col"><ThreadViewport ref={viewport} messages={messages} isStreaming={false} /></div>' },
  { title: "ThreadHistoryStatus · 历史加载", files: ["thread/ThreadHistoryStatus"], Preview: HistoryPreview,
    description: "切换加载、失败和下拉状态，并试用重试按钮。", options: "loading 控制加载指示，error 控制错误提示，pullDistance 控制下拉位置，onRetry 由调用方提供。",
    code: '<ThreadHistoryStatus loading={loading} error={error} onRetry={retry} />' },
  { title: "RecoveryNotice · 任务恢复", files: ["thread/RecoveryNotice"], Preview: RecoveryPreview,
    description: "切换中断、恢复、失败和无法继续状态，试用继续与关闭。", options: "state 为已有恢复快照；onContinue 与 onDismiss 返回 Promise。示例回调只更新当前预览。",
    code: '<RecoveryNotice state={recoveryState} onContinue={continueTask} onDismiss={dismissRecovery} />' },
  { title: "ModelFallbackNotice · 模型回退", files: ["thread/ModelFallbackNotice"], Preview: FallbackPreview,
    description: "查看回退模型与授权失效提示，试用设置入口和关闭操作。", options: "model 标识回退模型；reauthProviderLabel 显示授权到期提示；onOpenSettings 和 onDismiss 由调用方提供。",
    code: '<ModelFallbackNotice model="gpt-4.1" onDismiss={dismiss} onOpenSettings={openModelSettings} />' },
  { title: "ContextCompactionNotice · 上下文压缩", files: ["thread/ContextCompactionNotice"], Preview: CompactionPreview,
    description: "比较压缩开始、成功、失败和取消时的显示。", options: "compaction.phase 决定提示，announce 控制屏幕阅读器播报。",
    code: '<ContextCompactionNotice compaction={{ id: "compaction-1", phase: "succeeded", announce: true }} />' },
  { title: "StreamErrorNotice · 消息错误", files: ["thread/StreamErrorNotice"], Preview: ErrorPreview,
    description: "比较消息大小、目录权限、任务拒绝和模型请求失败的提示。", options: "error.kind 决定错误文案；onDismiss 关闭提示。",
    code: '<StreamErrorNotice error={{ kind: "message_too_big" }} onDismiss={dismiss} />' },
  { title: "AgentActivityCluster · 完整活动", files: ["thread/AgentActivityCluster"], Preview: ClusterPreview,
    description: "用真实活动容器展示推理和工具记录，切换运行、完成和失败。", options: "messages 包含已有 reasoning 和 trace 投影；isTurnStreaming 控制活动状态；expanded 可由调用方控制。",
    code: '<AgentActivityCluster messages={activityMessages} isTurnStreaming={running} hasBodyBelow={false} expanded={expanded} onExpandedChange={setExpanded} />' },
  { title: "WebSearchRun · 搜索活动", files: ["thread/activity/WebSearchRun", "thread/activity/WebActivityRow"], Preview: SearchActivityPreview,
    description: "查看搜索进度与结果来源，切换网页和 X 搜索样式。", options: "run 为搜索显示快照，包含 query、target、status 和 sources；turnActive 控制运行效果。结果站点图标由共享组件加载。",
    code: '<WebSearchRun run={searchRun} turnActive={running} />' },
  { title: "FallbackResponseSources · 响应来源", files: ["ResponseSourceBadge"], Preview: ResponseSourcesPreview,
    description: "查看历史回复使用的回退预设、模型和供应商。", options: "sources 保留响应时的模型快照，仅 fallback 为 true 的来源显示标记。",
    code: '<FallbackResponseSources sources={[{ provider: "openai", model: "gpt-4.1", preset: "Daily", fallback: true }]} />' },
].map((example) => ({ ...example, files: example.files.map((file) => `${components}${file}.tsx`) }));
