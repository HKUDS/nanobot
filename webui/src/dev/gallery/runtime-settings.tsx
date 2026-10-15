import { useRef, useState } from "react";

import { StarLinkView, StarPromptView } from "@/components/StarPromptView";
import { AboutSettingsView } from "@/components/settings/overview/AboutSettingsView";
import { AppearanceSettingsView } from "@/components/settings/overview/AppearanceSettingsView";
import { VersionCheckRowView, type VersionCheckState } from "@/components/settings/overview/VersionCheckRowView";
import { AutomationChatBindingView } from "@/components/settings/system/AutomationChatBindingView";
import { AutomationRunDialogView, type AutomationRunResult } from "@/components/settings/system/AutomationRunDialogView";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { DEFAULT_LOCAL_PREFS } from "@/lib/local-preferences";
import type { AutomationChatsPayload, SessionAutomationJob } from "@/lib/types";
import { StatePicker, type ComponentExample } from "./example";

const job: SessionAutomationJob = {
  id: "gallery-report", name: "Weekly summary", enabled: true, chat_binding_revision: "gallery-1",
  schedule: { kind: "cron", expr: "30 9 * * 1", tz: "UTC" },
  payload: { message: "Summarize the changes and open questions." }, state: {},
  origin: { channel: "websocket", title: "Planning" },
};
const chats: AutomationChatsPayload = {
  revision: "gallery-1", current: { id: "planning", title: "Planning", channel: "websocket" },
  chats: [{ id: "planning", title: "Planning", channel: "websocket" },
    { id: "reviews", title: "Reviews", channel: "websocket" },
    { id: "archived", title: "Archived chat", channel: "websocket", unavailable: true }],
};

function RunResultPreview() {
  const [mode, setMode] = useState<"complete" | "loading" | "error" | "empty" | "unavailable">("complete");
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const result: AutomationRunResult = mode === "loading" || mode === "error"
    ? { status: mode, response: null }
    : { status: "loaded", response: mode === "empty" ? "" : mode === "unavailable" ? null : "## Weekly summary\n\n- **Completed:** component previews\n- **Next:** review the changes" };
  return <><StatePicker label="运行结果" value={mode} options={["complete", "loading", "error", "empty", "unavailable"]} onChange={setMode} />
    <Button ref={trigger} variant="outline" onClick={() => setOpen(true)}>查看运行结果</Button>
    <AutomationRunDialogView job={job} run={{ run_at_ms: Date.UTC(2026, 9, 12, 9, 30), status: "ok", duration_ms: 3200 }}
      locale="zh-CN" open={open} result={result} onRetry={() => setMode("complete")} onOpenChange={setOpen}
      onCloseAutoFocus={(event) => { event.preventDefault(); trigger.current?.focus(); }} /></>;
}

function ChatBindingPreview() {
  const [mode, setMode] = useState<"ready" | "pending" | "load-error" | "conflict">("ready");
  const [task, setTask] = useState(job);
  const [data, setData] = useState(chats);
  const [notice, setNotice] = useState("");
  return <><StatePicker label="聊天绑定状态" value={mode} options={["ready", "pending", "load-error", "conflict"]} onChange={setMode} />
    <Dialog><DialogTrigger asChild><Button variant="outline">设置运行聊天</Button></DialogTrigger>
      <DialogContent aria-describedby={undefined} className="max-w-[520px] gap-0 p-0">
        <AutomationChatBindingView job={mode === "pending" ? { ...task, state: { pending: true } } : task}
          data={data} loadError={mode === "load-error"} showBrandLogos={false} onReload={() => setMode("ready")}
          onSave={async (_task, values) => {
            if (mode === "conflict") throw new Error("automation_chat_conflict");
            setTask((current) => ({ ...current, chat_binding_revision: `${current.chat_binding_revision}-next`, payload: { ...current.payload, message: values.message } }));
          }} onSaved={(target) => {
            setData((current) => ({ ...current, current: target, revision: `${current.revision}-next` }));
            setNotice(`下次运行将在 ${target.title} 中进行`);
          }}>{(picker) => <>
            <DialogHeader className="px-6 pb-4 pr-12 pt-5"><DialogTitle>{task.name}</DialogTitle></DialogHeader>
            <div className="px-6 pb-6">{picker}</div>
          </>}</AutomationChatBindingView>
      </DialogContent>
    </Dialog><p role="status" className="mt-4 text-xs text-muted-foreground">{notice || "选择目标聊天，确认或修改任务说明。"}</p></>;
}

function AboutPreview() {
  const [mode, setMode] = useState<"ready" | "checking" | "up-to-date" | "update" | "error">("ready");
  const [notice, setNotice] = useState("");
  const result: VersionCheckState = mode === "up-to-date" ? { type: mode }
    : mode === "update" ? { type: mode, latestVersion: "0.3.6", pypiUrl: "https://pypi.org/project/nanobot-ai/" }
      : mode === "error" ? { type: mode, message: "无法获取版本信息，请重试。" } : null;
  return <><StatePicker label="版本状态" value={mode} options={["ready", "checking", "up-to-date", "update", "error"]} onChange={setMode} />
    <AboutSettingsView reportIssueUrl="https://github.com/HKUDS/nanobot/issues/new?template=bug_report.yml"
      versionCheck={<VersionCheckRowView currentVersion="0.3.5" currentCommit="abcdef1234567890" checking={mode === "checking"}
        result={result} onCheck={() => setMode("update")} />}
      starLink={<StarLinkView onActivate={() => setNotice("选择了 GitHub 链接")} />} />
    {notice ? <p role="status" className="mt-4 text-xs text-muted-foreground">{notice}</p> : null}</>;
}

