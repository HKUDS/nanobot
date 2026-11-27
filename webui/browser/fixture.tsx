import type { ReactElement } from "react";
import { createRoot } from "react-dom/client";

import { TooltipProvider } from "@/components/ui/tooltip";
import { initializeI18n, setAppLanguage } from "@/i18n";
import { LOCALE_STORAGE_KEY, normalizeLocale } from "@/i18n/config";
import { installFocusModality } from "@/lib/focus-modality";
import "../src/globals.css";

installFocusModality();

const parameters = new URLSearchParams(location.search);
const fixtureCase = parameters.get("case");
const historyPreview = parameters.get("preview");

async function withClient(fixture: ReactElement, webuiCapabilities?: string[]) {
  const [{ ClientProvider }, { NanobotClient }] = await Promise.all([
    import("@/providers/ClientProvider"),
    import("@/lib/nanobot-client"),
  ]);
  const client = new NanobotClient({ url: "ws://127.0.0.1:8765", reconnect: false });
  return <ClientProvider client={client} token="fixture" webuiCapabilities={webuiCapabilities}>{fixture}</ClientProvider>;
}

// Load and install only the selected scene's mocks before i18n and React mount.
async function loadFixture() {
  switch (fixtureCase) {
    case "model-options": {
      const { ModelOptionsFixture, installModelOptionsPreviewApi } = await import("./model-options-fixture");
      installModelOptionsPreviewApi();
      return <ModelOptionsFixture />;
    }
    case "toast": {
      const { ToastFixture } = await import("./toast-fixture");
      return <ToastFixture parameters={parameters} />;
    }
    case "session-transition": {
      const { installSessionTransitionPreviewApi, SessionTransitionFixture } = await import("./session-transition-fixture");
      if (parameters.has("preview")) installSessionTransitionPreviewApi();
      if (parameters.has("narrow")) {
        const widePreview = new URL(location.href);
        widePreview.searchParams.delete("narrow");
        return <iframe title="Narrow goal preview" src={widePreview.href} style={{ display: "block", margin: "0 auto", height: "100dvh", width: "100%", maxWidth: 390, border: 0 }} />;
      }
      return <SessionTransitionFixture />;
    }
    case "continuity": {
      const { ContinuityFixture } = await import("./continuity-fixture");
      return <ContinuityFixture />;
    }
    case "appearance": {
      const { AppearanceFixture } = await import("./appearance-fixture");
      return <AppearanceFixture />;
    }
    case "loaded-session-search": {
      const { LoadedSessionSearchFixture } = await import("./loaded-session-search-fixture");
      return <LoadedSessionSearchFixture />;
    }
    case "subagent-dock": {
      const { installSubagentDockApi, SubagentDockFixture } = await import("./subagent-dock-fixture");
      installSubagentDockApi();
      return <SubagentDockFixture parameters={parameters} />;
    }
    case "attachments": {
      const { AttachmentLayoutFixture } = await import("./attachment-layout-fixture");
      return <AttachmentLayoutFixture />;
    }
    case "theme-toggle": {
      const { ThemeToggleFixture } = await import("./theme-toggle-fixture");
      return withClient(<ThemeToggleFixture />);
    }
    case "mobile-chat-layout": {
      const { MobileChatLayoutFixture } = await import("./mobile-chat-layout-fixture");
      return withClient(<MobileChatLayoutFixture parameters={parameters} />);
    }
    case "long-user-message": {
      const { LongUserMessageFixture } = await import("./long-user-message-fixture");
      return withClient(<LongUserMessageFixture parameters={parameters} />);
    }
    case "composer-action": {
      const { ComposerActionFixture, installMissingMicrophonePreview } = await import("./composer-action-fixture");
      if (parameters.get("voiceError") === "noDevice") installMissingMicrophonePreview();
      return <ComposerActionFixture parameters={parameters} />;
    }
    case "workspace-alignment": {
      const { WorkspaceAlignmentFixture } = await import("./workspace-alignment-fixture");
      return <WorkspaceAlignmentFixture parameters={parameters} />;
    }
    case "queued-guidance": {
      const { QueuedGuidanceFixture } = await import("./queued-guidance-fixture");
      return <QueuedGuidanceFixture />;
    }
    case "code-highlighting": {
      const { CodeHighlightingFixture } = await import("./code-highlighting-fixture");
      return <CodeHighlightingFixture />;
    }
    case "file-diff": {
      const { FileDiffFixture } = await import("./file-diff-fixture");
      return <FileDiffFixture shiki={parameters.has("shiki")} />;
    }
    case "file-edit-path": {
      const { FileEditPathFixture } = await import("./file-edit-path-fixture");
      return <FileEditPathFixture />;
    }
    case "answer-order": {
      const { AnswerOrderFixture } = await import("./answer-order-fixture");
      return <AnswerOrderFixture />;
    }
    case "activity-logos": {
      const { ActivityLogosFixture } = await import("./activity-logos-fixture");
      return <ActivityLogosFixture parameters={parameters} />;
    }
    case "activity-wheel": {
      const { ActivityWheelFixture } = await import("./activity-wheel-fixture");
      return <ActivityWheelFixture />;
    }
    case "exec-session": {
      const { ExecSessionFixture } = await import("./exec-session-fixture");
      return <ExecSessionFixture />;
    }
    case "sidebar-activity": {
      const { SidebarActivityFixture } = await import("./sidebar-activity-fixture");
      return <SidebarActivityFixture />;
    }
    case "chat-failure": {
      const { ChatFailureFixture } = await import("./chat-failure-fixture");
      return <ChatFailureFixture parameters={parameters} />;
    }
    case "display-math": {
      const { DisplayMathFixture } = await import("./display-math-fixture");
      return <DisplayMathFixture />;
    }
    case "markdown-dollar-refs": {
      const { MarkdownDollarRefsFixture } = await import("./markdown-dollar-refs-fixture");
      return <MarkdownDollarRefsFixture />;
    }
    case "code-wrapping": {
      const { CodeWrappingFixture } = await import("./code-wrapping-fixture");
      return <CodeWrappingFixture />;
    }
    case "typography": {
      const { TypographyFixture } = await import("./typography-fixture");
      return withClient(<TypographyFixture />);
    }
    case "inline-references": {
      const { InlineReferencesFixture } = await import("./inline-references-fixture");
      return withClient(<InlineReferencesFixture />);
    }
    case "inline-file-reference": {
      const { InlineFileReferenceFixture } = await import("./inline-file-reference-fixture");
      return <InlineFileReferenceFixture />;
    }
    case "idle-compaction": {
      const { IdleCompactionFixture, installIdleCompactionApi } = await import("./idle-compaction-fixture");
      installIdleCompactionApi();
      return <IdleCompactionFixture />;
    }
    case "history-hydration": {
      const { HistoryHydrationFixture } = await import("./history-hydration-fixture");
      return <HistoryHydrationFixture />;
    }
    case "history-boundary": {
      const { HistoryBoundaryFixture } = await import("./history-boundary-fixture");
      if (historyPreview === "slow" || historyPreview === "fast" || historyPreview === "pages" || historyPreview === "error") {
        const { installHistoryBoundaryPreviewApi } = await import("./history-boundary-preview");
        installHistoryBoundaryPreviewApi(historyPreview);
      }
      return withClient(<HistoryBoundaryFixture local={parameters.has("local")} navigate={parameters.has("navigate")} tasks={parameters.has("tasks")} />, ["webui.prompt-navigation.v1"]);
    }
    case "diagrams": {
      const { DiagramFixture } = await import("./diagram-fixture");
      return <DiagramFixture parameters={parameters} />;
    }
    case "thread-loading": {
      const { ThreadLoadingFixture } = await import("./thread-loading-fixture");
      return withClient(<ThreadLoadingFixture />);
    }
    case "new-chat-skeleton": {
      const { NewChatSkeletonFixture } = await import("./new-chat-skeleton-fixture");
      return withClient(<NewChatSkeletonFixture />);
    }
    case "skeleton-additions": {
      const { installSkeletonPreviewApi, SkeletonAdditionsFixture } = await import("./skeleton-additions-fixture");
      installSkeletonPreviewApi();
      return withClient(<SkeletonAdditionsFixture />, parameters.has("sandboxSettings") ? ["webui.sandbox-settings.v1"] : []);
    }
    case "skeleton": {
      const { SkeletonFixture } = await import("./skeleton-fixture");
      return withClient(<SkeletonFixture surface={parameters.get("surface") ?? "skills"} loading={parameters.has("loading")} />);
    }
    case "tools-catalog": {
      const { installToolsCatalogPreviewApi, ToolsCatalogFixture } = await import("./tools-catalog-fixture");
      installToolsCatalogPreviewApi();
      return withClient(<ToolsCatalogFixture />);
    }
    case "apps": {
      const { AppsFixture } = await import("./apps-fixture");
      return withClient(<AppsFixture />);
    }
    case "rail": {
      const { RailFixture } = await import("./rail-fixture");
      return withClient(<RailFixture />, ["webui.prompt-navigation.v1"]);
    }
    case "settings-icon": {
      const [{ Button }, { SettingsIcon }] = await Promise.all([
        import("@/components/ui/button"),
        import("@/components/icons/product-icons"),
      ]);
      return <Button variant="icon" size="icon" aria-label="Settings"><SettingsIcon className="h-4 w-4" /></Button>;
    }
    case "session-messages": {
      const { SessionMessagesFixture } = await import("./history-fixture");
      return <SessionMessagesFixture />;
    }
    case "history": {
      const { HistoryFixture } = await import("./history-fixture");
      return <HistoryFixture />;
    }
    default: {
      const { TallDialogFixture } = await import("./tall-dialog-fixture");
      return <TallDialogFixture placement={parameters.get("placement") === "bottom" ? "bottom" : "center"} />;
    }
  }
}

const fixture = await loadFixture();
await initializeI18n();
if (fixtureCase === "activity-wheel") await setAppLanguage("zh-CN");
if (fixtureCase === "toast" && parameters.has("lang")) {
  const previous = localStorage.getItem(LOCALE_STORAGE_KEY);
  await setAppLanguage(normalizeLocale(parameters.get("lang")));
  if (previous === null) localStorage.removeItem(LOCALE_STORAGE_KEY);
  else localStorage.setItem(LOCALE_STORAGE_KEY, previous);
}
if ((["appearance", "chat-failure", "long-user-message", "session-transition", "tools-catalog"].includes(fixtureCase ?? "") || historyPreview) && parameters.has("lang")) {
  await setAppLanguage(normalizeLocale(parameters.get("lang")));
}
createRoot(document.getElementById("root")!).render(<TooltipProvider>{fixture}</TooltipProvider>);
