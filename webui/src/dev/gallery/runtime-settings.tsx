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
import type { ThemePreference } from "@/hooks/useTheme";
import type { UpdateChannel } from "@/lib/api";
import type { AutomationChatsPayload, SessionAutomationJob } from "@/lib/types";
import { StatePicker, type ComponentExample } from "./example";
import { useGalleryTranslation } from "./i18n";

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
  const { t, i18n } = useGalleryTranslation();
  const [mode, setMode] = useState<"complete" | "loading" | "error" | "empty" | "unavailable">("complete");
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const result: AutomationRunResult = mode === "loading" || mode === "error"
    ? { status: mode, response: null }
    : { status: "loaded", response: mode === "empty" ? "" : mode === "unavailable" ? null : "## Weekly summary\n\n- **Completed:** component previews\n- **Next:** review the changes" };
  return <><StatePicker label={t("controls.runResult.state")} value={mode} options={["complete", "loading", "error", "empty", "unavailable"]} onChange={setMode} />
    <Button ref={trigger} variant="outline" onClick={() => setOpen(true)}>{t("controls.runResult.view")}</Button>
    <AutomationRunDialogView job={job} run={{ run_at_ms: Date.UTC(2026, 9, 12, 9, 30), status: "ok", duration_ms: 3200 }}
      locale={i18n.language} open={open} result={result} onRetry={() => setMode("complete")} onOpenChange={setOpen}
      onCloseAutoFocus={(event) => { event.preventDefault(); trigger.current?.focus(); }} /></>;
}

function ChatBindingPreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"ready" | "pending" | "load-error" | "conflict">("ready");
  const [task, setTask] = useState(job);
  const [data, setData] = useState(chats);
  const [targetTitle, setTargetTitle] = useState("");
  return <><StatePicker label={t("controls.chatBinding.state")} value={mode} options={["ready", "pending", "load-error", "conflict"]} onChange={setMode} />
    <Dialog><DialogTrigger asChild><Button variant="outline">{t("controls.chatBinding.setChat")}</Button></DialogTrigger>
      <DialogContent aria-describedby={undefined} className="max-w-[520px] gap-0 p-0">
        <AutomationChatBindingView job={mode === "pending" ? { ...task, state: { pending: true } } : task}
          data={data} loadError={mode === "load-error"} showBrandLogos={false} onReload={() => setMode("ready")}
          onSave={async (_task, values) => {
            if (mode === "conflict") throw new Error("automation_chat_conflict");
            setTask((current) => ({ ...current, chat_binding_revision: `${current.chat_binding_revision}-next`, payload: { ...current.payload, message: values.message } }));
          }} onSaved={(target) => {
            setData((current) => ({ ...current, current: target, revision: `${current.revision}-next` }));
            setTargetTitle(target.title);
          }}>{(picker) => <>
            <DialogHeader className="px-6 pb-4 pr-12 pt-5"><DialogTitle>{task.name}</DialogTitle></DialogHeader>
            <div className="px-6 pb-6">{picker}</div>
          </>}</AutomationChatBindingView>
      </DialogContent>
    </Dialog><p role="status" className="mt-4 text-xs text-muted-foreground">{targetTitle ? t("controls.chatBinding.saved", { title: targetTitle }) : t("controls.chatBinding.hint")}</p></>;
}

function AboutPreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"ready" | "checking" | "up-to-date" | "update" | "preview" | "error">("ready");
  const [notice, setNotice] = useState<"updateRequested" | "selectedLink" | null>(null);
  const [channel, setChannel] = useState<UpdateChannel>("stable");
  const result: VersionCheckState = mode === "up-to-date" ? { type: mode }
    : mode === "update" ? { type: mode, latestVersion: "0.3.6", pypiUrl: "https://pypi.org/project/nanobot-ai/" }
      : mode === "preview" ? { type: "update", latestVersion: "0.3.7.dev2026101501",
        releaseUrl: "https://github.com/HKUDS/nanobot/releases" }
      : mode === "error" ? { type: mode, message: t("controls.about.error") } : null;
  return <><StatePicker label={t("controls.about.state")} value={mode} options={["ready", "checking", "up-to-date", "update", "preview", "error"]} onChange={setMode} />
    <AboutSettingsView reportIssueUrl="https://github.com/HKUDS/nanobot/issues/new?template=bug_report.yml"
      versionCheck={<VersionCheckRowView currentVersion="0.3.5" currentCommit="abcdef1234567890" checking={mode === "checking"}
        result={result} onCheck={() => setMode("update")}
        releaseStatus={{ channel, revision: 0, currentVersion: "0.3.5", state: "current" }}
        canChangeChannel onChangeChannel={async (value) => {
          setChannel(value);
        }}
        onRequestUpdate={mode === "preview" ? () => setNotice("updateRequested") : undefined} />}
      starLink={<StarLinkView onActivate={() => setNotice("selectedLink")} />} />
    {notice ? <p role="status" className="mt-4 text-xs text-muted-foreground">{t(`controls.about.${notice}`)}</p> : null}</>;
}

