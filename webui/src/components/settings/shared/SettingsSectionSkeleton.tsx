import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isCapabilitySection, type SettingsSectionKey } from "@/components/settings/contracts";
import { SettingsGroup } from "@/components/settings/shared/SettingsControls";
import { SkeletonStatus } from "@/components/settings/shared/SkeletonStatus";
import { RUNTIME_CONFIG_FIELDS, RUNTIME_CONFIG_GROUPS, type RuntimeConfigPage } from "@/components/settings/system/runtime-config-fields";
import { cn } from "@/lib/utils";

type Control = "switch" | "input" | "duration" | "segments" | "theme" | "edit" | "text" | "feature";
const block = "rounded bg-muted-foreground/20";

function Title({ heading = false }: { heading?: boolean }) {
  return <div className={cn("settings-section-title flex h-5 items-center", heading && "!m-0 !p-0")}>
    <div className={cn(block, "h-3 w-24")} />
  </div>;
}

function Row({ control }: { control: Control }) {
  const toggle = control === "switch" || control === "feature";
  return <div data-settings-skeleton-row className="settings-row">
    <div className="flex h-5 items-center"><div className={cn(block, "h-3.5 w-32 max-w-full")} /></div>
    <div className="settings-control">
      {control === "feature" ? <div className={cn(block, "mr-3 h-3 w-14")} /> : null}
      {control === "duration" ? <div className="w-full"><div className={cn(block, "h-9 w-full rounded-full")} /><div className="mt-1.5 flex h-4 items-center"><div className={cn(block, "h-2.5 w-4/5 opacity-60")} /></div></div> : <div data-skeleton-switch={toggle ? "" : undefined} className={cn(block,
        toggle ? "h-5 w-9 shrink-0 rounded-full" : control === "input" ? "h-9 w-full rounded-full"
          : control === "segments" || control === "theme" ? "segmented-control w-44 rounded-full" : control === "edit" ? "ml-auto h-9 w-9 rounded-full" : "h-[19.5px] w-24",
        control === "segments" && "h-[34px]", control === "theme" && "h-8",
      )} />}
    </div>
  </div>;
}

function Group({ controls }: { controls: Control[] }) {
  return <section><Title /><SettingsGroup>{controls.map((control, index) => <Row key={index} control={control} />)}</SettingsGroup></section>;
}

function RuntimeGroups({ page }: { page: RuntimeConfigPage }) {
  return <>{RUNTIME_CONFIG_GROUPS.filter((group) => group.page === page).map((group) => group.id === "chat"
    ? <Group key={group.id} controls={["switch", "segments"]} />
    : <Group key={group.id} controls={RUNTIME_CONFIG_FIELDS.filter((field) => field.group === group.id && (!field.when || field.when.value === true)).map((field) =>
      field.kind === "boolean" || field.kind === "toggle" ? "switch" : field.kind === "list" ? "edit" : field.kind === "duration" ? "duration" : "input",
    )} />)}</>;
}

