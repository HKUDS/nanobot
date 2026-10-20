import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

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
import { useGalleryTranslation } from "./i18n";

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
  { command: "/status", title: "previews.composer.statusCommand", description: "previews.composer.statusDescription", icon: "activity", lifecycle: "side_channel", acceptsArgs: false },
  { command: "/compact", title: "previews.composer.compactCommand", description: "previews.composer.compactDescription", icon: "archive", lifecycle: "finalize_active_turn", acceptsArgs: false },
  { command: "/help", title: "previews.composer.helpCommand", description: "previews.composer.helpDescription", icon: "circle-help", lifecycle: "side_channel", acceptsArgs: false },
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
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"thread" | "hero" | "streaming" | "disabled">("thread");
  const [preset, setPreset] = useState(presets[0].name);
  const [sent, setSent] = useState<{ kind: "sent"; content: string; attachments: number } | { kind: "stopped" } | null>(null);
  const [quoted, setQuoted] = useState<string | null>(null);
  const selected = presets.find((option) => option.name === preset) ?? presets[0];
  return <div className="space-y-4">
    <StatePicker label={t("previews.composer.state")} value={mode} options={["thread", "hero", "streaming", "disabled"]} onChange={setMode} />
    <Button variant="outline" size="sm" onClick={() => setQuoted("组件接收状态，并把操作交给调用方。")}>{t("previews.composer.addQuote")}</Button>
    <ThreadComposer disabled={mode === "disabled"} isStreaming={mode === "streaming"} variant={mode === "hero" ? "hero" : "thread"}
      inputAriaLabel={t("previews.composer.input")} placeholder={t("previews.composer.placeholder")}
      modelLabel={selected.name} modelDetail={selected.model} modelProvider={selected.provider} modelPreset={preset}
      modelPresets={presets} onModelPresetChange={setPreset} slashCommands={commands.map((command) => ({ ...command, title: t(command.title), description: t(command.description) }))}
      contextUsage={{ contextTokens: 18_500, contextWindowTokens: 200_000 }} recentRoundUsage={rounds}
      workspaceScope={projectScope} workspaceControlsHidden quotedContext={quoted} onQuotedContextChange={setQuoted}
      onStop={() => { setMode("thread"); setSent({ kind: "stopped" }); }}
      onSend={(content, attachments) => { setSent({ kind: "sent", content, attachments: attachments?.length ?? 0 }); return true; }} />
    <p role="status" className="text-sm text-muted-foreground">{sent?.kind === "stopped" ? t("previews.composer.stopped")
      : sent ? t("previews.composer.sent", { content: sent.content, attachments: sent.attachments ? t("previews.composer.attachments", { amount: sent.attachments }) : "" })
        : t("previews.composer.hint")}</p>
  </div>;
}

function ModelPresetPreview() {
  const { t } = useTranslation();
  const { t: g } = useGalleryTranslation();
  const [preset, setPreset] = useState(presets[0].name);
  const [mode, setMode] = useState<"ready" | "setup" | "hero">("ready");
  const [action, setAction] = useState("");
  const selected = presets.find((option) => option.name === preset) ?? presets[0];
  return <div className="space-y-4">
    <StatePicker label={g("previews.modelPreset.state")} value={mode} options={["ready", "setup", "hero"]} onChange={setMode} />
    <ModelPresetBadge label={mode === "setup" ? t("thread.composer.configureModel") : selected.name} modelPreset={preset} modelPresets={presets}
      provider={selected.provider} modelDetail={selected.model} isHero={mode === "hero"} needsSetup={mode === "setup"}
      onPresetChange={setPreset} onManageModels={() => setAction("previews.modelPreset.manage")}
      onClick={() => setAction("previews.modelPreset.settings")} />
    <p role="status" className="text-sm text-muted-foreground">{action ? g(action) : g("previews.modelPreset.hint", { preset })}</p>
  </div>;
}

function UsagePreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"normal" | "caution" | "critical" | "rounds_only" | "sheet">("normal");
  const tokens = mode === "critical" ? 192_000 : mode === "caution" ? 162_000 : 18_500;
  return <div className="space-y-4">
    <StatePicker label={t("previews.usage.state")} value={mode} options={["normal", "caution", "critical", "rounds_only", "sheet"]} onChange={setMode} />
    <ComposerUsagePopover context={mode === "rounds_only" ? null : { contextTokens: tokens, contextWindowTokens: 200_000 }}
      rounds={rounds} showLabel bottomSheet={mode === "sheet"} />
    <p className="text-sm text-muted-foreground">{t("previews.usage.hint")}</p>
  </div>;
}