function AppearancePreview() {
  const [theme, setTheme] = useState<ThemePreference>("system");
  const [preferences, setPreferences] = useState(DEFAULT_LOCAL_PREFS);
  return <><AppearanceSettingsView themePreference={theme} onChangeTheme={setTheme}
    localPrefs={preferences} onChangeLocalPrefs={setPreferences} />
    <pre role="status" className="mt-4 overflow-auto rounded-control bg-muted p-4 text-xs">{JSON.stringify({ theme, ...preferences }, null, 2)}</pre></>;
}

function StarInvitationPreview() {
  const { t } = useGalleryTranslation();
  const [mode, setMode] = useState<"ready" | "saving" | "error">("ready");
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState<"dismissed" | "starred" | null>(null);
  return <><StatePicker label={t("controls.starInvitation.state")} value={mode} options={["ready", "saving", "error"]} onChange={setMode} />
    <Button variant="outline" onClick={() => setOpen(true)}>{t("controls.starInvitation.view")}</Button>
    <StarPromptView open={open} saving={mode === "saving"} error={mode === "error"} onOpenChange={setOpen}
      onDismissForever={() => { setNotice("dismissed"); setOpen(false); }}
      onStar={() => { setNotice("starred"); setOpen(false); }} />
    {notice ? <p role="status" className="mt-4 text-xs text-muted-foreground">{t(`controls.starInvitation.${notice}`)}</p> : null}</>;
}

export const runtimeSettingsExamples: ComponentExample[] = [
  { title: "controls.runResult.title", files: ["webui/src/components/settings/system/AutomationRunDialogView.tsx"], Preview: RunResultPreview,
    description: "controls.runResult.description",
    options: "controls.runResult.options",
    code: '<AutomationRunDialogView job={job} run={run} locale="zh-CN" open={open} result={{ status: "loaded", response }} onRetry={retry} onOpenChange={setOpen} onCloseAutoFocus={restoreFocus} />' },
  { title: "controls.chatBinding.title", files: ["webui/src/components/settings/system/AutomationChatBindingView.tsx"], Preview: ChatBindingPreview,
    description: "controls.chatBinding.description",
    options: "controls.chatBinding.options",
    code: '<AutomationChatBindingView job={job} data={chats} loadError={false} showBrandLogos={false} onSave={save} onSaved={updateCurrent} onReload={reload}>{renderDetails}</AutomationChatBindingView>' },
  { title: "controls.about.title", files: ["webui/src/components/settings/overview/AboutSettingsView.tsx", "webui/src/components/settings/overview/VersionCheckRowView.tsx"], Preview: AboutPreview,
    description: "controls.about.description",
    options: "controls.about.options",
    code: '<AboutSettingsView reportIssueUrl={reportIssueUrl} versionCheck={<VersionCheckRowView currentVersion={version} checking={checking} result={result} onCheck={check} />} starLink={<StarLinkView onActivate={star} />} />' },
  { title: "controls.appearance.title", files: ["webui/src/components/settings/overview/AppearanceSettingsView.tsx"], Preview: AppearancePreview,
    description: "controls.appearance.description",
    options: "controls.appearance.options",
    code: '<AppearanceSettingsView themePreference={preference} onChangeTheme={setTheme} localPrefs={preferences} onChangeLocalPrefs={setPreferences} />' },
  { title: "controls.starInvitation.title", files: ["webui/src/components/StarPromptView.tsx"], Preview: StarInvitationPreview,
    description: "controls.starInvitation.description",
    options: "controls.starInvitation.options",
    code: '<StarPromptView open={open} saving={saving} error={error} onOpenChange={setOpen} onDismissForever={dismiss} onStar={openRepository} />' },
];
