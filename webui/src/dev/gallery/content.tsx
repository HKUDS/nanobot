import { useState } from "react";

import { FilePreviewPanelView, type FilePreviewPanelState } from "@/components/FilePreviewPanelView";
import { SessionInfoPopoverView } from "@/components/thread/SessionInfoPopoverView";
import { SubagentThreadView } from "@/components/thread/SubagentThreadView";
import type { AutomationUpdatePayload, SessionAutomationJob, UIMessage } from "@/lib/types";
import { StatePicker, type ComponentExample } from "./example";
import { useGalleryTranslation } from "./i18n";

function FilePreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"markdown" | "text" | "image" | "truncated" | "loading" | "error" | "route_missing">("markdown");
  const [imageOpen, setImageOpen] = useState(false);
  const path = mode === "image" ? "nanobot.png" : mode === "markdown" || mode === "truncated" ? "REPORT.md" : "greeting.ts";
  const state: FilePreviewPanelState = mode === "loading" ? { status: "loading" }
    : mode === "error" || mode === "route_missing" ? { status: "error", routeMissing: mode === "route_missing" }
      : { status: "ready", payload: mode === "image"
        ? { kind: "image", path, display_path: path, project_path: "/workspace", size: 24_576, mime_type: "image/png", data_url: "/brand/nanobot_icon_512.png" }
        : { path, display_path: path, project_path: "/workspace", size: 128, language: path.endsWith(".md") ? "markdown" : "typescript", truncated: mode === "truncated",
          content: path.endsWith(".md")
            ? '# Skills 迁移报告\n\n已完成迁移，**原文件保持不变**。\n\n## 验证结果\n\n| 项目 | 结果 |\n| --- | --- |\n| 文件数量 | 1,199 个 |\n| 校验 | SHA-256 一致 |\n\n- [x] 保留原目录\n- [x] 检查引用\n\n## 下一步\n\n打开技能目录，确认所需服务已连接。\n\n```sh\nls skills/\n```\n\n![示意图](https://example.com/chart.png)\n'
            : 'export const greeting = "Hello, Nanobot";\n\nexport function greet(name: string) {\n  return `${greeting}, ${name}`;\n}\n' } };
  return <div className="space-y-4">
    <StatePicker label={t("previews.filePreview.state")} value={mode} options={["markdown", "text", "image", "truncated", "loading", "error", "route_missing"]}
      onChange={(next) => { setMode(next); setImageOpen(false); }} />
    <div className="flex h-[32rem] flex-col overflow-hidden rounded-control border">
      <FilePreviewPanelView key={path} path={path} state={state} imageOpen={imageOpen} onImageOpenChange={setImageOpen}
        onImageError={() => { setMode("error"); setImageOpen(false); }} />
    </div>
  </div>;
}

function exampleJobs(now: number): SessionAutomationJob[] {
  return [
    { id: "gallery-daily-summary", name: "项目摘要", enabled: true, schedule: { kind: "every", every_ms: 3_600_000 },
      payload: { message: "整理当前项目的进展、风险和下一步。" }, state: { next_run_at_ms: now + 3_600_000 },
      origin: { channel: "websocket", chat_id: "gallery", session_key: "websocket:gallery" } },
    { id: "gallery-reminder", name: "代码检查", enabled: false, schedule: { kind: "cron", expr: "0 9 * * 1", tz: "Asia/Shanghai" },
      payload: { message: "检查本周变更并整理待办。" }, state: { last_status: "error", last_error: "previews.session.providerError" } },
    { id: "gallery-local-trigger", name: "发布检查", enabled: true, kind: "local_trigger", schedule: { kind: "local" },
      payload: { kind: "local_trigger", message: "检查发布结果。", command: 'nanobot trigger gallery-local-trigger "检查发布结果"' }, state: {} },
  ];
}

