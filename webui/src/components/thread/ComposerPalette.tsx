import { useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import type { TFunction } from "i18next";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ActivityIcon, ArchiveIcon, CompactIcon, DreamIcon, DreamLogIcon, EditIcon,
  GoalIcon, HelpIcon, HistoryIcon, MemoryIcon, ModelsIcon, NewChatIcon,
  PairingIcon, PromptTemplateIcon, RestartIcon, RestoreMemoryIcon,
  RestrictedAccessIcon, SkillsIcon, StatusIcon, StopIcon, ToolRunIcon, TriggerIcon,
} from "@/components/icons/product-icons";
import { INLINE_REFERENCE_HIGHLIGHT_COLOR, INLINE_TOKEN_HIGHLIGHT_COLOR } from "@/components/InlineTokenHighlight";
import {
  floatingItemClassName,
  floatingItemFocusClassName,
  floatingSurfaceElevationClassName,
} from "@/components/ui/floating-surface";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { useOverlaySurfaceRef } from "@/lib/dom-overlays";
import { logoFallbackUrls } from "@/lib/provider-brand";
import { sessionHandleColor } from "@/lib/session-handle";
import type { SessionMention } from "@/lib/types";
import { cn } from "@/lib/utils";
import "./composer-palette.css";

const PALETTE_CHROME_PX = 12;

const COMMAND_ICONS: Record<string, LucideIcon> = {
  activity: ActivityIcon, archive: ArchiveIcon, "book-open": SkillsIcon,
  brain: MemoryIcon, "circle-help": HelpIcon, history: HistoryIcon,
  "rotate-cw": RestartIcon, shield: RestrictedAccessIcon, sparkles: DreamIcon,
  square: StopIcon, "square-pen": EditIcon, "undo-2": RestoreMemoryIcon,
  zap: TriggerIcon, "file-text": PromptTemplateIcon, wrench: ToolRunIcon,
};

const BUILTIN_COMMAND_ICONS: Record<string, LucideIcon> = {
  "/new": NewChatIcon, "/compact": CompactIcon, "/stop": StopIcon,
  "/restart": RestartIcon, "/status": StatusIcon, "/model": ModelsIcon,
  "/goal": GoalIcon, "/trigger": TriggerIcon,
  "/dream": DreamIcon, "/dream-log": DreamLogIcon, "/dream-restore": RestoreMemoryIcon,
  "/dream-prompt": PromptTemplateIcon, "/evaluator-prompt": PromptTemplateIcon,
  "/skill": SkillsIcon, "/help": HelpIcon, "/pairing": PairingIcon,
};

export type SlashPalettePlacement = "above" | "below" | "beside";
export interface SlashPaletteLayout { placement: SlashPalettePlacement; maxHeight: number; }
export type SkillSourceBucket = "workspace" | "builtin" | "other";

export interface SlashPaletteCommand {
  command: string;
  title: string;
  description: string;
  icon: string;
  argHint?: string;
  detail: string;
  badge?: string;
  recent: boolean;
}

export interface SkillPaletteItem {
  name: string;
  command: string;
  description: string;
  source: string;
  recent: boolean;
}

export type MentionCandidate = { name: string; displayName: string } & (
  | { kind: "session"; mention: SessionMention }
  | { kind: "cli" | "mcp"; brandColor: string | null; logoUrl: string | null; initials: string }
);

const SKILL_SOURCE_META: Record<SkillSourceBucket, { sourceKey: string; groupKey: string; fallback: string }> = {
  workspace: { sourceKey: "settings.skills.sourceWorkspace", groupKey: "settings.skills.customGroup", fallback: "Custom" },
  builtin: { sourceKey: "settings.skills.sourceBuiltin", groupKey: "settings.skills.builtinGroup", fallback: "Built-in" },
  other: { sourceKey: "settings.skills.otherGroup", groupKey: "settings.skills.otherGroup", fallback: "Other" },
};

const groupHeaderClass = "px-2.5 pb-1 pt-1 text-[11px] font-medium tracking-normal text-muted-foreground/75";
const badgeClass =
  "inline-flex shrink-0 items-center rounded-full bg-foreground/[0.06] px-1.5 py-0.5 text-[10.5px] font-medium leading-none text-muted-foreground dark:bg-white/[0.08]";

