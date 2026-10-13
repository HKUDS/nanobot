import { useState } from "react";
import { Check, CircleAlert } from "lucide-react";

import { AttachmentTile } from "@/components/AttachmentTile";
import { CodeBlock } from "@/components/CodeBlock";
import { ImageLightbox } from "@/components/ImageLightbox";
import { ZoomableImage } from "@/components/ZoomableImage";
import { Button } from "@/components/ui/button";
import sampleVideo from "./fixtures/sample.webm";
import { ImageGallery } from "@/components/ImageGallery";
import { MarkdownText } from "@/components/MarkdownText";
import { MessageBubble } from "@/components/MessageBubble";
import { FileReferenceChip } from "@/components/FileReferenceChip";
import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import { ReasoningRow } from "@/components/thread/activity/ReasoningRow";
import { ThinkingReasoningShell } from "@/components/thread/activity/ThinkingReasoningShell";
import { FileEditGroup, type FileEditSummary } from "@/components/thread/activity/FileEditRow";
import { GenericToolRun } from "@/components/thread/activity/GenericToolRun";
import { SettingsGroup, SettingsRow, SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";
import { SettingsFeature } from "@/components/settings/shared/SettingsFeature";
import { Input } from "@/components/ui/input";
import { ToggleButton } from "@/components/ui/toggle-button";
import type { UIMessage } from "@/lib/types";
import { Sample, StatePicker, type ComponentExample } from "./example";

const markdown = `## A small result\n\nA reply can contain **emphasis**, a list, and inline math $a^2 + b^2 = c^2$.\n\n- Read the source\n- Reuse the existing component\n\n| Item | State |\n| --- | --- |\n| UI | Ready |\n\n\`\`\`python\nprint("Hello, Nanobot")\n\`\`\``;

function MarkdownPreview() {
  const [state, setState] = useState<"complete" | "streaming">("complete");
  return <><StatePicker label="Markdown state" value={state} options={["complete", "streaming"]} onChange={setState} />
    <MarkdownText streaming={state === "streaming"}>{state === "streaming" ? markdown.slice(0, 100) : markdown}</MarkdownText></>;
}

function CodePreview() {
  const [mode, setMode] = useState<"code" | "terminal" | "viewport">("code");
  return <><StatePicker label="Code format" value={mode} options={["code", "terminal", "viewport"]} onChange={setMode} />
    <CodeBlock language={mode === "terminal" ? "ansi" : "tsx"} showLineNumbers={mode !== "terminal"}
      viewportHighlight={mode === "viewport"} wrapLongLines={mode !== "viewport"}
      code={mode === "terminal" ? "\u001b[32mPASS\u001b[0m Component preview ready\n\u001b[33mNOTE\u001b[0m No gateway connection" : '<Button variant="outline" onClick={save}>\n  Save changes\n</Button>'} /></>;
}

function MessagePreview() {
  const [state, setState] = useState<"answer" | "thinking" | "streaming" | "sending" | "failed">("answer");
  const user: UIMessage = {
    id: "gallery-user", role: "user", content: "Show me how this component works.", createdAt: Date.UTC(2026, 0, 1, 12),
    deliveryStatus: state === "sending" ? "sending" : state === "failed" ? "failed" : "accepted",
    deliveryErrorKind: state === "failed" ? "turn_rejected" : undefined,
  };
  const assistant: UIMessage = {
    id: "gallery-assistant", role: "assistant", createdAt: user.createdAt + 1000,
    content: state === "thinking" ? "" : "Here is a **reusable message** with the same typography and actions as the chat.",
    isStreaming: state === "thinking" || state === "streaming",
  };
  return <><StatePicker label="Message state" value={state} options={["answer", "thinking", "streaming", "sending", "failed"]} onChange={setState} />
    <div className="space-y-6"><MessageBubble message={user} />
      {state !== "sending" && state !== "failed" ? <MessageBubble message={assistant} /> : null}</div></>;
}

function ActivityPreview() {
  const [state, setState] = useState<"running" | "done" | "error">("running");
  const [expanded, setExpanded] = useState(true);
  return <><StatePicker label="Activity state" value={state} options={["running", "done", "error"]} onChange={setState} />
    <ThinkingReasoningShell active={state === "running"} expanded={expanded} label={state === "running" ? "Working" : "Activity details"}
      collapseLabel="Collapse" onToggle={() => setExpanded((value) => !value)}>
      <ReasoningRow text="Checking the component's inputs and shared styles." streaming={state === "running"} />
      <ActivityStep icon={state === "error" ? CircleAlert : Check} active={state === "running"}
        tone={state === "error" ? "error" : "success"} label={state === "error" ? "Could not read file" : "Read source"} detail="components/ui/button.tsx" />
      <GenericToolRun items={[{ status: state, trace: {
        name: "read_file", family: "read", groupKey: "read", fields: [{ key: "path", value: "webui/src/components/ui/button.tsx" }], collectedSource: false,
      } }]} />
    </ThinkingReasoningShell></>;
}

function FilesPreview() {
  const [state, setState] = useState<"done" | "editing" | "error">("done");
  const [display, setDisplay] = useState<"summary" | "diff" | "collapsed_diff">("diff");
  const [opened, setOpened] = useState("");
  const edit: FileEditSummary = {
    key: "example-edit", path: "src/greeting.ts", added: 1, deleted: 1, approximate: false, binary: false,
    status: state, pending: state === "editing", operation: "edit", error: state === "error" ? "Example edit could not be applied." : undefined,
    diff: { format: "unified", text: '@@ -1,2 +1,2 @@\n-export const greeting = "Hello";\n+export const greeting = "Hello, Nanobot";\n export const ready = true;\n' },
  };
  return <><StatePicker label="File edit state" value={state} options={["done", "editing", "error"]} onChange={setState} />
    <StatePicker label="Diff display" value={display} options={["summary", "diff", "collapsed_diff"]} onChange={setDisplay} />
    <FileEditGroup edits={[edit]} displayMode={display} onOpenFilePreview={setOpened} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">{opened ? `Selected file: ${opened}` : "Select a file reference to exercise its callback."}</p></>;
}

// Inline SVG fixtures stay local to the developer gallery and need no network fetch.
const mediaImages = ["#2563eb", "#0d9488", "#9333ea", "#ea580c", "#be123c", "#4f46e5"].map((color, index) => ({
  name: `Study ${index + 1} · 色彩练习 ${index + 1}`,
  url: `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="960" height="640" viewBox="0 0 960 640"><rect width="960" height="640" fill="${color}"/><path d="M0 480L240 160L480 480L720 160L960 480" fill="none" stroke="white" stroke-opacity=".35" stroke-width="32"/><circle cx="480" cy="320" r="120" fill="white" fill-opacity=".2"/><text x="480" y="355" text-anchor="middle" font-family="sans-serif" font-size="100" fill="white">${index + 1}</text></svg>`)}`,
}));

function ImageGalleryPreview() {
  return <div className="space-y-6">
    <Sample label="Six images · 六张图片"><ImageGallery images={mediaImages} /></Sample>
    <Sample label="Compact thumbnails · 紧凑缩略图"><ImageGallery images={mediaImages} size="compact" /></Sample>
    <p className="text-sm text-muted-foreground">Select a thumbnail or +2 to view all six images. · 点击缩略图或 +2 查看全部六张图片。</p>
  </div>;
}

function ImageLightboxPreview() {
  const [index, setIndex] = useState<number | null>(null);
  return <div className="space-y-4">
    <Button variant="outline" onClick={() => setIndex(0)}>Open full-screen viewer · 打开全屏预览</Button>
    <p className="text-sm text-muted-foreground">Use previous/next, ←/→ or Home/End; close with × or Escape. · 使用前后按钮、方向键或 Home/End 切图；点击 × 或按 Escape 关闭。</p>
    <ImageLightbox images={mediaImages.slice(0, 3)} index={index} onIndexChange={setIndex}
      onOpenChange={(open) => { if (!open) setIndex(null); }} />
  </div>;
}

function ZoomableImagePreview() {
  return <div className="space-y-4">
    <p className="text-sm text-muted-foreground">Zoom with +/−, double-click, Ctrl+wheel or pinch. Drag or scroll to pan after zooming; click the percentage or press 0 to reset. · 使用 +/−、双击、Ctrl+滚轮或双指缩放；放大后拖动或滚动平移，点击百分比或按 0 复位。</p>
    <div className="relative h-[28rem] overflow-hidden rounded-control bg-slate-950">
      <ZoomableImage src={mediaImages[0].url} alt={mediaImages[0].name} />
    </div>
  </div>;
}

function AttachmentTilePreview() {
  return <div className="space-y-6">
    <Sample label="Image · 图片"><AttachmentTile attachment={{ kind: "image", ...mediaImages[1] }} variant="compact" /></Sample>
    <Sample label="Playable video · 可播放视频"><AttachmentTile attachment={{ kind: "video", name: "sample.webm", url: sampleVideo }} /></Sample>
    <Sample label="Download file · 下载文件"><AttachmentTile attachment={{ kind: "file", name: "report.txt", url: "data:text/plain;charset=utf-8,Gallery%20attachment%20example%0A" }} /></Sample>
    <Sample label="Unavailable attachments (no URL) · 附件不可用（无 URL）">
      <div className="flex flex-wrap gap-3">{(["image", "video", "file"] as const).map((kind) =>
        <AttachmentTile key={kind} attachment={{ kind, name: `${kind}-unavailable` }} />)}</div>
    </Sample>
  </div>;
}

function SettingsPreview() {
  const [enabled, setEnabled] = useState(false);
  return <div className="settings-grid space-y-4">
    <SettingsSectionTitle>Example preferences</SettingsSectionTitle>
    <SettingsGroup><SettingsRow title="Keep drafts" description="A shared setting row with a controlled switch.">
      <ToggleButton checked={enabled} onChange={setEnabled} label="Keep drafts" />
    </SettingsRow><SettingsRow title="Project label"><Input aria-label="Settings project label" defaultValue="Nanobot" /></SettingsRow></SettingsGroup>
    <SettingsFeature title="Example capability" enabled={enabled} onChange={setEnabled}>
      <SettingsGroup><SettingsRow title="Notes"><Input aria-label="Capability notes" placeholder="Local preview only" /></SettingsRow></SettingsGroup>
    </SettingsFeature>
  </div>;
}

function FileReferencePreview() {
  const [selected, setSelected] = useState("");
  return <div className="space-y-4"><FileReferenceChip path="src/components/ui/button.tsx" onOpen={setSelected} />
    <p role="status" className="text-sm text-muted-foreground">{selected || "Select the file reference."}</p></div>;
}

const components = "webui/src/components/";
export const sharedExamples: ComponentExample[] = [
  { title: "MarkdownText · 回复排版", files: ["MarkdownText", "MarkdownTextRenderer"], Preview: MarkdownPreview,
    description: "The production streaming renderer, including tables, code and math.", options: "children is Markdown text. streaming controls incomplete content; onOpenFilePreview belongs to the screen.",
    code: '<MarkdownText streaming={running}>{content}</MarkdownText>' },
  { title: "CodeBlock · 代码展示", files: ["CodeBlock", "ViewportCodeRows"], Preview: CodePreview,
    description: "Syntax highlighting, line numbers, clipboard copying, ANSI output and viewport-aware rows.", options: "code and language supply content; showLineNumbers, wrapLongLines and chrome control presentation. Viewport highlighting requires line numbers and unwrapped lines.",
    code: '<CodeBlock language="python" code={source} showLineNumbers />' },
  { title: "DisplayMath · 数学公式", files: ["DisplayMath"], Preview: () => <MarkdownText>{"$$\nE = mc^2\n$$"}</MarkdownText>,
    description: "The shared fitting wrapper around Markdown's rendered display math.", options: "Use MarkdownText for TeX source. DisplayMath itself accepts already-rendered math nodes and scales them to the available width.", code: '<MarkdownText>{"$$\\nE = mc^2\\n$$"}</MarkdownText>' },
  { title: "MessageBubble · 消息", files: ["MessageBubble"], Preview: MessagePreview,
    description: "User and assistant messages, including thinking and delivery states.", options: "message is a UIMessage projected by the chat runtime. Data and network actions remain outside the renderer.",
    code: '<MessageBubble message={{ id: "example", role: "assistant", content: "Hello", createdAt: Date.now() }} />' },
  { title: "Agent activity · 思考与工具活动", files: ["thread/activity/ActivityStep", "thread/activity/ReasoningRow", "thread/activity/ThinkingReasoningShell", "thread/activity/GenericToolRun"], Preview: ActivityPreview,
    description: "Activity primitives composed into a working, completed or failed sequence.", options: "Pass text, status and controlled expansion. The gateway owns tool execution; these components render its projected state.",
    code: '<ReasoningRow text={reasoning} streaming={running} />\n<ActivityStep label="Read source" detail="button.tsx" active={running} />' },
  { title: "FileEditGroup · 文件修改", files: ["thread/activity/FileEditRow", "thread/activity/DiffPair", "thread/activity/DiffSyntaxHighlight"], Preview: FilesPreview,
    description: "File references, line-change counts and expandable diffs.", options: "edits contains display summaries; displayMode selects summary/diff/collapsed_diff; onOpenFilePreview is supplied by the screen.",
    code: '<FileEditGroup edits={edits} displayMode="diff" onOpenFilePreview={openFile} />' },
  { title: "ImageGallery · 图片缩略图", files: ["ImageGallery"], Preview: ImageGalleryPreview,
    description: "Multi-image layout, thumbnail selection and overflow. · 多图布局、缩略图选择与更多图片。", options: "images supplies URLs and names; size selects large or compact thumbnails, align controls alignment. Only four thumbnails are shown; the composed ImageLightbox includes all viewable images. · images 提供地址和名称，size 控制尺寸，align 控制对齐；最多显示四个缩略图，内置 ImageLightbox 可浏览全部有地址的图片。",
    code: '<ImageGallery images={images} />\n<ImageGallery images={images} size="compact" />' },
  { title: "ImageLightbox · 全屏预览", files: ["ImageLightbox"], Preview: ImageLightboxPreview,
    description: "Controlled full-screen viewing and image navigation. · 受控全屏预览与多图切换。", options: "index is null when closed. The caller owns index and open callbacks; ImageLightbox composes ZoomableImage and resets the view on image changes. · index 为 null 时关闭；调用方管理索引与开关回调，ImageLightbox 内置 ZoomableImage，切图时重置缩放。",
    code: '<ImageLightbox images={images} index={index} onIndexChange={setIndex}\n  onOpenChange={(open) => { if (!open) setIndex(null); }} />' },
  { title: "ZoomableImage · 单图缩放", files: ["ZoomableImage"], Preview: ZoomableImagePreview,
    description: "Single-image zoom, bounded panning and gestures. · 单图缩放、边界内平移与手势。", options: "src and alt supply one image. Place it in a positioned container with a defined height; remount when changing images. Focus the viewport for +, − and 0 keyboard controls. · src 和 alt 提供单张图片；容器须有定位和明确高度，换图时重新挂载。聚焦图片区域后可用 +、− 和 0 操作。",
    code: '<div className="relative h-[28rem] bg-slate-950">\n  <ZoomableImage src={image.url} alt={image.name} />\n</div>' },
  { title: "AttachmentTile · 附件", files: ["AttachmentTile"], Preview: AttachmentTilePreview,
    description: "Image preview, video playback, file download and unavailable attachments. · 图片预览、视频播放、文件下载与不可用附件。", options: "attachment.kind selects image, video or file. Images open ImageLightbox, videos use native controls, files use download links. Missing URLs render unavailable tiles; failed image loads also render an unavailable tile. · attachment.kind 区分图片、视频与文件；图片打开 ImageLightbox，视频使用原生控件，文件提供下载链接。无地址或图片加载失败时显示不可用附件。",
    code: '<AttachmentTile attachment={{ kind: "video", name: "sample.webm", url: sampleVideo }} />\n<AttachmentTile attachment={{ kind: "file", name: "report.txt", url: reportUrl }} />\n<AttachmentTile attachment={{ kind: "image", name: "unavailable.png" }} />' },
  { title: "FileReferenceChip · 文件引用", files: ["FileReferenceChip"], Preview: FileReferencePreview,
    description: "A file reference with a caller-owned open action.", options: "path supplies the label; onOpen supplies the action. The component does not decide workspace permissions.",
    code: '<FileReferenceChip path="src/app.tsx" onOpen={openFile} />' },
  { title: "Settings composition · 设置组件", files: ["settings/shared/SettingsControls", "settings/shared/SettingsFeature"], Preview: SettingsPreview,
    description: "The actual settings row/group/capability components composed with shared controls.", options: "The containing settings controller owns values and persistence. A gallery callback updates only local preview state.",
    code: '<SettingsGroup><SettingsRow title="Enabled"><ToggleButton checked={enabled} onChange={setEnabled} label="Enabled" /></SettingsRow></SettingsGroup>' },
].map((example) => ({ ...example, files: example.files.map((file) => `${components}${file}.tsx`) }));
