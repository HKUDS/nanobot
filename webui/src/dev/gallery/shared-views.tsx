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
import { useGalleryTranslation } from "./i18n";

const markdown = `## A small result\n\nA reply can contain **emphasis**, a list, and inline math $a^2 + b^2 = c^2$.\n\n- Read the source\n- Reuse the existing component\n\n| Item | State |\n| --- | --- |\n| UI | Ready |\n\n\`\`\`python\nprint("Hello, Nanobot")\n\`\`\``;

function MarkdownPreview() {
  const { t } = useGalleryTranslation();
  const [state, setState] = useState<"complete" | "streaming">("complete");
  return <><StatePicker label={t("controls.markdown.state")} value={state} options={["complete", "streaming"]} onChange={setState} />
    <MarkdownText streaming={state === "streaming"}>{state === "streaming" ? markdown.slice(0, 100) : markdown}</MarkdownText></>;
}

function CodePreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"code" | "terminal" | "viewport">("code");
  return <><StatePicker label={t("controls.code.format")} value={mode} options={["code", "terminal", "viewport"]} onChange={setMode} />
    <CodeBlock language={mode === "terminal" ? "ansi" : "tsx"} showLineNumbers={mode !== "terminal"}
      viewportHighlight={mode === "viewport"} wrapLongLines={mode !== "viewport"}
      code={mode === "terminal" ? "\u001b[32mPASS\u001b[0m Component preview ready\n\u001b[33mNOTE\u001b[0m No gateway connection" : '<Button variant="outline" onClick={save}>\n  Save changes\n</Button>'} /></>;
}

function MessagePreview() {
  const { t } = useGalleryTranslation();
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
  return <><StatePicker label={t("controls.message.state")} value={state} options={["answer", "thinking", "streaming", "sending", "failed"]} onChange={setState} />
    <div className="space-y-6"><MessageBubble message={user} />
      {state !== "sending" && state !== "failed" ? <MessageBubble message={assistant} /> : null}</div></>;
}

function ActivityPreview() {
  const { t } = useGalleryTranslation();
  const [state, setState] = useState<"running" | "done" | "error">("running");
  const [expanded, setExpanded] = useState(true);
  return <><StatePicker label={t("controls.activity.state")} value={state} options={["running", "done", "error"]} onChange={setState} />
    <ThinkingReasoningShell active={state === "running"} expanded={expanded} label={t(state === "running" ? "controls.activity.working" : "controls.activity.details")}
      collapseLabel={t("controls.activity.collapse")} onToggle={() => setExpanded((value) => !value)}>
      <ReasoningRow text="Checking the component's inputs and shared styles." streaming={state === "running"} />
      <ActivityStep icon={state === "error" ? CircleAlert : Check} active={state === "running"}
        tone={state === "error" ? "error" : "success"} label={t(state === "error" ? "controls.activity.readError" : "controls.activity.read")} detail="components/ui/button.tsx" />
      <GenericToolRun items={[{ status: state, trace: {
        name: "read_file", family: "read", groupKey: "read", fields: [{ key: "path", value: "webui/src/components/ui/button.tsx" }], collectedSource: false,
      } }]} />
    </ThinkingReasoningShell></>;
}

function FilesPreview() {
  const { t } = useGalleryTranslation();
  const [state, setState] = useState<"done" | "editing" | "error">("done");
  const [operation, setOperation] = useState<"create" | "edit" | "delete">("edit");
  const [display, setDisplay] = useState<"summary" | "diff" | "collapsed_diff">("diff");
  const [opened, setOpened] = useState("");
  const diffs = {
    create: '@@ -0,0 +1 @@\n+export const greeting = "Hello, Nanobot";\n',
    edit: '@@ -1,2 +1,2 @@\n-export const greeting = "Hello";\n+export const greeting = "Hello, Nanobot";\n export const ready = true;\n',
    delete: '@@ -1 +0,0 @@\n-export const greeting = "Hello";\n',
  };
  const edit: FileEditSummary = {
    key: "example-edit", path: "src/greeting.ts", added: operation === "delete" ? 0 : 1, deleted: operation === "create" ? 0 : 1, approximate: false, binary: false,
    status: state, pending: state === "editing", operation, error: state === "error" ? t("controls.files.error") : undefined,
    diff: { format: "unified", text: diffs[operation] },
  };
  return <><StatePicker label={t("controls.files.state")} value={state} options={["done", "editing", "error"]} onChange={setState} />
    <StatePicker label={t("controls.files.operation")} value={operation} options={["create", "edit", "delete"]} onChange={setOperation} />
    <StatePicker label={t("controls.files.display")} value={display} options={["summary", "diff", "collapsed_diff"]} onChange={setDisplay} />
    <FileEditGroup edits={[edit]} displayMode={display} onOpenFilePreview={setOpened} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">{opened ? t("controls.files.selected", { path: opened }) : t("controls.files.hint")}</p></>;
}

