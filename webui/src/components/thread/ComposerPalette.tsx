import { useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import type { TFunction } from "i18next";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ActivityIcon,
  ArchiveIcon,
  CompactIcon,
  DreamIcon,
  DreamLogIcon,
  EditIcon,
  GoalIcon,
  HelpIcon,
  HistoryIcon,
  MemoryIcon,
  ModelsIcon,
  NewChatIcon,
  PairingIcon,
  PromptTemplateIcon,
  RestartIcon,
  RestoreMemoryIcon,
  RestrictedAccessIcon,
  SkillsIcon,
  StatusIcon,
  StopIcon,
  ToolRunIcon,
  TriggerIcon,
} from "@/components/icons/product-icons";
import {
  INLINE_REFERENCE_HIGHLIGHT_COLOR,
  INLINE_TOKEN_HIGHLIGHT_COLOR,
} from "@/components/InlineTokenHighlight";
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

const PALETTE_CHROME_PX = 12;

const COMMAND_ICONS: Record<string, LucideIcon> = {
  activity: ActivityIcon,
  archive: ArchiveIcon,
  "book-open": SkillsIcon,
  brain: MemoryIcon,
  "circle-help": HelpIcon,
  history: HistoryIcon,
  "rotate-cw": RestartIcon,
  shield: RestrictedAccessIcon,
  sparkles: DreamIcon,
  square: StopIcon,
  "square-pen": EditIcon,
  "undo-2": RestoreMemoryIcon,
  zap: TriggerIcon,
  "file-text": PromptTemplateIcon,
  wrench: ToolRunIcon,
};

const BUILTIN_COMMAND_ICONS: Record<string, LucideIcon> = {
  "/new": NewChatIcon,
  "/compact": CompactIcon,
  "/stop": StopIcon,
  "/restart": RestartIcon,
  "/status": StatusIcon,
  "/model": ModelsIcon,
  "/goal": GoalIcon,
  "/trigger": TriggerIcon,
  "/dream": DreamIcon,
  "/dream-log": DreamLogIcon,
  "/dream-restore": RestoreMemoryIcon,
  "/dream-prompt": PromptTemplateIcon,
  "/evaluator-prompt": PromptTemplateIcon,
  "/skill": SkillsIcon,
  "/help": HelpIcon,
  "/pairing": PairingIcon,
};

export type SlashPalettePlacement = "above" | "below" | "beside";

export interface SlashPaletteLayout {
  placement: SlashPalettePlacement;
  maxHeight: number;
}

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

export type MentionCandidate = {
  name: string;
  displayName: string;
} & (
  | { kind: "session"; mention: SessionMention }
  | {
      kind: "cli" | "mcp";
      brandColor: string | null;
      logoUrl: string | null;
      initials: string;
    }
);

export function slashCommandI18nKey(command: string): string {
  return command.replace(/^\//, "").replace(/-/g, "_");
}

export type SkillSourceBucket = "workspace" | "builtin" | "other";

export function skillSourceBucket(source: string): SkillSourceBucket {
  if (source === "workspace") return "workspace";
  if (source === "builtin") return "builtin";
  return "other";
}

function skillSourceLabel(source: string, t: TFunction): string {
  const bucket = skillSourceBucket(source);
  if (bucket === "workspace") {
    return t("settings.skills.sourceWorkspace", { defaultValue: "Custom" });
  }
  if (bucket === "builtin") {
    return t("settings.skills.sourceBuiltin", { defaultValue: "Built-in" });
  }
  return t("settings.skills.otherGroup", { defaultValue: "Other" });
}

function skillGroupLabel(bucket: SkillSourceBucket, t: TFunction): string {
  if (bucket === "workspace") {
    return t("settings.skills.customGroup", { defaultValue: "Custom" });
  }
  if (bucket === "builtin") {
    return t("settings.skills.builtinGroup", { defaultValue: "Built-in" });
  }
  return t("settings.skills.otherGroup", { defaultValue: "Other" });
}

const paletteGroupHeaderClassName =
  "px-2.5 pb-1 pt-1 text-[11px] font-medium tracking-normal text-muted-foreground/75";

const paletteBadgeClassName =
  "inline-flex shrink-0 items-center rounded-full bg-foreground/[0.06] px-1.5 py-0.5 text-[10.5px] font-medium leading-none text-muted-foreground dark:bg-white/[0.08]";

function paletteItemSelectionClassName(selected: boolean): string {
  return selected
    ? "bg-foreground/[0.06] text-foreground dark:bg-black/[0.16]"
    : "text-foreground/90 hover:bg-foreground/[0.04] dark:hover:bg-black/[0.10]";
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  if (!query) return text;
  const index = text.toLowerCase().indexOf(query);
  if (index < 0) return text;
  const end = index + query.length;
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded-[3px] bg-foreground/[0.09] text-inherit dark:bg-white/[0.15]">
        {text.slice(index, end)}
      </mark>
      {text.slice(end)}
    </>
  );
}