function WorkspacePreview() {
  const { t } = useTranslation();
  const { t: g } = useGalleryTranslation();
  const [scope, setScope] = useState(projectScope);
  const [mode, setMode] = useState<"ready" | "disabled">("ready");
  return <div className="space-y-4">
    <StatePicker label={g("previews.workspace.state")} value={mode} options={["ready", "disabled"]} onChange={setMode} />
    <div className="flex flex-wrap items-center gap-3">
      <WorkspaceProjectPicker isHero scope={scope} defaultScope={projectScope} controls={workspaceCatalog.controls}
        disabled={mode === "disabled"} onLoadProjects={loadExampleProjects} onChange={setScope} />
      <WorkspaceAccessToggle scope={scope} isHero disabled={mode === "disabled"} onChange={setScope} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{scope.project_path} · {t(scope.access_mode === "full" ? "thread.composer.workspace.full" : "thread.composer.workspace.default")}</p>
  </div>;
}

function NavigatorPreview() {
  const { t } = useGalleryTranslation();
  const [selected, setSelected] = useState("");
  return <div className="space-y-4">
    <div className="flex items-center gap-3"><PromptNavigator messages={prompts} onJumpToPrompt={setSelected} />
      <span className="text-sm text-muted-foreground">{t("previews.navigator.hint")}</span></div>
    <p role="status" className="text-sm text-muted-foreground">{prompts.find((message) => message.id === selected)?.content ?? t("previews.navigator.empty")}</p>
  </div>;
}

function HeaderPreview() {
  const { t } = useTranslation();
  const { t: g } = useGalleryTranslation();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [temporary, setTemporary] = useState(false);
  const [action, setAction] = useState<{ kind: "sidebar" } | { kind: "jump"; id: string } | null>(null);
  return <div className="space-y-4">
    <div className="rounded-control border [--thread-header-position:relative]">
      <ThreadHeader title="组件使用示例" handle={{ id: "handle_11111111111111111111111111111111", name: "gallery" }}
        theme={theme} onToggleTheme={() => setTheme((value) => value === "light" ? "dark" : "light")}
        onToggleSidebar={() => setAction({ kind: "sidebar" })} temporaryChatEnabled={temporary} onTemporaryChatEnabledChange={setTemporary}
        promptNavigatorAction={<PromptNavigator messages={prompts} onJumpToPrompt={(id) => setAction({ kind: "jump", id })} />} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{action?.kind === "jump" ? g("previews.header.jump", { id: action.id })
      : g(action ? "previews.header.sidebar" : "previews.header.hint")} · {t(`settings.values.${theme}`)} · {g(temporary ? "previews.header.temporary" : "previews.header.regular")}</p>
  </div>;
}

function MessagesPreview() {
  const { t } = useGalleryTranslation();
  const [quoted, setQuoted] = useState("");
  const [fork, setFork] = useState<number | null>(null);
  return <div className="space-y-4">
    <div className="max-h-[30rem] overflow-y-auto rounded-control border px-4 py-5">
      <ThreadMessages messages={prompts} onQuoteSelection={setQuoted} onForkFromMessage={setFork} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{quoted ? t("previews.messages.quoted", { text: quoted }) : fork !== null ? t("previews.messages.forked", { index: fork + 1 }) : t("previews.messages.hint")}</p>
  </div>;
}

function ViewportPreview() {
  const { t } = useGalleryTranslation();
  const viewport = useRef<ThreadViewportHandle>(null);
  const [mode, setMode] = useState<"history" | "empty">("history");
  const [fork, setFork] = useState<number | null>(null);
  return <div className="space-y-4">
    <StatePicker label={t("previews.viewport.state")} value={mode} options={["history", "empty"]} onChange={setMode} />
    <div className="flex h-[28rem] flex-col overflow-hidden rounded-control border">
      <div className="shrink-0 border-b px-3 py-2"><PromptNavigator messages={mode === "history" ? longConversation : []}
        onJumpToPrompt={(id) => viewport.current?.jumpToUserPrompt(id)} /></div>
      <ThreadViewport ref={viewport} messages={mode === "history" ? longConversation : []} isStreaming={false}
        conversationKey={`gallery-${mode}`} conversationReady onForkFromMessage={setFork}
        emptyState={<p className="text-sm text-muted-foreground">{t("previews.viewport.empty")}</p>} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{fork !== null ? t("previews.messages.forked", { index: fork + 1 }) : t("previews.viewport.hint")}</p>
  </div>;
}

function HistoryPreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"loading" | "error" | "exhausted">("loading");
  const [retries, setRetries] = useState(0);
  return <div className="space-y-4">
    <StatePicker label={t("previews.history.state")} value={mode} options={["loading", "exhausted", "error"]} onChange={setMode} />
    <div className="relative h-20 rounded-control border">
      <ThreadHistoryStatus loading={mode === "loading"} error={mode === "error" ? t("previews.history.error") : null}
        exhausted={mode === "exhausted"} onRetry={() => { setRetries((value) => value + 1); setMode("loading"); }} />
    </div>
    <p role="status" className="text-sm text-muted-foreground">{t("previews.history.retries", { amount: retries })}</p>
  </div>;
}

function RecoveryPreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"awaiting_user" | "resuming" | "failed" | "unavailable">("awaiting_user");
  const [action, setAction] = useState("");
  const [visible, setVisible] = useState(true);
  const state: RecoveryState = { recovery_id: `gallery-recovery-${mode}`, status: mode === "unavailable" ? "failed" : mode, can_continue: mode !== "unavailable" };
  return <div className="space-y-4">
    <StatePicker label={t("previews.recovery.state")} value={mode} options={["awaiting_user", "resuming", "failed", "unavailable"]}
      onChange={(value) => { setMode(value); setVisible(true); setAction(""); }} />
    {visible ? <RecoveryNotice state={state} onContinue={() => { setVisible(false); setAction("previews.recovery.continued"); return Promise.resolve(); }}
      onDismiss={() => { setVisible(false); setAction("previews.recovery.dismissed"); return Promise.resolve(); }} /> : null}
    <Button variant="outline" size="sm" onClick={() => { setVisible(true); setAction(""); }}>{t("previews.recovery.reset")}</Button>
    <p role="status" className="text-sm text-muted-foreground">{t(action || "previews.recovery.hint")}</p>
  </div>;
}

function FallbackPreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"fallback" | "reauth">("fallback");
  const [dismissed, setDismissed] = useState(false);
  const [action, setAction] = useState("");
  return <div className="space-y-4">
    <StatePicker label={t("previews.fallback.state")} value={mode} options={["fallback", "reauth"]} onChange={(value) => { setMode(value); setDismissed(false); }} />
    {!dismissed ? <ModelFallbackNotice model="gpt-4.1" reauthProvider={mode === "reauth" ? "openai" : undefined}
      reauthProviderLabel={mode === "reauth" ? "OpenAI" : undefined} onDismiss={() => setDismissed(true)}
      onOpenSettings={() => setAction("previews.modelPreset.settings")} /> : null}
    <Button variant="outline" size="sm" onClick={() => setDismissed(false)}>{t("previews.fallback.showAgain")}</Button>
    <p role="status" className="text-sm text-muted-foreground">{t(action || "previews.fallback.hint")}</p>
  </div>;
}

function CompactionPreview() {
  const { t } = useGalleryTranslation();
  const [phase, setPhase] = useState<UIContextCompaction["phase"]>("started");
  return <><StatePicker label={t("previews.compaction.phase")} value={phase} options={["started", "succeeded", "failed", "cancelled"]} onChange={setPhase} />
    <ContextCompactionNotice compaction={{ id: "gallery-compaction", phase, announce: true }} /></>;
}

const errors: Record<StreamError["kind"], StreamError> = {
  message_too_big: { kind: "message_too_big" },
  workspace_scope_rejected: { kind: "workspace_scope_rejected" },
  turn_rejected: { kind: "turn_rejected", chatId: "gallery", turnId: "gallery-turn" },
  model_request_failed: { kind: "model_request_failed", chatId: "gallery", errorKind: "rate_limit", attempts: 3 },
};

