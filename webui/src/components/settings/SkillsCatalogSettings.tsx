import type { TFunction } from "i18next";
import { Brain, Check, CircleAlert, KeyRound, Loader2, Terminal } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { fetchSkillDetail } from "@/lib/api";
import type { SkillDetail, SkillSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export function SkillsCatalogSettings({ skills }: { skills: SkillSummary[] }) {
  const { t } = useTranslation();
  const availableCount = skills.filter((skill) => skill.available).length;
  const [selectedSkill, setSelectedSkill] = useState<SkillSummary | null>(null);

  return (
    <div className="space-y-7">
      <section className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <p className="max-w-[680px] text-[13px] leading-5 text-muted-foreground">
          {t("settings.skills.description", {
            defaultValue: "Review the instruction skills this agent can load during a conversation.",
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

      <section>
        <div className="flex items-center justify-between border-b border-border/45 pb-3">
          <h2 className="mb-2 px-1 text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
            {t("settings.skills.featured", { defaultValue: "Agent skills" })}
          </h2>
          <span className="rounded-full bg-muted px-2.5 py-1 text-[12px] font-medium text-muted-foreground">
            {skills.length}
          </span>
        </div>
        {skills.length ? (
          <div className="grid gap-x-10 gap-y-1 py-3 md:grid-cols-2">
            {skills.map((skill) => (
              <SkillCatalogRow
                key={`${skill.source}:${skill.name}`}
                skill={skill}
                onSelect={setSelectedSkill}
              />
            ))}
          </div>
        ) : (
          <div className="px-3 py-12 text-center text-sm text-muted-foreground">
            {t("settings.skills.empty", { defaultValue: "No skills are available." })}
          </div>
        )}
      </section>

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
  const sourceLabel = skillSourceLabel(skill.source, t);
  const StatusIcon = skill.available ? Check : CircleAlert;
  const statusLabel = skill.available
    ? t("settings.skills.statusAvailable", { defaultValue: "Available" })
    : t("settings.skills.statusUnavailable", { defaultValue: "Unavailable" });

  return (
    <button
      type="button"
      aria-label={t("settings.skills.openDetails", {
        name: skill.name,
        defaultValue: "Open details for {{name}}",
      })}
      onClick={() => onSelect(skill)}
      className={cn(
        "group flex min-w-0 items-center gap-3 rounded-[16px] px-3 py-3 text-left transition-colors",
        "hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        !skill.available && "opacity-65",
      )}
    >
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px] bg-muted/70 text-muted-foreground">
        <Brain className="h-5 w-5" strokeWidth={1.8} aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-[15px] font-semibold leading-5 text-foreground">
            {skill.name}
          </h3>
          <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold leading-none text-muted-foreground">
            {sourceLabel}
          </span>
        </div>
        <p className="mt-1 line-clamp-2 text-[13px] leading-5 text-muted-foreground">
          {skill.description}
        </p>
        {!skill.available && skill.unavailable_reason ? (
          <p className="mt-1 truncate text-[12px] leading-4 text-muted-foreground/80">
            {t("settings.skills.unavailableReason", {
              reason: skill.unavailable_reason,
              defaultValue: "Missing: {{reason}}",
            })}
          </p>
        ) : null}
      </div>
      <span
        title={!skill.available && skill.unavailable_reason ? skill.unavailable_reason : undefined}
        className={cn(
          "hidden shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium sm:inline-flex",
          skill.available
            ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            : "bg-muted text-muted-foreground",
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

  useEffect(() => {
    if (!open || !skill) return;
    let cancelled = false;
    setDetail(null);
    setLoading(true);
    setLoadFailed(false);
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
  }, [open, skill, token]);

  if (!skill) return null;

  const activeSkill = detail ?? skill;
  const sourceLabel = skillSourceLabel(activeSkill.source, t);
  const statusLabel = activeSkill.available
    ? t("settings.skills.statusAvailable", { defaultValue: "Available" })
    : t("settings.skills.statusUnavailable", { defaultValue: "Unavailable" });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[min(34rem,calc(100vw-1rem))] max-w-none gap-0 overflow-hidden p-0 sm:max-w-none"
      >
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div className="flex items-start gap-3 pr-8">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[15px] bg-muted/70 text-muted-foreground">
              <Brain className="h-5 w-5" strokeWidth={1.8} aria-hidden />
            </div>
            <div className="min-w-0">
              <SheetTitle className="truncate text-[20px] font-semibold">
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
                <Pill tone={activeSkill.available ? "success" : "muted"}>{statusLabel}</Pill>
              </div>
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
            <div className="mt-7 space-y-6">
              <DetailSection title={t("settings.skills.descriptionTitle", { defaultValue: "Description" })}>
                <p className="text-[14px] leading-6 text-muted-foreground">{activeSkill.description}</p>
              </DetailSection>

              <div className="grid grid-cols-2 gap-2">
                <MetaItem
                  label={t("settings.skills.source", { defaultValue: "Source" })}
                  value={sourceLabel}
                />
                <MetaItem
                  label={t("settings.skills.status", { defaultValue: "Status" })}
                  value={statusLabel}
                />
              </div>

              {!activeSkill.available && activeSkill.unavailable_reason ? (
                <DetailSection
                  title={t("settings.skills.unavailableReasonLabel", {
                    defaultValue: "Unavailable reason",
                  })}
                >
                  <p className="text-[13px] leading-5 text-destructive/85">
                    {activeSkill.unavailable_reason}
                  </p>
                </DetailSection>
              ) : null}

              {detail ? <RequirementsSection detail={detail} /> : null}

              {detail ? <RawInstructionsBlock markdown={detail.raw_markdown} /> : null}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
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
      <summary className="cursor-pointer select-none text-[13px] font-medium text-foreground/90 transition-colors hover:text-foreground">
        {t("settings.skills.rawInstructions", { defaultValue: "Raw SKILL.md" })}
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

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[16px] bg-muted/35 px-3 py-2.5">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate text-[13px] font-medium text-foreground">{value}</div>
    </div>
  );
}

function RequirementsSection({ detail }: { detail: SkillDetail }) {
  const { t } = useTranslation();
  const { bins, env, missing_bins, missing_env } = detail.requirements;
  const hasRequirements = bins.length > 0 || env.length > 0;

  return (
    <DetailSection title={t("settings.skills.requirements", { defaultValue: "Requirements" })}>
      {hasRequirements ? (
        <div className="space-y-3">
          {missing_bins.length ? (
            <RequirementLine
              title={t("settings.skills.missingCommands", { defaultValue: "Missing CLI" })}
              items={missing_bins}
              tone="danger"
              icon={<Terminal className="h-3.5 w-3.5" aria-hidden />}
            />
          ) : null}
          {missing_env.length ? (
            <RequirementLine
              title={t("settings.skills.missingEnvironment", { defaultValue: "Missing ENV" })}
              items={missing_env}
              tone="danger"
              icon={<KeyRound className="h-3.5 w-3.5" aria-hidden />}
            />
          ) : null}
          {bins.length ? (
            <RequirementLine
              title={t("settings.skills.commands", { defaultValue: "Commands" })}
              items={bins}
              icon={<Terminal className="h-3.5 w-3.5" aria-hidden />}
            />
          ) : null}
          {env.length ? (
            <RequirementLine
              title={t("settings.skills.environment", { defaultValue: "Environment variables" })}
              items={env}
              icon={<KeyRound className="h-3.5 w-3.5" aria-hidden />}
            />
          ) : null}
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {t("settings.skills.noRequirements", { defaultValue: "No explicit requirements." })}
        </p>
      )}
    </DetailSection>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-[12px] font-medium text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

function RequirementLine({
  title,
  items,
  icon,
  tone = "muted",
}: {
  title: string;
  items: string[];
  icon: ReactNode;
  tone?: "muted" | "danger";
}) {
  return (
    <div className="space-y-1.5">
      <div
        className={cn(
          "flex items-center gap-1.5 text-[12px]",
          tone === "danger" ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {icon}
        {title}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <Pill key={item}>{item}</Pill>
        ))}
      </div>
    </div>
  );
}

function Pill({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "muted" | "success";
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        tone === "success"
          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
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