function PaletteKeyHint({ text }: { text: string }) {
  const separator = text.indexOf(" ");
  if (separator < 0) {
    return <span className="text-[11px] text-muted-foreground/70">{text}</span>;
  }
  const key = text.slice(0, separator);
  const label = text.slice(separator + 1);
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground/70">
      <kbd className="rounded-[5px] border border-border/75 bg-background/90 px-1.5 py-[1px] font-sans text-[10px] font-medium leading-4 text-foreground/75 shadow-[0_1px_0_rgba(15,23,42,0.06)] dark:border-white/[0.10] dark:bg-white/[0.06] dark:shadow-none">
        {key}
      </kbd>
      <span>{label}</span>
    </span>
  );
}

function PalettePreviewFooter() {
  const { t } = useTranslation();
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/45 px-5 py-2.5 dark:border-white/[0.06]">
      <PaletteKeyHint text={t("thread.composer.slash.navigateHint")} />
      <PaletteKeyHint text={t("thread.composer.slash.selectHint")} />
      <PaletteKeyHint text={t("thread.composer.slash.closeHint")} />
    </div>
  );
}

function useSelectedOptionScroll(selectedIndex: number) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const option = container.querySelector<HTMLElement>(
      `[data-palette-index="${selectedIndex}"]`,
    );
    if (typeof option?.scrollIntoView === "function") {
      option.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  return containerRef;
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
  const listMaxHeight = Math.max(
    0,
    showSplitPreview ? layout.maxHeight : layout.maxHeight - PALETTE_CHROME_PX,
  );
  const listRef = useSelectedOptionScroll(selectedIndex);
  const surfaceRef = useOverlaySurfaceRef<HTMLDivElement>("overlay");

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

interface SlashCommandPaletteProps {
  commands: SlashPaletteCommand[];
  query: string;
  selectedIndex: number;
  layout: SlashPaletteLayout;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (command: SlashPaletteCommand) => void;
}

export function SlashCommandPalette({
  commands,
  query,
  selectedIndex,
  layout,
  isHero,
  onHover,
  onChoose,
}: SlashCommandPaletteProps) {
  const { t } = useTranslation();
  const groupLabel = t("thread.composer.slash.ariaLabel");
  const activeCommand = commands[selectedIndex] ?? commands[0];
  const activePreview = useMemo(() => {
    if (!activeCommand) return null;
    const Icon = BUILTIN_COMMAND_ICONS[activeCommand.command] ?? COMMAND_ICONS[activeCommand.icon] ?? HelpIcon;
    const commandKey = slashCommandI18nKey(activeCommand.command);
    const title = t(`thread.composer.slash.commands.${commandKey}.title`, {
      defaultValue: activeCommand.title,
    });
    const description = t(`thread.composer.slash.commands.${commandKey}.description`, {
      defaultValue: activeCommand.description,
    });
    const commandLabel = activeCommand.argHint
      ? `${activeCommand.command} ${activeCommand.argHint}`
      : activeCommand.command;
    const hasLiveDetail = Boolean(activeCommand.detail && activeCommand.detail !== description);
    const statusDotClass = activeCommand.command === "/stop"
      ? "bg-amber-500"
      : activeCommand.command === "/model" || activeCommand.badge
        ? "bg-emerald-500"
        : "bg-foreground/45";

    return (
      <>
        <div
          key={activeCommand.command}
          className="composer-palette-preview-body inset-scrollbar min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-5 py-4"
        >
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-background text-foreground ring-1 ring-border/70 shadow-[0_1px_2px_rgba(15,23,42,0.05)] dark:bg-white/[0.06] dark:ring-white/[0.09] dark:shadow-none">
              <Icon className="h-[18px] w-[18px]" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[14px] font-semibold leading-snug text-foreground">
                {title}
              </div>
            </div>
          </div>
          <div className="mt-3">
            <code className="inline-block max-w-full break-words rounded-compact bg-foreground/[0.045] px-2.5 py-1.5 font-mono text-[12px] font-medium leading-relaxed text-foreground/90 dark:bg-white/[0.065]">
              <HighlightedText text={commandLabel} query={query} />
            </code>
          </div>
          {description ? (
            <p className="mt-2.5 break-words text-[13px] leading-[1.6] text-muted-foreground">
              <HighlightedText text={description} query={query} />
            </p>
          ) : null}
          {hasLiveDetail ? (
            <div className="mt-3 flex min-w-0 items-center gap-2 rounded-compact bg-background/85 px-3 py-2 ring-1 ring-border/60 dark:bg-white/[0.045] dark:ring-white/[0.08]">
              <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", statusDotClass)} />
              <span className="min-w-0 break-words font-mono text-[12px] font-medium text-foreground/90">
                {activeCommand.detail}
              </span>
            </div>
          ) : null}
        </div>
        <PalettePreviewFooter />
      </>
    );
  }, [activeCommand, query, t]);

  return (
    <ComposerPaletteSurface
      ariaLabel={groupLabel}
      layout={layout}
      isHero={isHero}
      selectedIndex={selectedIndex}
      preview={activePreview}
    >
      <div role="group" aria-label={groupLabel}>
        <div className={paletteGroupHeaderClassName}>{groupLabel}</div>
        {commands.map((command, index) => {
          const Icon = BUILTIN_COMMAND_ICONS[command.command] ?? COMMAND_ICONS[command.icon] ?? HelpIcon;
          const selected = index === selectedIndex;
          const commandKey = slashCommandI18nKey(command.command);
          const title = t(`thread.composer.slash.commands.${commandKey}.title`, {
            defaultValue: command.title,
          });
          const description = t(`thread.composer.slash.commands.${commandKey}.description`, {
            defaultValue: command.description,
          });
          const detail = command.detail || description;
          const showDetail = detail && detail !== title;
          const badgeLabel = command.badge ?? (command.recent ? t("thread.composer.slash.badges.recent") : null);
          const commandLabel = command.argHint ? `${command.command} ${command.argHint}` : command.command;
          const ariaLabel = [commandLabel, title, showDetail ? detail : null, badgeLabel]
            .filter(Boolean)
            .join(" ");

          return (
            <button
              key={command.command}
              type="button"
              role="option"
              data-palette-index={index}
              aria-selected={selected}
              aria-label={ariaLabel}
              onMouseEnter={() => onHover(index)}
              onMouseDown={(e) => {
                e.preventDefault();
                onChoose(command);
              }}
              className={cn(
                floatingItemClassName,
                floatingItemFocusClassName,
                "flex min-h-[40px] w-full min-w-0 items-start gap-2.5 overflow-hidden px-2.5 py-2 text-left transition-colors duration-100 sm:min-h-[38px] sm:items-center sm:py-1.5",
                paletteItemSelectionClassName(selected),
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors sm:mt-0",
                  selected
                    ? "bg-foreground/[0.08] text-foreground dark:bg-white/[0.11]"
                    : "bg-foreground/[0.04] text-muted-foreground dark:bg-white/[0.055]",
                )}
                aria-hidden
              >
                <Icon className="h-3.5 w-3.5" />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className={cn(
                    "min-w-0 truncate font-mono text-[13px] tracking-tight text-foreground",
                    selected ? "font-semibold" : "font-medium",
                  )}>
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
                <span className={cn(paletteBadgeClassName, "ml-auto mt-0.5 sm:mt-0")}>
                  {badgeLabel}
                </span>
              ) : (
                <ChevronRight
                  aria-hidden
                  className={cn(
                    "ml-auto hidden h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-opacity duration-100 sm:block",
                    selected ? "opacity-100" : "opacity-0",
                  )}
                />
              )}
            </button>
          );
        })}
      </div>
    </ComposerPaletteSurface>
  );
}