export function slashCommandI18nKey(command: string): string {
  return command.replace(/^\//, "").replace(/-/g, "_");
}

export function skillSourceBucket(source: string): SkillSourceBucket {
  return source === "workspace" || source === "builtin" ? source : "other";
}

function skillBucketText(sourceOrBucket: string, kind: "sourceKey" | "groupKey", t: TFunction): string {
  const meta = SKILL_SOURCE_META[skillSourceBucket(sourceOrBucket)];
  return t(meta[kind], { defaultValue: meta.fallback });
}

function resolveSlashCommand(command: SlashPaletteCommand, t: TFunction) {
  const key = slashCommandI18nKey(command.command);
  const title = t(`thread.composer.slash.commands.${key}.title`, { defaultValue: command.title });
  const description = t(`thread.composer.slash.commands.${key}.description`, { defaultValue: command.description });
  const detail = command.detail || description;
  return {
    Icon: BUILTIN_COMMAND_ICONS[command.command] ?? COMMAND_ICONS[command.icon] ?? HelpIcon,
    title,
    description,
    detail,
    showDetail: Boolean(detail && detail !== title),
    hasLiveDetail: Boolean(command.detail && command.detail !== description),
    badgeLabel: command.badge ?? (command.recent ? t("thread.composer.slash.badges.recent") : null),
    commandLabel: command.argHint ? `${command.command} ${command.argHint}` : command.command,
  };
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  if (!query) return text;
  const index = text.toLowerCase().indexOf(query);
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded-[3px] bg-foreground/[0.09] text-inherit dark:bg-white/[0.15]">
        {text.slice(index, index + query.length)}
      </mark>
      {text.slice(index + query.length)}
    </>
  );
}

function SelectionChevron({ selected, className }: { selected: boolean; className?: string }) {
  return (
    <ChevronRight
      aria-hidden
      className={cn(
        "hidden h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-opacity duration-100 sm:block",
        selected ? "opacity-100" : "opacity-0",
        className,
      )}
    />
  );
}

function PaletteKeyHint({ text }: { text: string }) {
  const separator = text.indexOf(" ");
  if (separator < 0) return <span className="text-[11px] text-muted-foreground/70">{text}</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground/70">
      <kbd className="rounded-[5px] border border-border/75 bg-background/90 px-1.5 py-[1px] font-sans text-[10px] font-medium leading-4 text-foreground/75 shadow-[0_1px_0_rgba(15,23,42,0.06)] dark:border-white/[0.10] dark:bg-white/[0.06] dark:shadow-none">
        {text.slice(0, separator)}
      </kbd>
      <span>{text.slice(separator + 1)}</span>
    </span>
  );
}

function PalettePreviewShell({
  itemKey,
  icon,
  header,
  alignIcon = "center",
  children,
}: {
  itemKey: string;
  icon: ReactNode;
  header: ReactNode;
  alignIcon?: "center" | "start";
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <>
      <div
        key={itemKey}
        className="composer-palette-preview-body inset-scrollbar min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-5 py-4"
      >
        <div className={cn("flex gap-3", alignIcon === "start" ? "items-start" : "items-center")}>
          <span className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-background text-foreground ring-1 ring-border/70 shadow-[0_1px_2px_rgba(15,23,42,0.05)] dark:bg-white/[0.06] dark:ring-white/[0.09] dark:shadow-none",
            alignIcon === "start" && "mt-0.5",
          )}>
            {icon}
          </span>
          <div className="min-w-0 flex-1">{header}</div>
        </div>
        {children}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/45 px-5 py-2.5 dark:border-white/[0.06]">
        <PaletteKeyHint text={t("thread.composer.slash.navigateHint")} />
        <PaletteKeyHint text={t("thread.composer.slash.selectHint")} />
        <PaletteKeyHint text={t("thread.composer.slash.closeHint")} />
      </div>
    </>
  );
}

function PaletteOption({
  index,
  selected,
  ariaLabel,
  className,
  onHover,
  onChoose,
  children,
}: {
  index: number;
  selected: boolean;
  ariaLabel: string;
  className: string;
  onHover: (index: number) => void;
  onChoose: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="option"
      data-palette-index={index}
      aria-selected={selected}
      aria-label={ariaLabel}
      onMouseEnter={() => onHover(index)}
      onMouseDown={(e) => {
        e.preventDefault();
        onChoose();
      }}
      className={cn(
        floatingItemClassName,
        floatingItemFocusClassName,
        "flex w-full min-w-0 overflow-hidden px-2.5 text-left transition-colors duration-100",
        selected
          ? "bg-foreground/[0.06] text-foreground dark:bg-black/[0.16]"
          : "text-foreground/90 hover:bg-foreground/[0.04] dark:hover:bg-black/[0.10]",
        className,
      )}
    >
      {children}
    </button>
  );
}