function SessionPreview() {
  const { t } = useGalleryTranslation();
  const [now] = useState(Date.now);
  const [mode, setMode] = useState<"ready" | "loading" | "error" | "empty" | "action_error">("ready");
  const [jobs, setJobs] = useState(() => exampleJobs(now));
  const [action, setAction] = useState<{ key: string; name?: string } | null>(null);
  const displayJobs = (items: SessionAutomationJob[]) => items.map((job) => ({ ...job,
    state: { ...job.state, last_error: job.state.last_error ? t(job.state.last_error) : undefined },
  }));
  const saveJob = (job: SessionAutomationJob, values: AutomationUpdatePayload) => {
    if (mode === "action_error") return Promise.reject(new Error(t("previews.session.saveError")));
    const next = jobs.map((item) => item.id !== job.id ? item : { ...item,
      name: values.name ?? item.name, schedule: values.schedule ?? item.schedule,
      payload: { ...item.payload, message: values.message ?? item.payload.message },
    });
    setJobs(next); setAction({ key: "previews.session.saved" }); return Promise.resolve(displayJobs(next));
  };
  return <div className="space-y-4" onClick={(event) => {
    const link = event.target instanceof Element ? event.target.closest('a[href^="#/chat/"]') : null;
    if (link) { event.preventDefault(); setAction({ key: "previews.session.openedChat" }); }
  }}>
    <StatePicker label={t("previews.session.state")} value={mode} options={["ready", "loading", "error", "empty", "action_error"]}
      onChange={(next) => { setMode(next); setJobs(exampleJobs(now)); setAction(null); }} />
    <SessionInfoPopoverView title="组件设计" jobs={mode === "ready" || mode === "action_error" ? displayJobs(jobs) : []} loading={mode === "loading"} loadFailed={mode === "error"} now={now}
      onOpenCalendar={() => setAction({ key: "previews.session.openedCalendar" })}
      onAction={(operation, job) => {
        if (mode === "action_error") return Promise.reject(new Error(t("previews.session.actionError")));
        const next = operation === "delete" ? jobs.filter((item) => item.id !== job.id) : jobs.map((item) => item.id !== job.id ? item
          : operation === "run" ? { ...item, state: { ...item.state, pending: true } }
            : { ...item, enabled: operation === "enable" });
        setJobs(next); setAction({ key: `previews.session.${operation}`, name: job.name }); return Promise.resolve(displayJobs(next));
      }} onEdit={saveJob} />
    <p role="status" className="text-sm text-muted-foreground">{action ? t(action.key, { name: action.name }) : t("previews.session.hint")}</p>
  </div>;
}

function SubagentPreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"ready" | "running" | "loading" | "error">("ready");
  const [startedAt] = useState(Date.now);
  const [retries, setRetries] = useState(0);
  const messages: UIMessage[] = mode === "loading" || mode === "error" ? [] : [
    { id: "gallery-child-prompt", role: "user", content: "检查配置文件的字段和默认值。", turnId: "gallery-child-turn", createdAt: startedAt },
    { id: "gallery-child-thinking", role: "assistant", content: "", reasoning: "先定位配置定义，再核对默认值。",
      reasoningStreaming: mode === "running", isStreaming: mode === "running", turnId: "gallery-child-turn", createdAt: startedAt + 200 },
    ...(mode === "ready" ? [{ id: "gallery-child-answer", role: "assistant" as const, content: "已核对配置：\n\n- **字段类型** 与默认值一致\n- **目录权限** 由 gateway 执行\n- UI 显示已有配置和保存结果", turnId: "gallery-child-turn", latencyMs: 4_200, createdAt: startedAt + 4_200 }] : []),
  ];
  return <div className="space-y-4">
    <StatePicker label={t("previews.subagent.state")} value={mode} options={["ready", "running", "loading", "error"]} onChange={setMode} />
    <div className="max-h-96 overflow-y-auto rounded-control border py-4">
      <SubagentThreadView messages={messages} loading={mode === "loading"} error={mode === "error" ? t("previews.history.error") : null} isStreaming={mode === "running"}
        activeTurnId={mode === "running" ? "gallery-child-turn" : null} runStartedAt={startedAt / 1000}
        onRetry={() => { setRetries((value) => value + 1); setMode("ready"); }} />
    </div>
    <p role="status" className="text-xs text-muted-foreground">{t("previews.history.retries", { amount: retries })}</p>
  </div>;
}

export const contentExamples: ComponentExample[] = [
  { title: "previews.filePreview.title", files: ["webui/src/components/FilePreviewPanelView.tsx"], Preview: FilePreview,
    description: "previews.filePreview.description", options: "previews.filePreview.options",
    code: '<FilePreviewPanelView path={path} state={previewState} imageOpen={imageOpen} onImageOpenChange={setImageOpen} onImageError={reportImageError} />' },
  { title: "previews.session.title", files: ["webui/src/components/thread/SessionInfoPopoverView.tsx"], Preview: SessionPreview,
    description: "previews.session.description", options: "previews.session.options",
    code: '<SessionInfoPopoverView title={title} jobs={jobs} loading={loading} loadFailed={failed} now={now} onAction={act} onEdit={edit} onOpenCalendar={openCalendar} />' },
  { title: "previews.subagent.title", files: ["webui/src/components/thread/SubagentThreadView.tsx"], Preview: SubagentPreview,
    description: "previews.subagent.description", options: "previews.subagent.options",
    code: '<SubagentThreadView messages={messages} loading={loading} error={error} isStreaming={running} runStartedAt={startedAt} onRetry={retry} />' },
];