// Inline SVG fixtures stay local to the developer gallery and need no network fetch.
const mediaImages = ["#2563eb", "#0d9488", "#9333ea", "#ea580c", "#be123c", "#4f46e5"].map((color, index) => ({
  number: index + 1,
  url: `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="960" height="640" viewBox="0 0 960 640"><rect width="960" height="640" fill="${color}"/><path d="M0 480L240 160L480 480L720 160L960 480" fill="none" stroke="white" stroke-opacity=".35" stroke-width="32"/><circle cx="480" cy="320" r="120" fill="white" fill-opacity=".2"/><text x="480" y="355" text-anchor="middle" font-family="sans-serif" font-size="100" fill="white">${index + 1}</text></svg>`)}`,
}));

function useMediaImages() {
  const { t } = useGalleryTranslation();
  return mediaImages.map(({ number, url }) => ({ name: t("controls.media.study", { count: number }), url }));
}

function ImageGalleryPreview() {
  const { t } = useGalleryTranslation();
  const images = useMediaImages();
  return <div className="space-y-6">
    <Sample label={t("controls.imageGallery.sixImages")}><ImageGallery images={images} /></Sample>
    <Sample label={t("controls.imageGallery.compact")}><ImageGallery images={images} size="compact" /></Sample>
    <p className="text-sm text-muted-foreground">{t("controls.imageGallery.hint")}</p>
  </div>;
}

function ImageLightboxPreview() {
  const { t } = useGalleryTranslation();
  const images = useMediaImages();
  const [index, setIndex] = useState<number | null>(null);
  return <div className="space-y-4">
    <Button variant="outline" onClick={() => setIndex(0)}>{t("controls.imageLightbox.open")}</Button>
    <p className="text-sm text-muted-foreground">{t("controls.imageLightbox.hint")}</p>
    <ImageLightbox images={images.slice(0, 3)} index={index} onIndexChange={setIndex}
      onOpenChange={(open) => { if (!open) setIndex(null); }} />
  </div>;
}

function ZoomableImagePreview() {
  const { t } = useGalleryTranslation();
  const images = useMediaImages();
  return <div className="space-y-4">
    <p className="text-sm text-muted-foreground">{t("controls.zoomableImage.hint")}</p>
    <div className="relative h-[28rem] overflow-hidden rounded-control bg-slate-950">
      <ZoomableImage src={images[0].url} alt={images[0].name} />
    </div>
  </div>;
}

function AttachmentTilePreview() {
  const { t } = useGalleryTranslation();
  const images = useMediaImages();
  return <div className="space-y-6">
    <Sample label={t("controls.attachment.image")}><AttachmentTile attachment={{ kind: "image", ...images[1] }} variant="compact" /></Sample>
    <Sample label={t("controls.attachment.video")}><AttachmentTile attachment={{ kind: "video", name: "sample.webm", url: sampleVideo }} /></Sample>
    <Sample label={t("controls.attachment.file")}><AttachmentTile attachment={{ kind: "file", name: "report.txt", url: "data:text/plain;charset=utf-8,Gallery%20attachment%20example%0A" }} /></Sample>
    <Sample label={t("controls.attachment.unavailable")}>
      <div className="flex flex-wrap gap-3">{(["image", "video", "file"] as const).map((kind) =>
        <AttachmentTile key={kind} attachment={{ kind, name: `${kind}-unavailable` }} />)}</div>
    </Sample>
  </div>;
}

function SettingsPreview() {
  const { t } = useGalleryTranslation();
  const [enabled, setEnabled] = useState(false);
  return <div className="settings-grid space-y-4">
    <SettingsSectionTitle>{t("controls.settingsComposition.preferences")}</SettingsSectionTitle>
    <SettingsGroup><SettingsRow title={t("controls.settingsComposition.keepDrafts")} description={t("controls.settingsComposition.switchHint")}>
      <ToggleButton checked={enabled} onChange={setEnabled} label={t("controls.settingsComposition.keepDrafts")} />
    </SettingsRow><SettingsRow title={t("controls.settingsComposition.projectLabel")}><Input aria-label={t("controls.settingsComposition.projectName")} defaultValue="Nanobot" /></SettingsRow></SettingsGroup>
    <SettingsFeature title={t("controls.settingsComposition.capability")} enabled={enabled} onChange={setEnabled}>
      <SettingsGroup><SettingsRow title={t("controls.settingsComposition.notes")}><Input aria-label={t("controls.settingsComposition.capabilityNotes")} placeholder={t("controls.settingsComposition.localOnly")} /></SettingsRow></SettingsGroup>
    </SettingsFeature>
  </div>;
}

function FileReferencePreview() {
  const { t } = useGalleryTranslation();
  const [selected, setSelected] = useState("");
  return <div className="space-y-4"><FileReferenceChip path="src/components/ui/button.tsx" onOpen={setSelected} />
    <p role="status" className="text-sm text-muted-foreground">{selected || t("controls.fileReference.select")}</p></div>;
}

const components = "webui/src/components/";
export const sharedExamples: ComponentExample[] = [
  { title: "controls.markdown.title", files: ["MarkdownText", "MarkdownTextRenderer"], Preview: MarkdownPreview,
    description: "controls.markdown.description", options: "controls.markdown.options",
    code: '<MarkdownText streaming={running}>{content}</MarkdownText>' },
  { title: "controls.code.title", files: ["CodeBlock", "ViewportCodeRows"], Preview: CodePreview,
    description: "controls.code.description", options: "controls.code.options",
    code: '<CodeBlock language="python" code={source} showLineNumbers />' },
  { title: "controls.math.title", files: ["DisplayMath"], Preview: () => <MarkdownText>{"$$\nE = mc^2\n$$"}</MarkdownText>,
    description: "controls.math.description", options: "controls.math.options", code: '<MarkdownText>{"$$\\nE = mc^2\\n$$"}</MarkdownText>' },
  { title: "controls.message.title", files: ["MessageBubble"], Preview: MessagePreview,
    description: "controls.message.description", options: "controls.message.options",
    code: '<MessageBubble message={{ id: "example", role: "assistant", content: "Hello", createdAt: Date.now() }} />' },
  { title: "controls.activity.title", files: ["thread/activity/ActivityStep", "thread/activity/ReasoningRow", "thread/activity/ThinkingReasoningShell", "thread/activity/GenericToolRun"], Preview: ActivityPreview,
    description: "controls.activity.description", options: "controls.activity.options",
    code: '<ReasoningRow text={reasoning} streaming={running} />\n<ActivityStep label="Read source" detail="button.tsx" active={running} />' },
  { title: "controls.files.title", files: ["thread/activity/FileEditRow", "thread/activity/DiffPair", "thread/activity/DiffSyntaxHighlight"], Preview: FilesPreview,
    description: "controls.files.description", options: "controls.files.options",
    code: '<FileEditGroup edits={edits} displayMode="diff" onOpenFilePreview={openFile} />' },
  { title: "controls.imageGallery.title", files: ["ImageGallery"], Preview: ImageGalleryPreview,
    description: "controls.imageGallery.description", options: "controls.imageGallery.options",
    code: '<ImageGallery images={images} />\n<ImageGallery images={images} size="compact" />' },
  { title: "controls.imageLightbox.title", files: ["ImageLightbox"], Preview: ImageLightboxPreview,
    description: "controls.imageLightbox.description", options: "controls.imageLightbox.options",
    code: '<ImageLightbox images={images} index={index} onIndexChange={setIndex}\n  onOpenChange={(open) => { if (!open) setIndex(null); }} />' },
  { title: "controls.zoomableImage.title", files: ["ZoomableImage"], Preview: ZoomableImagePreview,
    description: "controls.zoomableImage.description", options: "controls.zoomableImage.options",
    code: '<div className="relative h-[28rem] bg-slate-950">\n  <ZoomableImage src={image.url} alt={image.name} />\n</div>' },
  { title: "controls.attachment.title", files: ["AttachmentTile"], Preview: AttachmentTilePreview,
    description: "controls.attachment.description", options: "controls.attachment.options",
    code: '<AttachmentTile attachment={{ kind: "video", name: "sample.webm", url: sampleVideo }} />\n<AttachmentTile attachment={{ kind: "file", name: "report.txt", url: reportUrl }} />\n<AttachmentTile attachment={{ kind: "image", name: "unavailable.png" }} />' },
  { title: "controls.fileReference.title", files: ["FileReferenceChip"], Preview: FileReferencePreview,
    description: "controls.fileReference.description", options: "controls.fileReference.options",
    code: '<FileReferenceChip path="src/app.tsx" onOpen={openFile} />' },
  { title: "controls.settingsComposition.title", files: ["settings/shared/SettingsControls", "settings/shared/SettingsFeature"], Preview: SettingsPreview,
    description: "controls.settingsComposition.description", options: "controls.settingsComposition.options",
    code: '<SettingsGroup><SettingsRow title="Enabled"><ToggleButton checked={enabled} onChange={setEnabled} label="Enabled" /></SettingsRow></SettingsGroup>' },
].map((example) => ({ ...example, files: example.files.map((file) => `${components}${file}.tsx`) }));