interface SkillPaletteProps {
  skills: SkillPaletteItem[];
  query: string;
  selectedIndex: number;
  layout: SlashPaletteLayout;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (skill: SkillPaletteItem) => void;
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
}: SkillPaletteProps) {
  const { t } = useTranslation();
  const ariaLabel = t("settings.skills.featured", { defaultValue: "Skills" });
  const activeSkill = skills[selectedIndex] ?? skills[0];
  const groups = useMemo<SkillGroup[]>(() => {
    const indexed = skills.map((skill, index) => ({ skill, index }));
    const distinctSources = new Set(skills.map((skill) => skillSourceBucket(skill.source)));
    const hasMultipleSources = distinctSources.size > 1;

    if (query !== "" || !hasMultipleSources) {
      return [{
        key: "skills",
        label: ariaLabel,
        showRecentPill: true,
        showSourceLabel: hasMultipleSources,
        items: indexed,
      }];
    }

    const result: SkillGroup[] = [];
    const recentItems = indexed.filter(({ skill }) => skill.recent);
    if (recentItems.length > 0) {
      result.push({
        key: "recent",
        label: t("thread.composer.slash.badges.recent"),
        showRecentPill: false,
        showSourceLabel: true,
        items: recentItems,
      });
    }
    const remaining = indexed.filter(({ skill }) => !skill.recent);
    for (const bucket of ["workspace", "builtin", "other"] as const) {
      const items = remaining.filter(({ skill }) => skillSourceBucket(skill.source) === bucket);
      if (items.length > 0) {
        result.push({
          key: bucket,
          label: skillGroupLabel(bucket, t),
          showRecentPill: false,
          showSourceLabel: false,
          items,
        });
      }
    }
    return result;
  }, [ariaLabel, query, skills, t]);

  const activePreview = useMemo(() => {
    if (!activeSkill) return null;
    const sourceText = skillSourceLabel(activeSkill.source, t);
    const hasDescription = Boolean(activeSkill.description && activeSkill.description !== activeSkill.name);
    return (
      <>
        <div
          key={activeSkill.command}
          className="composer-palette-preview-body inset-scrollbar min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-5 py-4"
        >
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-background ring-1 ring-border/70 shadow-[0_1px_2px_rgba(15,23,42,0.05)] dark:bg-white/[0.06] dark:ring-white/[0.09] dark:shadow-none">
              <SkillsIcon
                className="h-[18px] w-[18px]"
                style={{ color: INLINE_REFERENCE_HIGHLIGHT_COLOR }}
              />
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <div className="break-words font-mono text-[14px] font-semibold leading-snug tracking-tight text-foreground [overflow-wrap:anywhere]">
                <span
                  className="select-none font-normal opacity-90"
                  style={{ color: INLINE_REFERENCE_HIGHLIGHT_COLOR }}
                >
                  $
                </span>
                <HighlightedText text={activeSkill.name} query={query} />
              </div>
              <span className="inline-flex w-fit items-center rounded-full bg-foreground/[0.055] px-2 py-0.5 text-[11px] font-medium leading-none text-muted-foreground dark:bg-white/[0.08]">
                {sourceText}
              </span>
            </div>
          </div>
          {hasDescription ? (
            <p className="mt-3.5 break-words text-[13px] leading-[1.65] text-foreground/80">
              <HighlightedText text={activeSkill.description} query={query} />
            </p>
          ) : null}
        </div>
        <PalettePreviewFooter />
      </>
    );
  }, [activeSkill, query, t]);

  return (
    <ComposerPaletteSurface
      ariaLabel={ariaLabel}
      layout={layout}
      isHero={isHero}
      selectedIndex={selectedIndex}
      preview={activePreview}
    >
      {groups.map((group) => (
        <div
          key={group.key}
          role="group"
          aria-label={group.label}
          className="mt-1.5 first:mt-0"
        >
          <div className={paletteGroupHeaderClassName}>{group.label}</div>
          {group.items.map(({ skill, index }) => {
            const selected = index === selectedIndex;
            const showDescription = skill.description && skill.description !== skill.name;
            const showRecentPill = group.showRecentPill && skill.recent;
            const sourceText = group.showSourceLabel ? skillSourceLabel(skill.source, t) : null;
            const recentLabel = showRecentPill ? t("thread.composer.slash.badges.recent") : null;
            const optionAriaLabel = [
              skill.name,
              showDescription ? skill.description : null,
              recentLabel ?? sourceText,
            ]
              .filter(Boolean)
              .join(" ");

            return (
              <button
                key={skill.command}
                type="button"
                role="option"
                data-palette-index={index}
                aria-selected={selected}
                aria-label={optionAriaLabel}
                onMouseEnter={() => onHover(index)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChoose(skill);
                }}
                className={cn(
                  floatingItemClassName,
                  floatingItemFocusClassName,
                  "flex min-h-[40px] w-full min-w-0 flex-col items-stretch gap-0.5 overflow-hidden px-2.5 py-2 text-left transition-colors duration-100 sm:min-h-[36px] sm:py-1.5",
                  paletteItemSelectionClassName(selected),
                )}
              >
                <span className="flex w-full min-w-0 items-center gap-2">
                  <span className={cn(
                    "flex min-w-0 flex-1 items-baseline font-mono text-[13px] tracking-tight text-foreground",
                    selected ? "font-semibold" : "font-medium",
                  )}>
                    <span
                      aria-hidden
                      className="select-none font-normal opacity-90"
                      style={{ color: INLINE_REFERENCE_HIGHLIGHT_COLOR }}
                    >
                      $
                    </span>
                    <span data-palette-skill-name className="min-w-0 break-words [overflow-wrap:anywhere]">
                      <HighlightedText text={skill.name} query={query} />
                    </span>
                  </span>
                  {recentLabel ? (
                    <span className={paletteBadgeClassName}>
                      {recentLabel}
                    </span>
                  ) : sourceText ? (
                    <span className="shrink-0 text-[11px] font-normal text-muted-foreground/70">
                      {sourceText}
                    </span>
                  ) : (
                    <ChevronRight
                      aria-hidden
                      className={cn(
                        "hidden h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-opacity duration-100 sm:block",
                        selected ? "opacity-100" : "opacity-0",
                      )}
                    />
                  )}
                </span>
                {showDescription ? (
                  <span className="line-clamp-2 w-full break-words text-[12px] leading-[1.45] text-muted-foreground sm:hidden">
                    <HighlightedText text={skill.description} query={query} />
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      ))}
    </ComposerPaletteSurface>
  );
}

interface CliAppMentionPaletteProps {
  candidates: MentionCandidate[];
  query: string;
  selectedIndex: number;
  layout: SlashPaletteLayout;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (candidate: MentionCandidate) => void;
}

export function CliAppMentionPalette({
  candidates,
  query,
  selectedIndex,
  layout,
  isHero,
  onHover,
  onChoose,
}: CliAppMentionPaletteProps) {
  const { t } = useTranslation();
  const groupedCandidates = (["session", "cli", "mcp"] as const)
    .map((kind) => ({
      kind,
      label: kind === "session"
        ? t("thread.composer.mentions.sessionGroup")
        : kind === "cli"
          ? t("thread.composer.mentions.cliGroup")
          : t("thread.composer.mentions.mcpGroup"),
      items: candidates
        .map((candidate, index) => ({ candidate, index }))
        .filter(({ candidate }) => candidate.kind === kind),
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
          <div className={paletteGroupHeaderClassName}>{group.label}</div>
          {group.items.map(({ candidate, index }) => {
            const selected = index === selectedIndex;
            const name = candidate.name;
            const handleColor = candidate.kind === "session"
              ? candidate.mention.id ? sessionHandleColor(candidate.mention.id) : INLINE_TOKEN_HIGHLIGHT_COLOR
              : undefined;
            const typeLabel = candidate.kind === "cli"
              ? t("thread.composer.mentions.cliBadge")
              : candidate.kind === "mcp"
                ? t("thread.composer.mentions.mcpBadge")
                : t("thread.composer.mentions.sessionBadge");
            const ariaDescription = candidate.kind === "cli"
              ? t("thread.composer.mentions.cliDescription", { name })
              : candidate.kind === "mcp"
                ? t("thread.composer.mentions.mcpDescription", { name })
                : t("thread.composer.mentions.sessionDescription", { name });

            return (
              <button
                key={`${candidate.kind}-${name}`}
                type="button"
                role="option"
                data-palette-index={index}
                aria-selected={selected}
                aria-label={`@${name} ${candidate.displayName} ${ariaDescription} ${typeLabel}`}
                onMouseEnter={() => onHover(index)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChoose(candidate);
                }}
                className={cn(
                  floatingItemClassName,
                  floatingItemFocusClassName,
                  "touch-target flex min-h-10 w-full min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 overflow-hidden px-2.5 py-1.5 text-left transition-colors duration-100",
                  paletteItemSelectionClassName(selected),
                )}
              >
                <span
                  className="max-w-full shrink-0 truncate text-[13.5px] font-normal tracking-normal text-muted-foreground/75"
                  style={{ color: handleColor }}
                >
                  @<HighlightedText text={name} query={query} />
                </span>
                <span
                  className={cn(
                    "flex max-w-full flex-1 flex-wrap items-center gap-x-2 gap-y-1",
                    candidate.kind === "session" ? "min-w-[min(4rem,100%)]" : "min-w-[min(8rem,100%)]",
                  )}
                >
                  {candidate.kind !== "session" ? <MentionCandidateLogo candidate={candidate} selected={selected} /> : null}
                  <span className="min-w-[min(4rem,100%)] flex-1 truncate text-[13.5px] font-medium tracking-normal text-foreground">
                    <HighlightedText text={candidate.displayName} query={query} />
                  </span>
                  {candidate.kind !== "session" ? (
                    <span
                      className={cn(
                        "ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold leading-none tracking-normal",
                        candidate.kind === "cli"
                          ? "bg-orange-500/10 text-orange-600 dark:text-orange-300"
                          : "bg-sky-500/10 text-sky-600 dark:text-sky-300",
                      )}
                    >
                      {typeLabel}
                    </span>
                  ) : null}
                </span>
              </button>
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
  const color = candidate.brandColor || INLINE_TOKEN_HIGHLIGHT_COLOR;
  const logoUrls = useMemo(() => logoFallbackUrls(candidate.logoUrl), [candidate.logoUrl]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);

  if (logoUrl) {
    return (
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-compact",
          selected ? "bg-background/55" : "bg-transparent",
        )}
      >
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-5 w-5 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      </span>
    );
  }
  return (
    <span
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-compact text-[7.5px] font-semibold text-white"
      style={{ backgroundColor: color }}
    >
      {candidate.initials}
    </span>
  );
}
