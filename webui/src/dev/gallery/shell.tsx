import { useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { CapabilityMentionToken } from "@/components/CliAppMentionText";
import type { CapabilityMentionSegment } from "@/lib/composer-mention-text";
import { DeleteConfirm } from "@/components/DeleteConfirm";
import { FileActions } from "@/components/FileActions";
import { InlineTokenHighlight, INLINE_TOKEN_HIGHLIGHT_COLOR } from "@/components/InlineTokenHighlight";
import { MessageLinksMenu, useMessageWebLinks } from "@/components/MessageLinksMenu";
import { RenameDialog } from "@/components/RenameDialog";
import { SessionHandleLabel } from "@/components/SessionHandleLabel";
import { SlashCommandText } from "@/components/SlashCommandText";
import { StartupShell } from "@/components/StartupShell";
import { UserMessageText } from "@/components/UserMessageText";
import { WebLink } from "@/components/WebLink";
import * as ProductIcons from "@/components/icons/product-icons";
import { HostCompatibilityDialog } from "@/components/remote/HostCompatibilityDialog";
import { HostConnectionStatus } from "@/components/remote/HostConnectionStatus";
import type { HostConnectionState } from "@/components/remote/remote-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PaneWorkbench, type WorkbenchPane } from "@/components/workbench/PaneWorkbench";
import type { HostCompatibility, RemoteProfile } from "@/lib/remote-instances";
import type { CliAppInfo, McpPresetInfo, SessionAutomationJob, SessionMention, WorkbenchLayout } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Sample, StatePicker, type ComponentExample } from "./example";

const cliApp: CliAppInfo = {
  name: "nanobot", display_name: "Nanobot", category: "assistant", description: "Local assistant",
  requires: "Python", source: "local", entry_point: "nanobot", install_supported: true,
  installed: true, available: true, status: "installed", skill_installed: true,
  logo_url: "/brand/nanobot_icon_512.png", brand_color: "var(--inline-token-highlight)",
};
const mcpPreset: McpPresetInfo = {
  name: "files", display_name: "Workspace files", category: "files", description: "Workspace files",
  docs_url: "", transport: "stdio", requires: "", note: "", install_supported: true,
  installed: true, configured: true, available: true, status: "configured", required_fields: [],
  connection_summary: "Local files",
};
const sessionMention: SessionMention = {
  id: "gallery-session", name: "design", session_key: "webui:gallery-design", title: "组件设计",
};

function RenamePreview() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("组件设计");
  return <div className="space-y-4">
    <p className="text-sm">{title}</p>
    <Button variant="outline" onClick={() => setOpen(true)}>重命名分组</Button>
    <RenameDialog open={open} title={title}
      dialogTitle={t("workbench.renameGroupTitle")}
      description={t("workbench.renameGroupDescription")}
      placeholder={t("workbench.renameGroupPlaceholder")}
      onCancel={() => setOpen(false)}
      onConfirm={(next) => { setTitle(next); setOpen(false); }} />
    <p role="status" className="text-xs text-muted-foreground">保存后更新上方标题。</p>
  </div>;
}

const automations: SessionAutomationJob[] = [
  { id: "gallery-daily", name: "每日项目摘要", enabled: true, schedule: { kind: "cron", expr: "0 9 * * *", tz: "Asia/Shanghai" }, payload: { message: "Summarize project updates" }, state: { next_run_at_ms: Date.UTC(2026, 9, 14, 1) } },
  { id: "gallery-hourly", name: "每小时检查", enabled: false, schedule: { kind: "every", every_ms: 3_600_000 }, payload: { message: "Check updates" }, state: {} },
  { id: "gallery-trigger", name: "发布后检查", enabled: true, schedule: { kind: "local" }, payload: { message: "Check the release", kind: "local_trigger" }, state: {} },
  { id: "gallery-once", name: "一次性提醒", enabled: true, schedule: { kind: "at", at_ms: Date.UTC(2026, 9, 15, 2) }, payload: { message: "Review the result" }, state: { next_run_at_ms: Date.UTC(2026, 9, 15, 2) } },
  { id: "gallery-weekly", name: "每周回顾", enabled: true, schedule: { kind: "every", every_ms: 604_800_000 }, payload: { message: "Review the week" }, state: {} },
];