export function SettingsSectionSkeleton({ section, showRestart = false }: { section: SettingsSectionKey; showRestart?: boolean }) {
  const { t } = useTranslation();
  let content: ReactNode = null;
  if (isCapabilitySection(section)) content = <>
    <div className="settings-section-heading"><Title heading /></div>
    {[0, 1, 2, 3].map((index) => <SettingsGroup key={index}><Row control={index === 3 ? "switch" : "feature"} /></SettingsGroup>)}
  </>;
  else switch (section) {
    case "appearance":
      content = <><Group controls={["theme", "input"]} /><Group controls={["segments", "segments", "switch", "switch"]} /></>;
      break;
    case "notifications":
      content = <section><Title /><SettingsGroup>
        <Row control="switch" />
        <div className="settings-list-inset" aria-hidden="true"><div className="border-t border-border/40" /></div>
        <Row control="switch" />
      </SettingsGroup><p className="settings-list-inset mt-3 text-[12px] leading-5"><span className={cn(block, "text-transparent")}>{t("settings.notifications.pageRequired")}</span></p></section>;
      break;
    case "overview":
      content = <>
        <section className="rounded-panel bg-settings-surface p-6">
          <div className="flex h-5 items-center"><div className={cn(block, "h-3.5 w-24")} /></div>
          <div className="mt-2 flex h-9 items-center"><div className={cn(block, "h-7 w-20")} /></div>
          <div className="mt-5 flex h-7 items-center"><div className={cn(block, "h-3.5 w-3/5")} /></div>
        </section>
        {[1, 3].map((count) => <section key={count}><Title /><SettingsGroup>{Array.from({ length: count }, (_, index) =>
          <div key={index} data-overview-skeleton-row className="flex min-h-[68px] items-center gap-3 px-4 py-3.5 sm:px-5">
            <div className={cn(block, "h-9 w-9 shrink-0 rounded-control")} /><div className={cn(block, "h-3.5 w-28")} />
            <div className={cn(block, "ml-auto h-3 w-20")} /><div className="h-4 w-4" />
          </div>,
        )}</SettingsGroup></section>)}
      </>;
      break;
    case "models":
      content = <section><Title /><SettingsGroup>
        <div data-model-preset-skeleton className="settings-list-inset grid grid-cols-[auto_minmax(0,1fr)_auto_auto_auto] items-center gap-x-3 py-5 sm:py-6">
          <div className={cn(block, "h-[54.25px] w-[54.25px] shrink-0 rounded-control sm:h-[59.75px] sm:w-[59.75px]")} />
          <div className="min-w-0"><div className="flex h-[30.25px] items-center sm:h-[35.75px]"><div className={cn(block, "h-4 w-2/3 sm:h-5")} /></div><div className="mt-1 flex h-5 items-center"><div className={cn(block, "h-3 w-4/5 opacity-60")} /></div></div>
          <div className="text-[13px]"><span className="invisible hidden sm:inline">{t("settings.configure")}</span><div className="h-4 w-4 sm:hidden" /></div>
          <div className="h-4 w-4" /><div className={cn(block, "h-5 w-[38px] shrink-0 rounded-full")} />
        </div>
      </SettingsGroup><div className="settings-footer flex items-center justify-between gap-2"><div className="flex h-11 items-center sm:h-9"><div className={cn(block, "h-3 w-20")} /></div><div className="flex h-11 items-center sm:h-9"><div className={cn(block, "h-3 w-28")} /></div></div></section>;
      break;
    case "runtime":
      content = <><RuntimeGroups page="runtime" /><Group controls={["input", "segments", "input", "input"]} /><Group controls={["input"]} /><Group controls={showRestart ? ["text", "text", "input"] : ["text", "text"]} /></>;
      break;
    case "advanced":
      content = <RuntimeGroups page="advanced" />;
      break;
    case "about":
      content = <>
        <div className="flex flex-col items-center gap-4 py-6">
          <img src="/brand/nanobot_mark.svg" alt="" className="h-16 w-16" />
          <img src="/brand/nanobot_wordmark.svg" alt="" className="h-auto w-40 dark:brightness-150" />
          <div className="flex flex-col items-center gap-4"><div className="mt-0.5 flex h-5 items-center"><div className={cn(block, "h-3 w-20")} /></div><div className={cn(block, "h-9 w-36 rounded-full")} /></div>
        </div>
        <SettingsGroup>{[0, 1, 2].map((index) => <div key={index} className="settings-list-row flex items-center gap-3"><div className={cn(block, "h-4 w-4")} /><div className={cn(block, "h-3.5 w-28")} /></div>)}</SettingsGroup>
      </>;
      break;
  }
  return <SkeletonStatus label={t("settings.status.loading")} className="settings-stack">{content}</SkeletonStatus>;
}
