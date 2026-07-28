import { useEffect, useState, type ReactNode } from "react";
import type { TFunction } from "i18next";
import {
  Check,
  CircleAlert,
  Copy,
  KeyRound,
  Loader2,
  PowerOff,
  RefreshCw,
  Search,
  Terminal,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { SkillsMarketplace } from "@/components/settings/SkillsMarketplace";
import { deleteSkill, fetchSkillDetail, updateSkillEnabled } from "@/lib/api";
import { notifySkillsChanged } from "@/lib/skill-events";
import type { SkillDetail, SkillSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export function SkillsCatalogSettings({ skills }: { skills: SkillSummary[] }) {
  const { t } = useTranslation();
  const availableCount = skills.filter(
    (skill) => skill.enabled !== false && skill.available,
  ).length;
  const [selectedSkill, setSelectedSkill] = useState<SkillSummary | null>(null);
  const [view, setView] = useState<"installed" | "discover">("installed");
  const [installedQuery, setInstalledQuery] = useState("");
  const [installedFilter, setInstalledFilter] = useState<"all" | "enabled" | "disabled">(
    "all",
  );
  const normalizedQuery = installedQuery.trim().toLowerCase();
  const filteredSkills = skills.filter((skill) => {
    const enabled = skill.enabled !== false;
    if (installedFilter === "enabled" && !enabled) return false;
    if (installedFilter === "disabled" && enabled) return false;
    return (
      !normalizedQuery
      || skill.name.toLowerCase().includes(normalizedQuery)
      || skill.description.toLowerCase().includes(normalizedQuery)
    );
  });
  const groupedSkills = [
    {
      key: "workspace",
      label: t("settings.skills.customGroup", { defaultValue: "Custom" }),
      skills: filteredSkills.filter((skill) => skill.source === "workspace"),
    },
    {
      key: "builtin",
      label: t("settings.skills.builtinGroup", { defaultValue: "Built-in" }),
      skills: filteredSkills.filter((skill) => skill.source === "builtin"),
    },
    {
      key: "other",
      label: t("settings.skills.otherGroup", { defaultValue: "Other" }),
      skills: filteredSkills.filter(
        (skill) => skill.source !== "workspace" && skill.source !== "builtin",
      ),
    },
  ].filter((group) => group.skills.length);
  const disabledCount = skills.filter((skill) => skill.enabled === false).length;

  return (
    <div className="space-y-7">
      <section className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <p className="max-w-[680px] text-[13px] leading-5 text-muted-foreground">
          {t("settings.skills.description", {
            defaultValue:
              "Review installed skills or discover new capabilities from the skills.sh catalog.",
          })}
        </p>
        <span className="text-[12px] font-medium text-muted-foreground">
          {t("settings.skills.caption", {
            available: availableCount,
            total: skills.length,
            defaultValue: "{{available}} available · {{total}} total",
          })}
        </span>
      </section>

      <div
        className="inline-flex rounded-[12px] bg-muted/65 p-1"
        role="tablist"
        aria-label={t("settings.skills.views", { defaultValue: "Skills views" })}
      >
        {(["installed", "discover"] as const).map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={view === item}
            onClick={() => setView(item)}
            className={cn(
              "inline-flex items-center rounded-[9px] px-3.5 py-1.5 text-[13px] font-medium transition-colors",
              view === item
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {item === "installed"
              ? t("settings.skills.installedTab", { defaultValue: "Installed" })
              : t("settings.skills.discoverTab", { defaultValue: "Discover" })}
          </button>
        ))}
      </div>

      {view === "installed" ? (
        <section className="overflow-hidden rounded-[22px] bg-settings-surface">
          <div className="flex flex-col gap-3 border-b border-border/45 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full sm:max-w-[320px]">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={installedQuery}
                onChange={(event) => setInstalledQuery(event.target.value)}
                placeholder={t("settings.skills.searchInstalled", {
                  defaultValue: "Search installed skills",
                })}
                aria-label={t("settings.skills.searchInstalled", {
                  defaultValue: "Search installed skills",
                })}
                className="h-9 rounded-[11px] bg-background pl-9 text-[13px]"
              />
            </div>
            <div
              className={cn(
                "flex max-w-full items-center gap-1 overflow-x-auto rounded-[10px] bg-muted/65 p-1",
                "scrollbar-thin scrollbar-track-transparent sm:w-auto",
              )}
            >
              {([
                ["all", t("settings.skills.filterAll", { defaultValue: "All" }), skills.length],
                [
                  "enabled",
                  t("settings.skills.filterEnabled", { defaultValue: "Enabled" }),
                  skills.length - disabledCount,
                ],
                [
                  "disabled",
                  t("settings.skills.filterDisabled", { defaultValue: "Disabled" }),
                  disabledCount,
                ],
              ] as const).map(([filter, label, count]) => (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setInstalledFilter(filter)}
                  className={cn(
                    "shrink-0 whitespace-nowrap rounded-[8px] px-2.5 py-1 text-[11px] font-medium transition-colors",
                    installedFilter === filter
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label} <span className="ml-0.5 tabular-nums opacity-65">{count}</span>
                </button>
              ))}
            </div>
          </div>
          {groupedSkills.length ? (
            <div className="pb-2">
              {groupedSkills.map((group) => (
                <section key={group.key}>
                  <div className="flex items-center gap-2 bg-muted/20 px-5 py-2.5">
                    <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                      {group.label}
                    </h2>
                    <span className="text-[11px] tabular-nums text-muted-foreground/60">
                      {group.skills.length}
                    </span>
                  </div>
                  <div className="divide-y divide-border/40 px-3 sm:px-4">
                    {group.skills.map((skill) => (
                      <SkillCatalogRow
                        key={`${skill.source}:${skill.name}`}
                        skill={skill}
                        onSelect={setSelectedSkill}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <div className="px-3 py-12 text-center text-sm text-muted-foreground">
              {t("settings.skills.noMatching", {
                defaultValue: "No matching skills.",
              })}
            </div>
          )}
        </section>
      ) : (
        <SkillsMarketplace installedSkills={skills} />
      )}

      <SkillDetailSheet
        skill={selectedSkill}
        open={selectedSkill !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedSkill(null);
        }}
      />
    </div>
  );
}

function SkillCatalogRow({
  skill,
  onSelect,
}: {
  skill: SkillSummary;
  onSelect: (skill: SkillSummary) => void;
}) {
  const { t } = useTranslation();
  const enabled = skill.enabled !== false;
  const StatusIcon = !enabled ? PowerOff : skill.available ? Check : CircleAlert;
  const statusLabel = !enabled
    ? t("settings.skills.statusDisabled", { defaultValue: "Disabled" })
    : skill.available
      ? t("settings.skills.statusEnabled", { defaultValue: "Enabled" })
      : t("settings.skills.statusNeedsSetup", { defaultValue: "Needs setup" });

  return (
    <button
      type="button"
      aria-label={t("settings.skills.openDetails", {
        name: skill.name,
        defaultValue: "Open details for {{name}}",
      })}
      onClick={() => onSelect(skill)}
      className={cn(
        "group flex w-full min-w-0 items-center gap-3 rounded-[14px] px-2 py-3 text-left",
        "transition-[background-color,box-shadow] duration-150",
        "hover:bg-muted/70 hover:shadow-[inset_0_0_0_1px_hsl(var(--border)/0.35)]",
        "focus-visible:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        !enabled && "opacity-60",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/30 transition-colors duration-150",
          "group-hover:bg-foreground/55 group-focus-visible:bg-foreground/55",
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground">
          {skill.name}
        </h3>
        <p className="mt-0.5 line-clamp-1 text-[12px] leading-5 text-muted-foreground transition-colors duration-150 group-hover:text-foreground/65">
          {skill.description}
        </p>
      </div>
      <span
        title={enabled && !skill.available ? skill.unavailable_reason : undefined}
        className={cn(
          "hidden w-[92px] shrink-0 items-center justify-end gap-1 text-[11px] font-medium sm:inline-flex",
          !enabled
            ? "text-muted-foreground"
            : skill.available
              ? "text-emerald-700 dark:text-emerald-300"
              : "text-amber-700 dark:text-amber-300",
        )}
      >
        <StatusIcon className="h-3.5 w-3.5" aria-hidden />
        {statusLabel}
      </span>
    </button>
  );
}

function SkillDetailSheet({
  skill,
  open,
  onOpenChange,
}: {
  skill: SkillSummary | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { token } = useClient();
  const { t } = useTranslation();
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);

  useEffect(() => {
    if (!open || !skill) return;
    let cancelled = false;
    setDetail(null);
    setLoading(true);
    setLoadFailed(false);
    setActionError("");
    setDeleteOpen(false);
    setDescriptionExpanded(false);
    fetchSkillDetail(token, skill.name)
      .then((payload) => {
        if (!cancelled) setDetail(payload);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, refreshKey, skill, token]);

  if (!skill) return null;

  const activeSkill = detail ?? skill;
  const enabled = activeSkill.enabled !== false;
  const deletable = activeSkill.deletable ?? activeSkill.source === "workspace";
  const sourceLabel = skillSourceLabel(activeSkill.source, t);
  const statusLabel = !enabled
    ? t("settings.skills.statusDisabled", { defaultValue: "Disabled" })
    : activeSkill.available
      ? t("settings.skills.statusEnabled", { defaultValue: "Enabled" })
      : t("settings.skills.statusNeedsSetup", { defaultValue: "Needs setup" });
  const descriptionExpandable = activeSkill.description.length > 240;

  const toggleEnabled = async () => {
    setActionBusy(true);
    setActionError("");
    try {
      const payload = await updateSkillEnabled(token, activeSkill.name, !enabled);
      notifySkillsChanged(payload);
      const updated = payload.skills.find((item) => item.name === activeSkill.name);
      if (updated) {
        setDetail((current) => current ? { ...current, ...updated } : current);
      }
    } catch (reason) {
      setActionError(
        reason instanceof Error
          ? reason.message
          : t("settings.skills.updateFailed", {
              defaultValue: "Could not update this skill.",
            }),
      );
    } finally {
      setActionBusy(false);
    }
  };

  const removeSkill = async () => {
    setDeleteOpen(false);
    setActionBusy(true);
    setActionError("");
    try {
      const payload = await deleteSkill(token, activeSkill.name);
      notifySkillsChanged(payload);
      onOpenChange(false);
    } catch (reason) {
      setActionError(
        reason instanceof Error
          ? reason.message
          : t("settings.skills.deleteFailed", {
              defaultValue: "Could not delete this skill.",
            }),
      );
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="right"
          closeButtonClassName={cn(
            "right-2 top-2 inline-flex h-10 w-10 items-center justify-center rounded-full opacity-100",
            "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            "sm:right-3 sm:top-3",
          )}
          className={cn(
            "w-full max-w-none gap-0 overflow-hidden border-l-0 p-0",
            "sm:w-[min(34rem,calc(100vw-1rem))] sm:max-w-none sm:border-l",
          )}
        >
          <div
            className={cn(
              "min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5 sm:py-5",
              "pb-[max(1rem,env(safe-area-inset-bottom))]",
            )}
          >
            <div className="flex items-start gap-3 pr-8">
              <div className="min-w-0 flex-1">
                <SheetTitle className="truncate text-[19px] font-semibold sm:text-[20px]">
                  {activeSkill.name}
                </SheetTitle>
                <SheetDescription className="sr-only">
                  {t("settings.skills.detailDescription", {
                    name: activeSkill.name,
                    defaultValue: "Details for {{name}}.",
                  })}
                </SheetDescription>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-muted-foreground">
                  <Pill>{sourceLabel}</Pill>
                  <Pill
                    tone={
                      !enabled
                        ? "muted"
                        : activeSkill.available
                          ? "success"
                          : "warning"
                    }
                  >
                    {statusLabel}
                  </Pill>
                </div>
                <p
                  className={cn(
                    "mt-3 text-[13px] leading-5 text-muted-foreground",
                    descriptionExpandable && !descriptionExpanded && "line-clamp-5",
                  )}
                >
                  {activeSkill.description}
                </p>
                {descriptionExpandable ? (
                  <button
                    type="button"
                    aria-expanded={descriptionExpanded}
                    onClick={() => setDescriptionExpanded((value) => !value)}
                    className="mt-1.5 min-h-8 rounded-full text-[12px] font-medium text-foreground/70 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {descriptionExpanded
                      ? t("settings.skills.showLess", { defaultValue: "Show less" })
                      : t("settings.skills.showMore", { defaultValue: "Show more" })}
                  </button>
                ) : null}
              </div>
            </div>

            {loading ? (
              <div className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                {t("settings.skills.loadingDetail", { defaultValue: "Loading skill details..." })}
              </div>
            ) : loadFailed ? (
              <div className="mt-8 rounded-[16px] bg-destructive/10 px-3 py-3 text-sm text-destructive">
                {t("settings.skills.loadFailed", { defaultValue: "Could not load skill details." })}
              </div>
            ) : (
              <div className="mt-6 space-y-5">
                <div className="flex min-h-16 items-start justify-between gap-3 border-y border-border/45 px-1 py-3.5">
                  <div>
                    <p className="text-[13px] font-medium text-foreground">
                      {t("settings.skills.enabledControl", { defaultValue: "Use this skill" })}
                    </p>
                    <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
                      {t("settings.skills.enabledDescription", {
                        defaultValue:
                          "Allow the agent to load this skill when its requirements are ready.",
                      })}
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={enabled}
                    aria-label={
                      enabled
                        ? t("settings.skills.disableSkill", {
                            name: activeSkill.name,
                            defaultValue: "Disable {{name}}",
                          })
                        : t("settings.skills.enableSkill", {
                            name: activeSkill.name,
                            defaultValue: "Enable {{name}}",
                          })
                    }
                    disabled={actionBusy}
                    onClick={() => void toggleEnabled()}
                    className={cn(
                      "relative -mr-1 h-10 w-14 shrink-0 rounded-full",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                      "disabled:cursor-wait disabled:opacity-60",
                    )}
                  >
                    <span
                      className={cn(
                        "absolute left-1.5 top-2 h-6 w-11 rounded-full transition-colors",
                        enabled ? "bg-foreground" : "bg-muted-foreground/30",
                      )}
                    />
                    <span
                      className={cn(
                        "absolute left-2 top-2.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform",
                        enabled ? "translate-x-5" : "translate-x-0",
                      )}
                    />
                  </button>
                </div>

                {actionError ? (
                  <div className="rounded-[14px] bg-destructive/10 px-3 py-2.5 text-[13px] text-destructive">
                    {actionError}
                  </div>
                ) : null}

                {detail && enabled ? (
                  <RequirementsSection
                    detail={detail}
                    onRefresh={() => setRefreshKey((value) => value + 1)}
                  />
                ) : null}

                {detail ? <RawInstructionsBlock markdown={detail.raw_markdown} /> : null}

                {deletable ? (
                  <div className="flex flex-col items-stretch gap-3 border-t border-border/45 pt-5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                    <div>
                      <p className="text-[13px] font-medium text-foreground">
                        {t("settings.skills.deleteTitle", { defaultValue: "Delete skill" })}
                      </p>
                      <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
                        {t("settings.skills.deleteDescription", {
                          defaultValue: "Remove this skill from the current workspace.",
                        })}
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={actionBusy}
                      onClick={() => setDeleteOpen(true)}
                      className={cn(
                        "h-10 w-full shrink-0 rounded-full border-destructive/20 text-destructive",
                        "hover:bg-destructive/8 hover:text-destructive sm:h-9 sm:w-auto",
                      )}
                    >
                      <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                      {t("settings.skills.deleteAction", { defaultValue: "Delete" })}
                    </Button>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </SheetContent>
      </Sheet>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent className="rounded-[20px]">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("settings.skills.deleteConfirmTitle", {
                name: activeSkill.name,
                defaultValue: "Delete {{name}}?",
              })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.skills.deleteConfirmDescription", {
                defaultValue:
                  "This removes the skill files from the current workspace. This action cannot be undone.",
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {t("common.cancel", { defaultValue: "Cancel" })}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void removeSkill()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t("settings.skills.deleteConfirmAction", { defaultValue: "Delete skill" })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function RawInstructionsBlock({ markdown }: { markdown: string }) {
  const { t } = useTranslation();
  const content =
    markdown ||
    t("settings.skills.rawInstructionsEmpty", {
      defaultValue: "No raw instructions.",
    });

  return (
    <details className="group rounded-[18px] border border-border/45 bg-muted/20 px-3 py-3">
      <summary className="flex min-h-11 cursor-pointer select-none items-center justify-between gap-3 text-[13px] font-medium text-foreground/90 transition-colors hover:text-foreground">
        <span>
          {t("settings.skills.instructionsTitle", { defaultValue: "Skill instructions" })}
        </span>
        <code className="font-mono text-[10px] font-normal text-muted-foreground">
          SKILL.md
        </code>
      </summary>
      <div className="mt-3 overflow-hidden rounded-[14px] border border-border/35 bg-background/70">
        <pre
          className={cn(
            "max-h-[min(42vh,32rem)] overflow-auto overscroll-contain px-3.5 py-3 pr-4",
            "whitespace-pre-wrap break-words font-mono text-[12px] leading-[1.7] text-foreground/62",
            "scrollbar-thin scrollbar-track-transparent",
            "[&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar]:w-1.5",
            "[&::-webkit-scrollbar-thumb]:bg-muted-foreground/25",
          )}
        >
          {content}
        </pre>
      </div>
    </details>
  );
}

function RequirementsSection({
  detail,
  onRefresh,
}: {
  detail: SkillDetail;
  onRefresh: () => void;
}) {
  const { t } = useTranslation();
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const { missing_bins, missing_env } = detail.requirements;
  const hasMissing = missing_bins.length > 0 || missing_env.length > 0;

  if (!hasMissing) return null;

  const installOptions = detail.install_options ?? [];
  const copyCommand = async (command: string) => {
    try {
      await navigator.clipboard.writeText(command);
      setCopiedCommand(command);
    } catch {
      setCopiedCommand(null);
    }
  };

  return (
    <section className="rounded-[18px] border border-amber-500/20 bg-amber-500/[0.06] p-4">
      <div className="flex items-start gap-2.5">
        <CircleAlert
          className="mt-0.5 h-4 w-4 shrink-0 text-amber-700 dark:text-amber-300"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <h3 className="text-[13px] font-semibold text-foreground">
            {t("settings.skills.setupRequired", { defaultValue: "Setup required" })}
          </h3>
          <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
            {t("settings.skills.setupDescription", {
              defaultValue:
                "Install the missing dependency on the machine running nanobot, then check again.",
            })}
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {installOptions.map((option) => (
          <div
            key={`${option.id}:${option.command}`}
            className="flex min-w-0 items-center gap-2 rounded-[12px] bg-background/80 px-3 py-2"
          >
            <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-[11px] text-foreground/80">
              {option.command}
            </code>
            <button
              type="button"
              aria-label={t("settings.skills.copySetupCommand", {
                defaultValue: "Copy setup command",
              })}
              title={option.label}
              onClick={() => void copyCommand(option.command)}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[9px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:h-7 sm:w-7"
            >
              {copiedCommand === option.command ? (
                <Check className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
              ) : (
                <Copy className="h-3.5 w-3.5" aria-hidden />
              )}
            </button>
          </div>
        ))}

        {!installOptions.length && missing_bins.length ? (
          <SetupRequirement
            icon={<Terminal className="h-3.5 w-3.5" aria-hidden />}
            label={t("settings.skills.missingCommands", { defaultValue: "Missing CLI" })}
            items={missing_bins}
          />
        ) : null}
        {missing_env.length ? (
          <SetupRequirement
            icon={<KeyRound className="h-3.5 w-3.5" aria-hidden />}
            label={t("settings.skills.missingEnvironment", { defaultValue: "Missing ENV" })}
            items={missing_env}
          />
        ) : null}
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onRefresh}
        className="mt-3 h-9 rounded-full bg-background/60 px-3 text-[11px]"
      >
        <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
        {t("settings.skills.checkAgain", { defaultValue: "Check again" })}
      </Button>
    </section>
  );
}

function SetupRequirement({
  label,
  items,
  icon,
}: {
  label: string;
  items: string[];
  icon: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-1 py-1 text-[11px] text-muted-foreground">
      <span className="inline-flex items-center gap-1.5">
        {icon}
        {label}
      </span>
      {items.map((item) => (
        <code
          key={item}
          className="rounded-full bg-background/80 px-2 py-0.5 font-mono text-[10px] text-foreground/70"
        >
          {item}
        </code>
      ))}
    </div>
  );
}

function Pill({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "muted" | "success" | "warning";
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        tone === "success"
          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : tone === "warning"
            ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
            : "bg-muted text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

function skillSourceLabel(source: string, t: TFunction): string {
  if (source === "workspace") {
    return t("settings.skills.sourceWorkspace", { defaultValue: "Custom" });
  }
  if (source === "builtin") {
    return t("settings.skills.sourceBuiltin", { defaultValue: "Built-in" });
  }
  return source;
}