function DeletePreview() {
  const [scenario, setScenario] = useState<"single" | "multiple" | "automations">("single");
  const [open, setOpen] = useState(false);
  const [deleted, setDeleted] = useState(false);
  return <>
    <StatePicker label="删除场景" value={scenario} options={["single", "multiple", "automations"]}
      onChange={(next) => { setScenario(next); setDeleted(false); }} />
    <Button variant="outline" onClick={() => { setDeleted(false); setOpen(true); }}>打开删除确认</Button>
    <DeleteConfirm open={open} title="组件设计" count={scenario === "multiple" ? 3 : 1}
      automations={scenario === "automations" ? automations : []} onCancel={() => setOpen(false)}
      onConfirm={() => { setDeleted(true); setOpen(false); }} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">{deleted ? "已确认删除示例。" : "选择单个、批量或带自动任务的会话。"}</p>
  </>;
}

function InlineTokensPreview() {
  const [command, setCommand] = useState("/status");
  const [handle, setHandle] = useState("gallery-session");
  return <div className="space-y-5">
    <Sample label="命令文本"><Input aria-label="命令文本" value={command} onChange={(event) => setCommand(event.target.value)} />
      <p className="text-sm">运行 <SlashCommandText command={command} /> 查看状态。</p></Sample>
    <Sample label="会话标识"><Input aria-label="会话标识" value={handle} onChange={(event) => setHandle(event.target.value)} />
      <p className="text-sm">继续 <SessionHandleLabel id={handle}>@design</SessionHandleLabel> 中的工作。</p></Sample>
    <Sample label="共享高亮"><p className="text-sm">使用 <InlineTokenHighlight color={INLINE_TOKEN_HIGHLIGHT_COLOR} title="Skill: review">review</InlineTokenHighlight> 检查修改。</p></Sample>
  </div>;
}

function SessionLinksPreview({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState(false);
  return <div className="space-y-4" onClick={(event) => {
    if (!(event.target instanceof Element)) return;
    const link = event.target.closest<HTMLAnchorElement>('a[href^="#/chat/"]');
    if (!link) return;
    event.preventDefault();
    setSelected(true);
  }}>
    {children}
    <p role="status" className="text-xs text-muted-foreground">{selected ? "已选择会话：组件设计。" : "选择会话引用查看反馈。"}</p>
  </div>;
}

function UserTextPreview() {
  const [text, setText] = useState("用 $review 检查 @nanobot 的修改，参考 @design 和 @files。");
  return <SessionLinksPreview>
    <label className="grid gap-2 text-xs text-muted-foreground">消息文本
      <Textarea value={text} onChange={(event) => setText(event.target.value)} />
    </label>
    <p className="whitespace-pre-wrap text-sm leading-7"><UserMessageText text={text} cliApps={[cliApp]}
      mcpPresets={[mcpPreset]} sessionMentions={[sessionMention]} /></p>
  </SessionLinksPreview>;
}

function CapabilityTokensPreview() {
  const [variant, setVariant] = useState<"message" | "composer">("message");
  const segments: Array<Exclude<CapabilityMentionSegment, { kind: "text" }>> = [
    { kind: "cli", text: "@nanobot", app: cliApp },
    { kind: "mcp", text: "@files", preset: mcpPreset },
    { kind: "session", text: "@design", mention: sessionMention },
  ];
  return <SessionLinksPreview>
    <StatePicker label="引用位置" value={variant} options={["message", "composer"]} onChange={setVariant} />
    <div className="flex flex-wrap gap-6 text-sm leading-7">{segments.map((segment) =>
      <CapabilityMentionToken key={segment.kind} segment={segment} variant={variant} />)}</div>
  </SessionLinksPreview>;
}

function ProductIconsPreview() {
  const [size, setSize] = useState<"16" | "20" | "24">("20");
  const [selected, setSelected] = useState("ConversationIcon");
  return <>
    <StatePicker label="图标尺寸" value={size} options={["16", "20", "24"]} onChange={setSize} />
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">{Object.entries(ProductIcons).map(([name, Icon]) =>
      <button key={name} type="button" aria-pressed={selected === name} onClick={() => setSelected(name)}
        className={cn("flex min-w-0 flex-col items-center gap-2 rounded-control p-3 text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", selected === name && "bg-muted text-foreground")}>
        <Icon size={Number(size)} /><span className="max-w-full break-all text-center text-[10px] leading-4">{name.replace(/Icon$/, "")}</span>
      </button>)}</div>
    <p role="status" className="mt-4 text-xs text-muted-foreground">已选择：{selected}</p>
  </>;
}