function ErrorPreview() {
  const { t } = useGalleryTranslation();
  const [kind, setKind] = useState<StreamError["kind"]>("model_request_failed");
  const [dismissed, setDismissed] = useState(false);
  return <div className="space-y-4">
    <StatePicker label={t("previews.streamError.kind")} value={kind} options={["message_too_big", "workspace_scope_rejected", "turn_rejected", "model_request_failed"]}
      onChange={(value) => { setKind(value); setDismissed(false); }} />
    {!dismissed ? <StreamErrorNotice error={errors[kind]} onDismiss={() => setDismissed(true)} /> : null}
    <Button variant="outline" size="sm" onClick={() => setDismissed(false)}>{t("previews.fallback.showAgain")}</Button>
  </div>;
}

function ClusterPreview() {
  const { t } = useGalleryTranslation();
  const [status, setStatus] = useState<"running" | "done" | "error">("done");
  const [expanded, setExpanded] = useState(true);
  const [startedAt] = useState(Date.now);
  const event: ToolProgressEvent = { call_id: "gallery-read", name: "read_file", arguments: { path: "webui/src/components/thread/ThreadComposer.tsx" },
    phase: status === "running" ? "start" : status === "error" ? "error" : "end", error: status === "error" ? t("previews.cluster.error") : undefined };
  const trace = formatToolCallTrace(event) ?? "read_file()";
  const messages: UIMessage[] = [
    { id: "gallery-reasoning", role: "assistant", content: "", reasoning: "先核对组件接口，再查看消息和模型控件的组合方式。", reasoningStreaming: status === "running", isStreaming: status === "running", createdAt: startedAt },
    { id: "gallery-tool", role: "tool", kind: "trace", content: trace, traces: [trace], toolEvents: [event], createdAt: startedAt + 1_000 },
  ];
  return <><StatePicker label={t("previews.cluster.state")} value={status} options={["running", "done", "error"]} onChange={setStatus} />
    <AgentActivityCluster messages={messages} isTurnStreaming={status === "running"} hasBodyBelow={false}
      startedAtMs={startedAt} turnLatencyMs={4_800} expanded={expanded} onExpandedChange={setExpanded} /></>;
}

function SearchActivityPreview() {
  const { t } = useGalleryTranslation();
  const [status, setStatus] = useState<"running" | "done" | "error">("done");
  const [target, setTarget] = useState<"web" | "x">("web");
  return <><StatePicker label={t("previews.search.state")} value={status} options={["running", "done", "error"]} onChange={setStatus} />
    <StatePicker label={t("previews.search.source")} value={target} options={["web", "x"]} onChange={setTarget} />
    <WebSearchRun turnActive={status === "running"} run={{ key: "gallery-search", query: "React component composition", target, status,
      sources: status === "done" && target === "web" ? [{ title: "React · Passing props to a component", href: "https://react.dev/learn/passing-props-to-a-component", host: "react.dev", displayUrl: "react.dev/learn/passing-props-to-a-component" }] : [] }} /></>;
}

function ResponseSourcesPreview() {
  const { t } = useGalleryTranslation();
  return <Sample label={t("previews.responseSources.hint")}>
    <FallbackResponseSources sources={[
      { preset: "日常", model: "gpt-4.1", provider: "openai", fallback: true },
      { preset: "推理", model: "claude-sonnet-4", provider: "anthropic", fallback: true },
    ]} />
  </Sample>;
}