function ComposerPaletteSurface({
  ariaLabel,
  layout,
  isHero,
  selectedIndex,
  preview,
  children,
}: {
  ariaLabel: string;
  layout: SlashPaletteLayout;
  isHero: boolean;
  selectedIndex: number;
  preview?: ReactNode;
  children: ReactNode;
}) {
  const showSplitPreview = Boolean(preview) && layout.placement !== "beside";
  const listMaxHeight = Math.max(0, showSplitPreview ? layout.maxHeight : layout.maxHeight - PALETTE_CHROME_PX);
  const listRef = useRef<HTMLDivElement | null>(null);
  const surfaceRef = useOverlaySurfaceRef<HTMLDivElement>("overlay");

  useLayoutEffect(() => {
    const option = listRef.current?.querySelector<HTMLElement>(`[data-palette-index="${selectedIndex}"]`);
    if (typeof option?.scrollIntoView === "function") option.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  return (
    <div
      ref={surfaceRef}
      role="listbox"
      aria-label={ariaLabel}
      data-placement={layout.placement}
      style={{ maxHeight: layout.maxHeight }}
      className={cn(
        floatingSurfaceElevationClassName,
        "composer-palette-surface z-30 overflow-hidden rounded-floating ring-1 ring-border/75 dark:ring-white/[0.08]",
        "shadow-[0_12px_36px_-8px_rgba(15,23,42,0.12),0_2px_10px_-2px_rgba(15,23,42,0.06)] dark:shadow-[0_16px_40px_-6px_rgba(0,0,0,0.44)]",
        showSplitPreview
          ? "grid grid-cols-1 p-0 sm:grid-cols-[minmax(0,16.5rem)_minmax(0,1fr)] md:grid-cols-[minmax(0,18.5rem)_minmax(0,1fr)]"
          : "p-1.5",
        layout.placement === "beside"
          ? "relative col-start-2 row-start-1 w-full"
          : cn(
              "absolute inset-x-0 mx-auto",
              layout.placement === "above" ? "bottom-full mb-2" : "top-full mt-2",
              isHero
                ? "w-full max-w-[var(--composer-content-width,58rem)]"
                : "w-[calc(100%-0.5rem)] max-w-[var(--composer-content-width,49.5rem)] sm:w-full",
            ),
      )}
    >
      <div
        ref={listRef}
        className={cn(
          "inset-scrollbar min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain",
          showSplitPreview && "p-1.5",
        )}
        style={{ maxHeight: listMaxHeight }}
      >
        {children}
      </div>
      {showSplitPreview ? (
        <div
          aria-hidden
          data-palette-preview
          style={{ maxHeight: layout.maxHeight }}
          className="hidden min-w-0 flex-col overflow-hidden border-l border-border/55 bg-muted/[0.32] sm:flex dark:border-white/[0.06] dark:bg-black/[0.16]"
        >
          {preview}
        </div>
      ) : null}
    </div>
  );
}

interface SharedPaletteProps<T> {
  query: string;
  selectedIndex: number;
  layout: SlashPaletteLayout;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (item: T) => void;
}

export function SlashCommandPalette({
  commands,
  query,
  selectedIndex,
  layout,
  isHero,
  onHover,
  onChoose,
}: SharedPaletteProps<SlashPaletteCommand> & { commands: SlashPaletteCommand[] }) {
  const { t } = useTranslation();
  const groupLabel = t("thread.composer.slash.ariaLabel");
  const resolved = commands.map((command) => ({ command, ...resolveSlashCommand(command, t) }));
  const active = resolved[selectedIndex] ?? resolved[0];
  const activePreview = active ? (
    <PalettePreviewShell
      itemKey={active.command.command}
      icon={<active.Icon className="h-[18px] w-[18px]" />}
      header={<div className="truncate text-[14px] font-semibold leading-snug text-foreground">{active.title}</div>}
    >
      <div className="mt-3">
        <code className="inline-block max-w-full break-words rounded-compact bg-foreground/[0.045] px-2.5 py-1.5 font-mono text-[12px] font-medium leading-relaxed text-foreground/90 dark:bg-white/[0.065]">
          <HighlightedText text={active.commandLabel} query={query} />
        </code>
      </div>
      {active.description ? (
        <p className="mt-2.5 break-words text-[13px] leading-[1.6] text-muted-foreground">
          <HighlightedText text={active.description} query={query} />
        </p>
      ) : null}
      {active.hasLiveDetail ? (
        <div className="mt-3 flex min-w-0 items-center gap-2 rounded-compact bg-background/85 px-3 py-2 ring-1 ring-border/60 dark:bg-white/[0.045] dark:ring-white/[0.08]">
          <span
            className={cn(
              "h-1.5 w-1.5 shrink-0 rounded-full",
              active.command.command === "/stop"
                ? "bg-amber-500"
                : active.command.command === "/model" || active.command.badge
                  ? "bg-emerald-500"
                  : "bg-foreground/45",
            )}
          />
          <span className="min-w-0 break-words font-mono text-[12px] font-medium text-foreground/90">
            {active.command.detail}
          </span>
        </div>
      ) : null}
    </PalettePreviewShell>
  ) : null;

  return (
    <ComposerPaletteSurface
      ariaLabel={groupLabel}
      layout={layout}
      isHero={isHero}
      selectedIndex={selectedIndex}
      preview={activePreview}
    >
      <div role="group" aria-label={groupLabel}>
        <div className={groupHeaderClass}>{groupLabel}</div>
        {resolved.map(({ command, Icon, title, detail, showDetail, badgeLabel, commandLabel }, index) => {
          const selected = index === selectedIndex;
          const ariaLabel = [commandLabel, title, showDetail ? detail : null, badgeLabel].filter(Boolean).join(" ");
          return (
            <PaletteOption
              key={command.command}
              index={index}
              selected={selected}
              ariaLabel={ariaLabel}
              onHover={onHover}
              onChoose={() => onChoose(command)}
              className="min-h-[40px] items-start gap-2.5 py-2 sm:min-h-[38px] sm:items-center sm:py-1.5"
            >
              <span
                aria-hidden
                className={cn(
                  "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors sm:mt-0",
                  selected
                    ? "bg-foreground/[0.08] text-foreground dark:bg-white/[0.11]"
                    : "bg-foreground/[0.04] text-muted-foreground dark:bg-white/[0.055]",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className={cn("min-w-0 truncate font-mono text-[13px] tracking-tight text-foreground", selected ? "font-semibold" : "font-medium")}>
                    <HighlightedText text={command.command} query={query} />
                  </span>
                  <span className="max-w-[46%] shrink-0 truncate text-[12px] text-muted-foreground/80">
                    <HighlightedText text={title} query={query} />
                  </span>
                </span>
                {showDetail ? (
                  <span className="min-w-0 truncate text-[12px] leading-[1.4] text-muted-foreground sm:hidden">
                    <HighlightedText text={detail} query={query} />
                  </span>
                ) : null}
              </span>
              {badgeLabel ? (
                <span className={cn(badgeClass, "ml-auto mt-0.5 sm:mt-0")}>{badgeLabel}</span>
              ) : (
                <SelectionChevron selected={selected} className="ml-auto" />
              )}
            </PaletteOption>
          );
        })}
      </div>
    </ComposerPaletteSurface>
  );
}

interface SkillGroup {
  key: string;
  label: string;
  showRecentPill: boolean;
  showSourceLabel: boolean;
  items: Array<{ skill: SkillPaletteItem; index: number }>;
}

export function SkillPalette({
  skills,
  query,
  selectedIndex,
  layout,
  isHero,
  onHover,
  onChoose,
}: SharedPaletteProps<SkillPaletteItem> & { skills: SkillPaletteItem[] }) {
  const { t } = useTranslation();
  const ariaLabel = t("settings.skills.featured", { defaultValue: "Skills" });
  const activeSkill = skills[selectedIndex] ?? skills[0];

  const groups = useMemo<SkillGroup[]>(() => {
    const indexed = skills.map((skill, index) => ({ skill, index }));
    const hasMultipleSources = new Set(skills.map((skill) => skillSourceBucket(skill.source))).size > 1;
    if (query !== "" || !hasMultipleSources) {
      return [{ key: "skills", label: ariaLabel, showRecentPill: true, showSourceLabel: hasMultipleSources, items: indexed }];
    }
    const recentItems = indexed.filter(({ skill }) => skill.recent);
    const remaining = indexed.filter(({ skill }) => !skill.recent);
    return [
      ...(recentItems.length
        ? [{ key: "recent", label: t("thread.composer.slash.badges.recent"), showRecentPill: false, showSourceLabel: true, items: recentItems }]
        : []),
      ...(["workspace", "builtin", "other"] as const).flatMap((bucket) => {
        const items = remaining.filter(({ skill }) => skillSourceBucket(skill.source) === bucket);
        return items.length
          ? [{ key: bucket, label: skillBucketText(bucket, "groupKey", t), showRecentPill: false, showSourceLabel: false, items }]
          : [];
      }),
    ];
  }, [ariaLabel, query, skills, t]);

  const activePreview = activeSkill ? (
    <PalettePreviewShell
      itemKey={activeSkill.command}
      alignIcon="start"
      icon={<SkillsIcon className="h-[18px] w-[18px]" style={{ color: INLINE_REFERENCE_HIGHLIGHT_COLOR }} />}
      header={
        <div className="flex flex-col gap-1.5">
          <div className="break-words font-mono text-[14px] font-semibold leading-snug tracking-tight text-foreground [overflow-wrap:anywhere]">
            <span className="select-none font-normal opacity-90" style={{ color: INLINE_REFERENCE_HIGHLIGHT_COLOR }}>$</span>
            <HighlightedText text={activeSkill.name} query={query} />
          </div>
          <span className="inline-flex w-fit items-center rounded-full bg-foreground/[0.055] px-2 py-0.5 text-[11px] font-medium leading-none text-muted-foreground dark:bg-white/[0.08]">
            {skillBucketText(activeSkill.source, "sourceKey", t)}
          </span>
        </div>
      }
    >
      {activeSkill.description && activeSkill.description !== activeSkill.name ? (
        <p className="mt-3.5 break-words text-[13px] leading-[1.65] text-foreground/80">
          <HighlightedText text={activeSkill.description} query={query} />
        </p>
      ) : null}
    </PalettePreviewShell>
  ) : null;

  return (
    <ComposerPaletteSurface
      ariaLabel={ariaLabel}
      layout={layout}
      isHero={isHero}
      selectedIndex={selectedIndex}
      preview={activePreview}
    >
      {groups.map((group) => (
        <div key={group.key} role="group" aria-label={group.label} className="mt-1.5 first:mt-0">
          <div className={groupHeaderClass}>{group.label}</div>
          {group.items.map(({ skill, index }) => {
            const selected = index === selectedIndex;
            const showDescription = Boolean(skill.description && skill.description !== skill.name);
            const recentLabel = group.showRecentPill && skill.recent ? t("thread.composer.slash.badges.recent") : null;
            const sourceText = group.showSourceLabel ? skillBucketText(skill.source, "sourceKey", t) : null;
            const optionAriaLabel = [skill.name, showDescription ? skill.description : null, recentLabel ?? sourceText].filter(Boolean).join(" ");
            return (
              <PaletteOption
                key={skill.command}
                index={index}
                selected={selected}
                ariaLabel={optionAriaLabel}
                onHover={onHover}
                onChoose={() => onChoose(skill)}
                className="min-h-[40px] flex-col items-stretch gap-0.5 py-2 sm:min-h-[36px] sm:py-1.5"
              >
                <span className="flex w-full min-w-0 items-center gap-2">
                  <span className={cn("flex min-w-0 flex-1 items-baseline font-mono text-[13px] tracking-tight text-foreground", selected ? "font-semibold" : "font-medium")}>
                    <span aria-hidden className="select-none font-normal opacity-90" style={{ color: INLINE_REFERENCE_HIGHLIGHT_COLOR }}>$</span>
                    <span data-palette-skill-name className="min-w-0 break-words [overflow-wrap:anywhere]">
                      <HighlightedText text={skill.name} query={query} />
                    </span>
                  </span>
                  {recentLabel ? (
                    <span className={badgeClass}>{recentLabel}</span>
                  ) : sourceText ? (
                    <span className="shrink-0 text-[11px] font-normal text-muted-foreground/70">{sourceText}</span>
                  ) : (
                    <SelectionChevron selected={selected} />
                  )}
                </span>
                {showDescription ? (
                  <span className="line-clamp-2 w-full break-words text-[12px] leading-[1.45] text-muted-foreground sm:hidden">
                    <HighlightedText text={skill.description} query={query} />
                  </span>
                ) : null}
              </PaletteOption>
            );
          })}
        </div>
      ))}
    </ComposerPaletteSurface>
  );
}

export function CliAppMentionPalette({
  candidates,
  query,
  selectedIndex,
  layout,
  isHero,
  onHover,
  onChoose,
}: SharedPaletteProps<MentionCandidate> & { candidates: MentionCandidate[] }) {
  const { t } = useTranslation();
  const groupedCandidates = (["session", "cli", "mcp"] as const)
    .map((kind) => ({
      kind,
      label: t(`thread.composer.mentions.${kind}Group`),
      items: candidates.map((candidate, index) => ({ candidate, index })).filter(({ candidate }) => candidate.kind === kind),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <ComposerPaletteSurface
      ariaLabel={t("thread.composer.mentions.ariaLabel")}
      layout={layout}
      isHero={isHero}
      selectedIndex={selectedIndex}
    >
      {groupedCandidates.map((group) => (
        <div key={group.kind} role="group" aria-label={group.label} className="mt-1.5 first:mt-0">
          <div className={groupHeaderClass}>{group.label}</div>
          {group.items.map(({ candidate, index }) => {
            const selected = index === selectedIndex;
            const { name, kind } = candidate;
            const handleColor = kind === "session"
              ? candidate.mention.id ? sessionHandleColor(candidate.mention.id) : INLINE_TOKEN_HIGHLIGHT_COLOR
              : undefined;
            const typeLabel = t(`thread.composer.mentions.${kind}Badge`);
            const ariaDescription = t(`thread.composer.mentions.${kind}Description`, { name });

            return (
              <PaletteOption
                key={`${kind}-${name}`}
                index={index}
                selected={selected}
                ariaLabel={`@${name} ${candidate.displayName} ${ariaDescription} ${typeLabel}`}
                onHover={onHover}
                onChoose={() => onChoose(candidate)}
                className="touch-target min-h-10 flex-wrap items-center gap-x-2.5 gap-y-1 py-1.5"
              >
                <span className="max-w-full shrink-0 truncate text-[13.5px] font-normal tracking-normal text-muted-foreground/75" style={{ color: handleColor }}>
                  @<HighlightedText text={name} query={query} />
                </span>
                <span className={cn("flex max-w-full flex-1 flex-wrap items-center gap-x-2 gap-y-1", kind === "session" ? "min-w-[min(4rem,100%)]" : "min-w-[min(8rem,100%)]")}>
                  {kind !== "session" ? <MentionCandidateLogo candidate={candidate} selected={selected} /> : null}
                  <span className="min-w-[min(4rem,100%)] flex-1 truncate text-[13.5px] font-medium tracking-normal text-foreground">
                    <HighlightedText text={candidate.displayName} query={query} />
                  </span>
                  {kind !== "session" ? (
                    <span className={cn("ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold leading-none tracking-normal", kind === "cli" ? "bg-orange-500/10 text-orange-600 dark:text-orange-300" : "bg-sky-500/10 text-sky-600 dark:text-sky-300")}>
                      {typeLabel}
                    </span>
                  ) : null}
                </span>
              </PaletteOption>
            );
          })}
        </div>
      ))}
    </ComposerPaletteSurface>
  );
}

function MentionCandidateLogo({
  candidate,
  selected,
}: {
  candidate: Extract<MentionCandidate, { kind: "cli" | "mcp" }>;
  selected: boolean;
}) {
  const logoUrls = useMemo(() => logoFallbackUrls(candidate.logoUrl), [candidate.logoUrl]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);

  if (logoUrl) {
    return (
      <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-compact", selected ? "bg-background/55" : "bg-transparent")}>
        <img src={logoUrl} alt="" decoding="async" loading="lazy" className="h-5 w-5 object-contain" onLoad={onLogoLoad} onError={onLogoError} />
      </span>
    );
  }
  return (
    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-compact text-[7.5px] font-semibold text-white" style={{ backgroundColor: candidate.brandColor || INLINE_TOKEN_HIGHLIGHT_COLOR }}>
      {candidate.initials}
    </span>
  );
}