function StartupPreview() {
  return <div className="gallery-startup-preview h-80 overflow-hidden rounded-panel border"><StartupShell embedded /></div>;
}

function FileActionsPreview() {
  const [scope, setScope] = useState<"workspace" | "outside" | "unresolved">("workspace");
  const path = "src/app.tsx";
  return <>
    <StatePicker label="文件范围" value={scope} options={["workspace", "outside", "unresolved"]} onChange={setScope} />
    <FileActions path={path} metadata={scope === "unresolved" ? undefined : {
      path: scope === "workspace" ? "D:/workspace/nanobot/src/app.tsx" : "D:/documents/report.tsx",
      relative_path: scope === "workspace" ? path : null,
    }}><Button variant="outline">{path}</Button></FileActions>
    <p className="mt-4 text-xs text-muted-foreground">右键打开复制菜单，也可聚焦文件后按 Shift+F10。</p>
  </>;
}

function WebLinksPreview() {
  const [open, setOpen] = useState(false);
  const [display, setDisplay] = useState<"compact" | "expanded">("compact");
  const message = useRef<HTMLDivElement>(null);
  const links = useMessageWebLinks(message, open);
  return <div className="space-y-4">
    <StatePicker label="链接菜单宽度" value={display} options={["compact", "expanded"]} onChange={setDisplay} />
    <div ref={message} className="text-sm leading-7"><p data-assistant-selectable>
      查看 <WebLink href={`${window.location.origin}/gallery.html`} className="underline underline-offset-4">组件画廊</WebLink>
      {" 和 "}<WebLink href={`${window.location.origin}/brand/nanobot_icon_512.png`} className="underline underline-offset-4">品牌图片</WebLink>。
    </p></div>
    <Button variant="outline" onClick={() => setOpen((value) => !value)}>{open ? "关闭链接菜单" : "查看消息链接"}</Button>
    {open && links.length > 0 ? <div className="rounded-control border p-1">
      <MessageLinksMenu links={links} onBack={() => setOpen(false)} onClose={() => setOpen(false)} expanded={display === "expanded"} />
    </div> : null}
    <p className="text-xs text-muted-foreground">右键链接可复制地址；消息菜单从实际渲染的链接中收集条目。</p>
  </div>;
}

const initialPanes: WorkbenchPane[] = [
  { key: "pane-1", title: "组件设计" }, { key: "pane-2", title: "实现" }, { key: "pane-3", title: "验证" },
];

function WorkbenchPreview() {
  const [panes, setPanes] = useState(initialPanes);
  const [active, setActive] = useState("pane-1");
  const [layout, setLayout] = useState<WorkbenchLayout>("columns");
  const [ratios, setRatios] = useState<number[]>([]);
  return <>
    <StatePicker label="窗格布局" value={layout} options={["columns", "rows", "grid", "bsp", "main-stack"]}
      onChange={(next) => { setLayout(next); setRatios([]); }} />
    <div className="h-[28rem] overflow-hidden rounded-panel border">
      <PaneWorkbench panes={panes} activePaneKey={active} layout={layout} showLayoutControl
        addPaneDisabled={panes.length >= 4} addPaneDisabledLabel="最多四个窗格"
        onActivatePane={setActive} onLayoutChange={(next) => { setLayout(next); setRatios([]); }}
        onAddPane={() => {
          const next = { key: `pane-${panes.length + 1}`, title: "补充笔记" };
          setPanes([...panes, next]); setActive(next.key);
        }}
        onPaneOrderChange={(keys) => setPanes(keys.flatMap((key) => panes.filter((pane) => pane.key === key)))}
        splitRatios={ratios} onSplitRatiosChange={setRatios}
        renderPane={(pane, context) => {
          const header = <div className="pointer-events-auto flex h-10 items-center justify-between gap-2 px-3 text-xs">
            <span>{pane.title}</span>{context.headerActions}
          </div>;
          return <div className="flex min-w-0 flex-1 flex-col gap-3 p-3 pb-8">
            {context.active && context.headerPortalTarget ? createPortal(header, context.headerPortalTarget) : context.active ? header : <p className="h-10 content-center text-xs text-muted-foreground">{pane.title}</p>}
            <label className="grid gap-2 text-xs text-muted-foreground">{pane.title}笔记
              <Textarea defaultValue={`在${pane.title}窗格中编辑笔记。`} /></label>
            <p className="text-xs text-muted-foreground">{context.active ? "当前窗格" : "选择此窗格以激活"}</p>
          </div>;
        }} />
    </div>
    <p role="status" className="mt-4 text-xs text-muted-foreground">当前：{panes.find((pane) => pane.key === active)?.title}。拖动底部手柄移动窗格，拖动边界调整尺寸。</p>
  </>;
}