function AppearancePreview() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [preferences, setPreferences] = useState(DEFAULT_LOCAL_PREFS);
  return <><AppearanceSettingsView theme={theme} onToggleTheme={() => setTheme((current) => current === "light" ? "dark" : "light")}
    localPrefs={preferences} onChangeLocalPrefs={setPreferences}
    onChangeBrowserNotifications={(enabled) => setPreferences((current) => ({ ...current, browserNotifications: enabled }))} />
    <pre role="status" className="mt-4 overflow-auto rounded-control bg-muted p-4 text-xs">{JSON.stringify({ theme, ...preferences }, null, 2)}</pre></>;
}

function StarInvitationPreview() {
  const [mode, setMode] = useState<"ready" | "saving" | "error">("ready");
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState("");
  return <><StatePicker label="邀请状态" value={mode} options={["ready", "saving", "error"]} onChange={setMode} />
    <Button variant="outline" onClick={() => setOpen(true)}>查看邀请</Button>
    <StarPromptView open={open} saving={mode === "saving"} error={mode === "error"} onOpenChange={setOpen}
      onDismissForever={() => { setNotice("预览中选择了不再提醒"); setOpen(false); }}
      onStar={() => { setNotice("预览中选择了 GitHub 链接"); setOpen(false); }} />
    {notice ? <p role="status" className="mt-4 text-xs text-muted-foreground">{notice}</p> : null}</>;
}

export const runtimeSettingsExamples: ComponentExample[] = [
  { title: "AutomationRunDialogView · 运行结果", files: ["webui/src/components/settings/system/AutomationRunDialogView.tsx"], Preview: RunResultPreview,
    description: "打开运行结果，比较 Markdown 回复、加载、重试、空回复与历史记录缺失状态。",
    options: "result 提供加载状态与已取得的回复。onRetry 交给调用方处理；此视图不读取运行时或请求结果。",
    code: '<AutomationRunDialogView job={job} run={run} locale="zh-CN" open={open} result={{ status: "loaded", response }} onRetry={retry} onOpenChange={setOpen} onCloseAutoFocus={restoreFocus} />' },
  { title: "AutomationChatBindingView · 运行聊天", files: ["webui/src/components/settings/system/AutomationChatBindingView.tsx"], Preview: ChatBindingPreview,
    description: "选择运行聊天、修改任务说明，确认、更换回来或取消；可比较任务占用、加载错误与冲突。",
    options: "data 与 job 提供可用聊天和绑定版本。视图管理确认草稿；onSave、onSaved 与 onReload 由功能入口接入数据操作。",
    code: '<AutomationChatBindingView job={job} data={chats} loadError={false} showBrandLogos={false} onSave={save} onSaved={updateCurrent} onReload={reload}>{renderDetails}</AutomationChatBindingView>' },
  { title: "About and version views · 关于与版本", files: ["webui/src/components/settings/overview/AboutSettingsView.tsx", "webui/src/components/settings/overview/VersionCheckRowView.tsx"], Preview: AboutPreview,
    description: "比较版本检查状态、提交链接、更新入口和关于页面；按钮用示例结果更新显示。",
    options: "AboutSettingsView 接受版本与支持链接的组合。VersionCheckRowView 展示 checking/result，并通过 onCheck 请求检查。真实检查与诊断链接数据由功能入口负责。",
    code: '<AboutSettingsView reportIssueUrl={reportIssueUrl} versionCheck={<VersionCheckRowView currentVersion={version} checking={checking} result={result} onCheck={check} />} starLink={<StarLinkView onActivate={star} />} />' },
  { title: "AppearanceSettingsView · 外观选项", files: ["webui/src/components/settings/overview/AppearanceSettingsView.tsx"], Preview: AppearancePreview,
    description: "切换外观、活动展示、文件差异和通知偏好，下方显示示例值。",
    options: "主题和偏好由调用方管理。onChangeBrowserNotifications 将权限申请交给功能入口；预览回调只改变示例开关。",
    code: '<AppearanceSettingsView theme={theme} onToggleTheme={toggleTheme} localPrefs={preferences} onChangeLocalPrefs={setPreferences} onChangeBrowserNotifications={changeNotifications} />' },
  { title: "StarPromptView · 支持邀请", files: ["webui/src/components/StarPromptView.tsx"], Preview: StarInvitationPreview,
    description: "打开实际邀请弹窗，比较保存与错误状态，体验暂缓、GitHub 链接和不再提醒的操作。",
    options: "open、saving 和 error 是显示状态。领取邀请与持久化偏好由原有 StarPrompt 入口负责；视图只调用传入操作。",
    code: '<StarPromptView open={open} saving={saving} error={error} onOpenChange={setOpen} onDismissForever={dismiss} onStar={openRepository} />' },
];
