import { useState } from "react";

import { FilePreviewPanelView, type FilePreviewPanelState } from "@/components/FilePreviewPanelView";
import { WebPreviewPanelView } from "@/components/WebPreviewPanelView";
import { SessionInfoPopoverView } from "@/components/thread/SessionInfoPopoverView";
import { SubagentThreadView } from "@/components/thread/SubagentThreadView";
import type { AutomationUpdatePayload, SessionAutomationJob, UIMessage } from "@/lib/types";
import { StatePicker, type ComponentExample } from "./example";

function FilePreview() {
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
    <StatePicker label="文件预览状态" value={mode} options={["markdown", "text", "image", "truncated", "loading", "error", "route_missing"]}
      onChange={(next) => { setMode(next); setImageOpen(false); }} />
    <div className="flex h-[32rem] flex-col overflow-hidden rounded-control border">
      <FilePreviewPanelView key={path} path={path} state={state} imageOpen={imageOpen} onImageOpenChange={setImageOpen}
        onImageError={() => { setMode("error"); setImageOpen(false); }} />
    </div>
  </div>;
}

const localDocument = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>body{font-family:system-ui;padding:32px;color:#252525}h1{font-size:24px}p{line-height:1.7}code{background:#f2f2f2;padding:4px 8px;border-radius:6px}</style><h1>网页预览</h1><p>这段内容来自当前示例的本地文档。</p><p>点击顶部 <code>刷新</code> 按钮，重新显示文档；打开信息按钮查看隔离说明。</p></html>';

function WebsitePreview() {
  const [mode, setMode] = useState<"available" | "native" | "unsupported" | "sameOrigin" | "mixedContent" | "invalid">("available");
  const [revision, setRevision] = useState(0);
  const url = mode === "invalid" ? null : new URL(mode === "sameOrigin" ? window.location.href : "https://example.com/preview");
  return <div className="space-y-4">
    <StatePicker label="网页预览状态" value={mode} options={["available", "native", "unsupported", "sameOrigin", "mixedContent", "invalid"]} onChange={setMode} />
    <div className="flex h-80 flex-col overflow-hidden rounded-control border">
      <WebPreviewPanelView url={url} restriction={mode === "available" ? null : mode} loopback={mode === "sameOrigin"}
        onRefresh={() => setRevision((value) => value + 1)}>
        <iframe key={revision} title="本地示例网页" sandbox="" referrerPolicy="no-referrer" srcDoc={localDocument}
          className="min-h-0 w-full flex-1 border-0 bg-white" />
      </WebPreviewPanelView>
    </div>
    <p role="status" className="text-xs text-muted-foreground">刷新次数：{revision}</p>
  </div>;
}

function exampleJobs(now: number): SessionAutomationJob[] {
  return [
    { id: "gallery-daily-summary", name: "项目摘要", enabled: true, schedule: { kind: "every", every_ms: 3_600_000 },
      payload: { message: "整理当前项目的进展、风险和下一步。" }, state: { next_run_at_ms: now + 3_600_000 },
      origin: { channel: "websocket", chat_id: "gallery", session_key: "websocket:gallery" } },
    { id: "gallery-reminder", name: "代码检查", enabled: false, schedule: { kind: "cron", expr: "0 9 * * 1", tz: "Asia/Shanghai" },
      payload: { message: "检查本周变更并整理待办。" }, state: { last_status: "error", last_error: "Example provider unavailable" } },
    { id: "gallery-local-trigger", name: "发布检查", enabled: true, kind: "local_trigger", schedule: { kind: "local" },
      payload: { kind: "local_trigger", message: "检查发布结果。", command: 'nanobot trigger gallery-local-trigger "检查发布结果"' }, state: {} },
  ];
}

function SessionPreview() {
  const [now] = useState(Date.now);
  const [mode, setMode] = useState<"ready" | "loading" | "error" | "empty" | "action_error">("ready");
  const [jobs, setJobs] = useState(() => exampleJobs(now));
  const [action, setAction] = useState("");
  const saveJob = (job: SessionAutomationJob, values: AutomationUpdatePayload) => {
    if (mode === "action_error") return Promise.reject(new Error("示例保存失败，请重试。"));
    const next = jobs.map((item) => item.id !== job.id ? item : { ...item,
      name: values.name ?? item.name, schedule: values.schedule ?? item.schedule,
      payload: { ...item.payload, message: values.message ?? item.payload.message },
    });
    setJobs(next); setAction("已保存任务"); return Promise.resolve(next);
  };
  return <div className="space-y-4" onClick={(event) => {
    const link = event.target instanceof Element ? event.target.closest('a[href^="#/chat/"]') : null;
    if (link) { event.preventDefault(); setAction("打开示例聊天"); }
  }}>
    <StatePicker label="会话任务状态" value={mode} options={["ready", "loading", "error", "empty", "action_error"]}
      onChange={(next) => { setMode(next); setJobs(exampleJobs(now)); setAction(""); }} />
    <SessionInfoPopoverView title="组件设计" jobs={mode === "ready" || mode === "action_error" ? jobs : []} loading={mode === "loading"} loadFailed={mode === "error"} now={now}
      onOpenCalendar={() => setAction("打开任务日历")}
      onAction={(operation, job) => {
        if (mode === "action_error") return Promise.reject(new Error("示例操作失败，请重试。"));
        const next = operation === "delete" ? jobs.filter((item) => item.id !== job.id) : jobs.map((item) => item.id !== job.id ? item
          : operation === "run" ? { ...item, state: { ...item.state, pending: true } }
            : { ...item, enabled: operation === "enable" });
        setJobs(next); setAction(`${operation}: ${job.name}`); return Promise.resolve(next);
      }} onEdit={saveJob} />
    <p role="status" className="text-sm text-muted-foreground">{action || "打开会话详情，试用任务查看、开关、编辑和删除。"}</p>
  </div>;
}

function SubagentPreview() {
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
    <StatePicker label="子任务会话状态" value={mode} options={["ready", "running", "loading", "error"]} onChange={setMode} />
    <div className="max-h-96 overflow-y-auto rounded-control border py-4">
      <SubagentThreadView messages={messages} loading={mode === "loading"} error={mode === "error" ? "示例历史加载失败。" : null} isStreaming={mode === "running"}
        activeTurnId={mode === "running" ? "gallery-child-turn" : null} runStartedAt={startedAt / 1000}
        onRetry={() => { setRetries((value) => value + 1); setMode("ready"); }} />
    </div>
    <p role="status" className="text-xs text-muted-foreground">重试次数：{retries}</p>
  </div>;
}

export const contentExamples: ComponentExample[] = [
  { title: "FilePreviewPanelView · 文件内容", files: ["webui/src/components/FilePreviewPanelView.tsx"], Preview: FilePreview,
    description: "比较文本、图片、截断、加载和错误显示，点击图片试用缩放。", options: "state 是调用方提供的显示快照；path 决定文件类型和名称；图片打开与失败动作通过回调更新当前预览。",
    code: '<FilePreviewPanelView path={path} state={previewState} imageOpen={imageOpen} onImageOpenChange={setImageOpen} onImageError={reportImageError} />' },
  { title: "WebPreviewPanelView · 网页内容", files: ["webui/src/components/WebPreviewPanelView.tsx"], Preview: WebsitePreview,
    description: "查看网页标题栏、隔离说明和各类限制提示，试用刷新本地文档。", options: "运行时先决定 restriction，再提供网页内容。展示层通过 children 接收内容，通过 onRefresh 请求刷新；此示例的 iframe 使用本地 srcDoc。",
    code: '<WebPreviewPanelView url={url} restriction={restriction} loopback={loopback} onRefresh={refresh}>{frame}</WebPreviewPanelView>' },
  { title: "SessionInfoPopoverView · 会话任务", files: ["webui/src/components/thread/SessionInfoPopoverView.tsx"], Preview: SessionPreview,
    description: "查看任务列表，编辑、停用和删除任务，并切换加载和错误状态。", options: "jobs、loading、loadFailed 和 now 来自调用方；onAction 与 onEdit 返回更新后的任务快照；界面负责弹窗衔接、焦点恢复和操作反馈。",
    code: '<SessionInfoPopoverView title={title} jobs={jobs} loading={loading} loadFailed={failed} now={now} onAction={act} onEdit={edit} onOpenCalendar={openCalendar} />' },
  { title: "SubagentThreadView · 子任务消息", files: ["webui/src/components/thread/SubagentThreadView.tsx"], Preview: SubagentPreview,
    description: "查看子任务消息、推理活动、加载和失败状态，试用重试回调。", options: "messages 已由运行时投影；loading 和 error 复用历史加载组件；isStreaming 与 activeTurnId 决定当前活动。界面不获取任务历史。",
    code: '<SubagentThreadView messages={messages} loading={loading} error={error} isStreaming={running} runStartedAt={startedAt} onRetry={retry} />' },
];