function ConnectionPreview() {
  const [state, setState] = useState<HostConnectionState>("open");
  return <>
    <StatePicker label="连接状态" value={state} options={["open", "closed", "connecting", "error"]} onChange={setState} />
    <div className="flex flex-wrap gap-8"><Sample label="状态与文字"><HostConnectionStatus state={state} /></Sample>
      <Sample label="紧凑显示"><HostConnectionStatus state={state} compact /></Sample></div>
  </>;
}

function CompatibilityPreview() {
  const [status, setStatus] = useState<HostCompatibility["status"] | "unchecked">("compatible");
  const [open, setOpen] = useState(false);
  const profile: RemoteProfile = {
    id: "gallery-host", name: "开发主机", host: "dev.example", port: 22, ssh_config: "", identity_file: "",
    config_path: "~/.nanobot/config.json", runtime_user: "developer", connected: false,
    compatibility: status === "unchecked" ? undefined : {
      status, client_version: "0.3.0", host_version: status === "update_host" ? "0.2.0" : status === "update_client" ? "0.4.0" : "0.3.0",
    },
  };
  return <>
    <StatePicker label="版本兼容状态" value={status} options={["compatible", "update_host", "update_client", "unknown", "unchecked"]} onChange={setStatus} />
    <Button variant="outline" onClick={() => setOpen(true)}>查看兼容详情</Button>
    <HostCompatibilityDialog profile={open ? profile : undefined} clientVersion="0.3.0" onClose={() => setOpen(false)} />
  </>;
}