const components = "webui/src/components/";
export const conversationExamples: ComponentExample[] = [
  { title: "previews.composer.title", files: ["thread/ThreadComposer"], Preview: ComposerPreview,
    description: "previews.composer.description", options: "previews.composer.options",
    code: '<ThreadComposer onSend={send} modelPresets={presets} onModelPresetChange={setPreset} slashCommands={commands} />' },
  { title: "previews.modelPreset.title", files: ["thread/ModelPresetBadge"], Preview: ModelPresetPreview,
    description: "previews.modelPreset.description", options: "previews.modelPreset.options",
    code: '<ModelPresetBadge label={preset} modelPreset={preset} modelPresets={presets} onPresetChange={setPreset} isHero={false} />' },
  { title: "previews.usage.title", files: ["thread/ComposerUsagePopover"], Preview: UsagePreview,
    description: "previews.usage.description", options: "previews.usage.options",
    code: '<ComposerUsagePopover context={{ contextTokens: 18500, contextWindowTokens: 200000 }} rounds={rounds} showLabel />' },
  { title: "previews.workspace.title", files: ["thread/WorkspaceControls"], Preview: WorkspacePreview,
    description: "previews.workspace.description", options: "previews.workspace.options",
    code: '<WorkspaceProjectPicker isHero scope={scope} defaultScope={defaultScope} controls={controls} onLoadProjects={loadProjects} onChange={setScope} />\n<WorkspaceAccessToggle scope={scope} isHero onChange={setScope} />' },
  { title: "previews.navigator.title", files: ["thread/PromptNavigator"], Preview: NavigatorPreview,
    description: "previews.navigator.description", options: "previews.navigator.options",
    code: '<PromptNavigator messages={messages} onJumpToPrompt={jumpToPrompt} />' },
  { title: "previews.header.title", files: ["thread/ThreadHeader"], Preview: HeaderPreview,
    description: "previews.header.description", options: "previews.header.options",
    code: '<ThreadHeader title="Component examples" theme={theme} onToggleTheme={toggleTheme} onToggleSidebar={toggleSidebar} />' },
  { title: "previews.messages.title", files: ["thread/ThreadMessages", "thread/AssistantSelectionAction"], Preview: MessagesPreview,
    description: "previews.messages.description", options: "previews.messages.options",
    code: '<ThreadMessages messages={messages} onForkFromMessage={forkFromMessage} onQuoteSelection={quoteText} />' },
  { title: "previews.viewport.title", files: ["thread/ThreadViewport", "thread/PromptRail"], Preview: ViewportPreview,
    description: "previews.viewport.description", options: "previews.viewport.options",
    code: '<div className="flex h-96 flex-col"><ThreadViewport ref={viewport} messages={messages} isStreaming={false} /></div>' },
  { title: "previews.history.title", files: ["thread/ThreadHistoryStatus"], Preview: HistoryPreview,
    description: "previews.history.description", options: "previews.history.options",
    code: '<ThreadHistoryStatus loading={loading} error={error} onRetry={retry} />' },
  { title: "previews.recovery.title", files: ["thread/RecoveryNotice"], Preview: RecoveryPreview,
    description: "previews.recovery.description", options: "previews.recovery.options",
    code: '<RecoveryNotice state={recoveryState} onContinue={continueTask} onDismiss={dismissRecovery} />' },
  { title: "previews.fallback.title", files: ["thread/ModelFallbackNotice"], Preview: FallbackPreview,
    description: "previews.fallback.description", options: "previews.fallback.options",
    code: '<ModelFallbackNotice model="gpt-4.1" onDismiss={dismiss} onOpenSettings={openModelSettings} />' },
  { title: "previews.compaction.title", files: ["thread/ContextCompactionNotice"], Preview: CompactionPreview,
    description: "previews.compaction.description", options: "previews.compaction.options",
    code: '<ContextCompactionNotice compaction={{ id: "compaction-1", phase: "succeeded", announce: true }} />' },
  { title: "previews.streamError.title", files: ["thread/StreamErrorNotice"], Preview: ErrorPreview,
    description: "previews.streamError.description", options: "previews.streamError.options",
    code: '<StreamErrorNotice error={{ kind: "message_too_big" }} onDismiss={dismiss} />' },
  { title: "previews.cluster.title", files: ["thread/AgentActivityCluster"], Preview: ClusterPreview,
    description: "previews.cluster.description", options: "previews.cluster.options",
    code: '<AgentActivityCluster messages={activityMessages} isTurnStreaming={running} hasBodyBelow={false} expanded={expanded} onExpandedChange={setExpanded} />' },
  { title: "previews.search.title", files: ["thread/activity/WebSearchRun", "thread/activity/WebActivityRow"], Preview: SearchActivityPreview,
    description: "previews.search.description", options: "previews.search.options",
    code: '<WebSearchRun run={searchRun} turnActive={running} />' },
  { title: "previews.responseSources.title", files: ["ResponseSourceBadge"], Preview: ResponseSourcesPreview,
    description: "previews.responseSources.description", options: "previews.responseSources.options",
    code: '<FallbackResponseSources sources={[{ provider: "openai", model: "gpt-4.1", preset: "Daily", fallback: true }]} />' },
].map((example) => ({ ...example, files: example.files.map((file) => `${components}${file}.tsx`) }));