const components = "webui/src/components/";
export const shellExamples: ComponentExample[] = [
  { title: "RenameDialog · 分组与项目改名", files: ["RenameDialog"], Preview: RenamePreview,
    description: "预览分组和项目使用的改名弹窗；话题在会话列表中行内改名。", options: "调用方提供 dialogTitle、description 和 placeholder。title 设置初值，onConfirm 接收去除两端空白的标题。空标题无法保存。",
    code: '<RenameDialog open={open} title={title} dialogTitle="Rename group" description="Give this group a name." placeholder="Group name" onCancel={close} onConfirm={rename} />' },
  { title: "DeleteConfirm · 删除确认", files: ["DeleteConfirm"], Preview: DeletePreview,
    description: "切换单个、批量和关联自动任务的删除确认。", options: "count 控制批量文案；automations 展示关联任务、计划与下次运行时间。确认按钮调用 onConfirm。",
    code: '<DeleteConfirm open={open} title="组件设计" count={1} automations={jobs} onCancel={close} onConfirm={remove} />' },
  { title: "Inline tokens · 命令与会话标识", files: ["SlashCommandText", "InlineTokenHighlight", "SessionHandleLabel"], Preview: InlineTokensPreview,
    description: "输入命令与会话标识，观察高亮与稳定的会话颜色。", options: "SlashCommandText 接收 command；InlineTokenHighlight 接收 color 和内容；SessionHandleLabel 根据 id 生成颜色。",
    code: '<SlashCommandText command="/status" />\n<SessionHandleLabel id={session.id}>@design</SessionHandleLabel>\n<InlineTokenHighlight color="var(--inline-token-highlight)">review</InlineTokenHighlight>' },
  { title: "UserMessageText · 消息引用", files: ["UserMessageText"], Preview: UserTextPreview,
    description: "编辑消息，预览技能、应用、MCP 和会话引用。", options: "text 为原始消息；cliApps、mcpPresets 与 sessionMentions 提供可解析引用。技能使用 $name，其他引用使用 @name。",
    code: '<UserMessageText text={text} cliApps={apps} mcpPresets={presets} sessionMentions={sessions} />' },
  { title: "CapabilityMentionToken · 应用引用", files: ["CliAppMentionText"], Preview: CapabilityTokensPreview,
    description: "比较应用、MCP 与会话引用在输入框和消息中的样式。", options: "segment 指定 cli、mcp 或 session 及其元数据；variant 选择 composer 或 message。示例使用本地品牌图片。",
    code: '<CapabilityMentionToken segment={{ kind: "cli", text: "@nanobot", app }} variant="message" />' },
  { title: "Product icons · 产品图标", files: ["icons/product-icons"], Preview: ProductIconsPreview,
    description: "浏览实际产品图标，切换尺寸并选择高亮状态。", options: "图标接受 LucideProps，例如 size、strokeWidth、className。颜色继承 currentColor，按钮提供可访问的动作名称。",
    code: '<ConversationIcon size={20} />\n<SettingsIcon className="text-muted-foreground" />' },
  { title: "StartupShell · 启动占位", files: ["StartupShell"], Preview: StartupPreview,
    description: "预览应用连接时的安静占位布局。", options: "embedded 使用 section，其余情况使用 main。组件持续提供 aria-busy 与加载状态；占位样式来自应用入口。",
    code: '<StartupShell embedded />' },
  { title: "FileActions · 文件菜单", files: ["FileActions"], Preview: FileActionsPreview,
    description: "右键文件，体验完整路径、相对路径和引用文本的复制菜单。", options: "path 为引用文本；metadata 提供完整路径与可选相对路径。画廊直接提供元数据，无需加载文件。",
    code: '<FileActions path="src/app.tsx" metadata={{ path: "D:/workspace/src/app.tsx", relative_path: "src/app.tsx" }}><Button>app.tsx</Button></FileActions>' },
  { title: "Web links · 链接菜单", files: ["WebLink", "MessageLinksMenu"], Preview: WebLinksPreview,
    description: "打开真实链接菜单，选择消息中的链接并复制地址。", options: "WebLink 接收链接属性；useMessageWebLinks 收集消息中实际渲染的链接。MessageLinksMenu 接收条目、返回与关闭回调，expanded 控制宽度。示例链接均指向本地画廊资源。",
    code: '<WebLink href={url}>组件画廊</WebLink>\nconst links = useMessageWebLinks(messageRef, open);\n<MessageLinksMenu links={links} onBack={close} onClose={close} expanded />' },
  { title: "PaneWorkbench · 多窗格", files: ["workbench/PaneWorkbench"], Preview: WorkbenchPreview,
    description: "切换布局、激活窗格、添加窗格并调整位置与尺寸。", options: "panes、activePaneKey、layout 与 splitRatios 由调用方控制。renderPane 提供内容；回调将变更写回本地示例状态。窄屏自动显示当前窗格。",
    code: '<PaneWorkbench panes={panes} activePaneKey={active} layout={layout} showLayoutControl onActivatePane={setActive} onAddPane={addPane} onLayoutChange={setLayout} onPaneOrderChange={reorder} renderPane={renderPane} />' },
  { title: "HostConnectionStatus · 连接状态", files: ["remote/HostConnectionStatus"], Preview: ConnectionPreview,
    description: "切换已连接、断开、连接中和出错状态。", options: "state 控制图标与文字，compact 隐藏可见文字并保留可访问状态和悬浮标题。",
    code: '<HostConnectionStatus state="connecting" />\n<HostConnectionStatus state="open" compact />' },
  { title: "HostCompatibilityDialog · 版本兼容", files: ["remote/HostCompatibilityDialog"], Preview: CompatibilityPreview,
    description: "切换兼容检查结果，查看版本、准备说明和升级指南入口。", options: "profile 存在时打开对话框；compatibility 指定报告状态与版本。onClose 由调用方关闭；此组件只展示信息。",
    code: '<HostCompatibilityDialog profile={selectedProfile} clientVersion="0.3.0" onClose={close} />' },
].map((example) => ({ ...example, files: example.files.map((file) => `${components}${file}.tsx`) }));
