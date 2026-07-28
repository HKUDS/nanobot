import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ExternalLink,
  Loader2,
  PackagePlus,
  Search,
  ShieldAlert,
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
import {
  fetchMarketplaceSkillTrends,
  fetchTrendingMarketplaceSkills,
  installMarketplaceSkill,
  searchMarketplaceSkills,
} from "@/lib/api";
import { notifySkillsChanged } from "@/lib/skill-events";
import type {
  MarketplaceProvider,
  MarketplaceSkillSummary,
  SkillSummary,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export function SkillsMarketplace({
  installedSkills,
  installing,
  onInstallingChange,
}: {
  installedSkills: SkillSummary[];
  installing: string;
  onInstallingChange: (skillId: string) => void;
}) {
  const { token } = useClient();
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketplaceSkillSummary[]>([]);
  const [trending, setTrending] = useState<MarketplaceSkillSummary[]>([]);
  const [trends, setTrends] = useState<Record<string, number[]>>({});
  const [loading, setLoading] = useState(false);
  const [trendingLoading, setTrendingLoading] = useState(true);
  const [error, setError] = useState("");
  const [provider, setProvider] = useState<MarketplaceProvider>("all");
  const [selected, setSelected] = useState<MarketplaceSkillSummary | null>(null);
  const installedNames = useMemo(
    () => new Set(installedSkills.map((skill) => skill.name)),
    [installedSkills],
  );
  const visibleTrending = useMemo(
    () =>
      provider === "all"
        ? trending
        : trending.filter((skill) => skill.provider === provider),
    [provider, trending],
  );
  const visibleResults = useMemo(
    () =>
      provider === "all"
        ? results
        : results.filter((skill) => skill.provider === provider),
    [provider, results],
  );

  useEffect(() => {
    let cancelled = false;
    setTrendingLoading(true);
    fetchTrendingMarketplaceSkills(token)
      .then((payload) => {
        if (cancelled) return;
        setTrending(payload.skills);
      })
      .catch(() => {
        if (!cancelled) setTrending([]);
      })
      .finally(() => {
        if (!cancelled) setTrendingLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    const skills = query.trim().length < 2 ? trending : results;
    const unresolved = skills.filter(
      (skill) => skill.provider === "skills_sh" && !(skill.id in trends),
    );
    if (!unresolved.length) return;

    let cancelled = false;
    fetchMarketplaceSkillTrends(token, unresolved.map((skill) => skill.id))
      .then((payload) => {
        if (!cancelled) {
          setTrends((current) => ({ ...current, ...payload.trends }));
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [query, results, token, trending, trends]);

  useEffect(() => {
    const normalized = query.trim();
    if (normalized.length < 2) {
      setResults([]);
      setLoading(false);
      setError("");
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      searchMarketplaceSkills(token, normalized)
        .then((payload) => {
          if (cancelled) return;
          setResults(payload.skills);
        })
        .catch((reason: unknown) => {
          if (cancelled) return;
          setResults([]);
          setError(
            reason instanceof Error
              ? reason.message
              : t("settings.skills.marketplaceSearchFailed", {
                  defaultValue: "Could not search skill marketplaces.",
                }),
          );
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, t, token]);

  const install = async (skill: MarketplaceSkillSummary) => {
    setSelected(null);
    onInstallingChange(skill.id);
    setError("");
    try {
      const payload = await installMarketplaceSkill(
        token,
        skill.provider,
        skill.source,
        skill.skill_id,
        skill.version,
      );
      notifySkillsChanged(payload);
      setResults((current) =>
        current.map((item) =>
          item.id === skill.id ? { ...item, installed: true } : item,
        ),
      );
      setTrending((current) =>
        current.map((item) =>
          item.id === skill.id ? { ...item, installed: true } : item,
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("settings.skills.marketplaceInstallFailed", {
              defaultValue: "Could not install this skill.",
            }),
      );
    } finally {
      onInstallingChange("");
    }
  };

  return (
    <section className="space-y-4">
      <div className="space-y-2">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("settings.skills.marketplaceSearchPlaceholder", {
              defaultValue: "Search skills",
            })}
            aria-label={t("settings.skills.marketplaceSearchLabel", {
              defaultValue: "Search skills",
            })}
            className="h-11 rounded-[14px] bg-settings-surface pl-9"
          />
          {loading ? (
            <span
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              role="status"
              aria-label={t("settings.skills.marketplaceSearching", {
                defaultValue: "Searching",
              })}
            >
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            </span>
          ) : null}
        </div>
        <ProviderFilter value={provider} onChange={setProvider} />
      </div>

      {error ? (
        <div className="rounded-[14px] bg-destructive/10 px-3 py-2.5 text-[13px] text-destructive">
          {error}
        </div>
      ) : null}

      {query.trim().length < 2 ? (
        <section className="overflow-hidden rounded-[22px] bg-settings-surface">
          <div className="flex flex-col items-start gap-2 border-b border-border/45 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div>
              <h2 className="text-[14px] font-semibold">
                {t("settings.skills.marketplaceTrendingTitle", {
                  defaultValue: "Trending by marketplace",
                })}
              </h2>
              <p className="mt-0.5 text-[12px] text-muted-foreground">
                {t("settings.skills.marketplaceTrendingDescription", {
                  defaultValue: "Each marketplace keeps its own ranking and install metrics.",
                })}
              </p>
            </div>
            {provider !== "all" ? (
              <a
                href={providerUrl(provider)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {t("settings.skills.marketplaceViewAll", { defaultValue: "View all" })}
                <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            ) : null}
          </div>
          {trendingLoading ? (
            <TrendingSkeleton />
          ) : visibleTrending.length ? (
            <MarketplaceSkillGroups
              skills={visibleTrending}
              installedNames={installedNames}
              installing={installing}
              trends={trends}
              grouped={provider === "all"}
              onSelect={setSelected}
            />
          ) : (
            <div className="px-5 py-10 text-center text-[13px] text-muted-foreground">
              {t("settings.skills.marketplaceTrendingUnavailable", {
                defaultValue: "Trending skills are temporarily unavailable.",
              })}
            </div>
          )}
        </section>
      ) : !loading && visibleResults.length === 0 && !error ? (
        <div className="rounded-[22px] bg-settings-surface px-5 py-12 text-center text-sm text-muted-foreground">
          {t("settings.skills.marketplaceEmpty", {
            query: query.trim(),
            defaultValue: "No skills found for “{{query}}”.",
          })}
        </div>
      ) : (
        <div className="overflow-hidden rounded-[22px] bg-settings-surface">
          <MarketplaceSkillGroups
            skills={visibleResults}
            installedNames={installedNames}
            installing={installing}
            trends={trends}
            grouped={provider === "all"}
            onSelect={setSelected}
          />
        </div>
      )}

      <AlertDialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <AlertDialogContent className="rounded-[20px]">
          <AlertDialogHeader>
            <div className="mb-1 flex h-10 w-10 items-center justify-center rounded-[12px] bg-amber-500/10 text-amber-700 dark:text-amber-300">
              <ShieldAlert className="h-5 w-5" aria-hidden />
            </div>
            <AlertDialogTitle>
              {t("settings.skills.marketplaceConfirmTitle", {
                name: selected?.name ?? "",
                defaultValue: "Install {{name}}?",
              })}
            </AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <span className="block">
                {t("settings.skills.marketplaceConfirmDescription", {
                  source: selected?.source ?? "",
                  provider: selected ? providerLabel(selected.provider) : "",
                  defaultValue:
                    "This third-party skill comes from {{provider}} ({{source}}) and may include instructions or executable scripts.",
                })}
              </span>
              <span className="flex flex-wrap items-center gap-2 rounded-md bg-muted px-2 py-1.5 text-[12px] text-foreground">
                {selected ? <ProviderMark provider={selected.provider} /> : null}
                <code>{selected?.source}</code>
                {selected?.version ? <span>v{selected.version}</span> : null}
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {t("common.cancel", { defaultValue: "Cancel" })}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (selected) void install(selected);
              }}
            >
              {t("settings.skills.marketplaceConfirmInstall", {
                defaultValue: "Install skill",
              })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

function ProviderFilter({
  value,
  onChange,
}: {
  value: MarketplaceProvider;
  onChange: (provider: MarketplaceProvider) => void;
}) {
  const { t } = useTranslation();
  const providers: MarketplaceProvider[] = ["all", "skills_sh", "skillhub"];
  return (
    <div
      className="flex w-fit items-center gap-0.5 rounded-full bg-settings-surface p-1"
      role="tablist"
      aria-label={t("settings.skills.marketplaceProviderFilter", {
        defaultValue: "Skill source",
      })}
    >
      {providers.map((provider) => (
        <button
          key={provider}
          type="button"
          role="tab"
          aria-selected={value === provider}
          onClick={() => onChange(provider)}
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-[12px] font-medium text-muted-foreground transition-colors",
            value === provider && "bg-background text-foreground shadow-sm",
          )}
        >
          {provider !== "all" ? <ProviderDot provider={provider} /> : null}
          {provider === "all"
            ? t("settings.skills.marketplaceProviderAll", { defaultValue: "All" })
            : providerLabel(provider)}
        </button>
      ))}
    </div>
  );
}

function MarketplaceSkillGroups({
  skills,
  installedNames,
  installing,
  trends,
  grouped,
  onSelect,
}: {
  skills: MarketplaceSkillSummary[];
  installedNames: Set<string>;
  installing: string;
  trends: Record<string, number[]>;
  grouped: boolean;
  onSelect: (skill: MarketplaceSkillSummary) => void;
}) {
  const { t } = useTranslation();
  const providers: Array<Exclude<MarketplaceProvider, "all">> = [
    "skills_sh",
    "skillhub",
  ];
  if (!grouped) {
    return (
      <MarketplaceSkillList
        skills={skills}
        installedNames={installedNames}
        installing={installing}
        trends={trends}
        onSelect={onSelect}
      />
    );
  }
  return (
    <div>
      {providers.map((provider) => {
        const providerSkills = skills.filter((skill) => skill.provider === provider);
        if (!providerSkills.length) return null;
        return (
          <section key={provider} className="border-t border-border/45 first:border-t-0">
            <div className="flex items-center justify-between px-5 pb-1 pt-3.5">
              <ProviderMark provider={provider} />
              <a
                href={providerUrl(provider)}
                target="_blank"
                rel="noreferrer"
                className="text-muted-foreground transition-colors hover:text-foreground"
                aria-label={t("settings.skills.marketplaceOpenProvider", {
                  provider: providerLabel(provider),
                  defaultValue: "Open {{provider}}",
                })}
              >
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </a>
            </div>
            <MarketplaceSkillList
              skills={providerSkills}
              installedNames={installedNames}
              installing={installing}
              trends={trends}
              onSelect={onSelect}
            />
          </section>
        );
      })}
    </div>
  );
}

function MarketplaceSkillList({
  skills,
  installedNames,
  installing,
  trends,
  onSelect,
}: {
  skills: MarketplaceSkillSummary[];
  installedNames: Set<string>;
  installing: string;
  trends: Record<string, number[]>;
  onSelect: (skill: MarketplaceSkillSummary) => void;
}) {
  return (
    <div className="divide-y divide-border/45 px-3 sm:px-4">
      {skills.map((skill) => (
        <MarketplaceSkillRow
          key={skill.id}
          skill={skill}
          installed={skill.installed || installedNames.has(skill.skill_id)}
          isInstalling={installing === skill.id}
          installBusy={Boolean(installing)}
          trend={trends[skill.id]}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

function MarketplaceSkillRow({
  skill,
  installed,
  isInstalling,
  installBusy,
  trend,
  onSelect,
}: {
  skill: MarketplaceSkillSummary;
  installed: boolean;
  isInstalling: boolean;
  installBusy: boolean;
  trend?: number[];
  onSelect: (skill: MarketplaceSkillSummary) => void;
}) {
  const { t } = useTranslation();
  const actionLabel = t(
    isInstalling
      ? "settings.skills.marketplaceInstalling"
      : installed
        ? "settings.skills.marketplaceInstalled"
        : "settings.skills.marketplaceInstall",
  );

  return (
    <div className="group flex min-w-0 items-center gap-2 px-1 py-3.5 sm:gap-3 sm:px-2">
      {skill.rank ? (
        <span className="w-6 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted-foreground/65 sm:w-7 sm:text-[12px]">
          #{skill.rank}
        </span>
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-[14px] font-semibold text-foreground">
            {skill.name}
          </h3>
          <a
            href={skill.url}
            target="_blank"
            rel="noreferrer"
            aria-label={t("settings.skills.marketplaceOpen", {
              name: skill.name,
              provider: providerLabel(skill.provider),
              defaultValue: "Open {{name}} on {{provider}}",
            })}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        </div>
        <div className="mt-1 flex min-w-0 items-center gap-1.5 truncate text-[12px] text-muted-foreground">
          {skill.source}
          {skill.version ? <span>· v{skill.version}</span> : null}
          <span>·</span>
          {skill.metric === "installs_24h"
            ? t("settings.skills.marketplaceInstalls24h", {
                count: skill.installs,
                formattedCount: skill.installs.toLocaleString(),
                defaultValue: "{{formattedCount}} installs / 24h",
              })
            : t("settings.skills.marketplaceInstalls", {
                count: skill.installs,
                formattedCount: skill.installs.toLocaleString(),
                defaultValue: "{{formattedCount}} installs",
              })}
        </div>
      </div>
      {skill.provider === "skills_sh" ? <TrendSparkline values={trend} /> : null}
      <Button
        type="button"
        aria-label={`${actionLabel} ${skill.name}`}
        size="icon"
        variant="ghost"
        disabled={installed || installBusy || !skill.install_supported}
        onClick={() => onSelect(skill)}
        className={cn(
          "h-9 w-9 shrink-0 rounded-full bg-muted/70 text-muted-foreground transition-[opacity,color,background-color,transform] hover:scale-[1.03] hover:bg-foreground hover:text-background focus-visible:bg-foreground focus-visible:text-background focus-visible:opacity-100 sm:opacity-[0.55] sm:group-hover:opacity-100",
          installed &&
            "bg-emerald-500/10 text-emerald-700 disabled:opacity-100 dark:text-emerald-300",
        )}
        title={
          !skill.install_supported
            ? t("settings.skills.marketplaceNpxRequired", {
                defaultValue: "Node.js with npx is required",
              })
            : `${actionLabel} ${skill.name}`
        }
      >
        {isInstalling ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : installed ? (
          <Check className="h-4 w-4" aria-hidden />
        ) : (
          <PackagePlus className="h-4 w-4" aria-hidden />
        )}
      </Button>
    </div>
  );
}

function ProviderMark({
  provider,
}: {
  provider: Exclude<MarketplaceProvider, "all">;
}) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-[12px] font-medium text-foreground/75">
      <ProviderDot provider={provider} />
      {providerLabel(provider)}
    </span>
  );
}

function ProviderDot({
  provider,
}: {
  provider: Exclude<MarketplaceProvider, "all">;
}) {
  return (
    <span
      className={cn(
        "h-1.5 w-1.5 shrink-0 rounded-full",
        provider === "skillhub" ? "bg-[#006EFF]" : "bg-foreground/55",
      )}
      aria-hidden
    />
  );
}

function providerLabel(provider: Exclude<MarketplaceProvider, "all">): string {
  return provider === "skillhub" ? "SkillHub" : "skills.sh";
}

function providerUrl(provider: Exclude<MarketplaceProvider, "all">): string {
  return provider === "skillhub" ? "https://skillhub.cn" : "https://skills.sh/trending";
}

function TrendSparkline({ values }: { values?: number[] }) {
  const { t } = useTranslation();
  const trendLabel = t("settings.skills.marketplaceTrendLabel", {
    defaultValue: "8-week install trend",
  });

  if (values === undefined) {
    return <span className="hidden h-[30px] w-24 shrink-0 sm:block" aria-hidden />;
  }
  if (values.length < 2) {
    return (
      <span className="hidden w-24 shrink-0 text-center text-[11px] text-muted-foreground/60 sm:block">
        {t("settings.skills.marketplaceNoTrend", { defaultValue: "No trend yet" })}
      </span>
    );
  }

  const width = 96;
  const height = 30;
  const padding = 2;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const points = values.map((value, index) => ({
    x: padding + (index / (values.length - 1)) * (width - padding * 2),
    y: padding + ((max - value) / range) * (height - padding * 2),
  }));
  const line = points.slice(1).reduce((path, point, index) => {
    const previous = points[index];
    const middle = (previous.x + point.x) / 2;
    return `${path} C ${middle} ${previous.y}, ${middle} ${point.y}, ${point.x} ${point.y}`;
  }, `M ${points[0].x} ${points[0].y}`);
  const area = `${line} L ${points.at(-1)?.x ?? width} ${height} L ${points[0].x} ${height} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="hidden h-[30px] w-24 shrink-0 overflow-visible text-foreground/40 sm:block"
      role="img"
      aria-label={trendLabel}
    >
      <title>{trendLabel}</title>
      <path d={area} fill="currentColor" opacity="0.06" />
      <path
        d={line}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TrendingSkeleton() {
  return (
    <div className="divide-y divide-border/45 px-5" aria-hidden>
      {Array.from({ length: 5 }, (_, index) => (
        <div key={index} className="flex items-center gap-3 py-4">
          <div className="h-3 w-5 animate-pulse rounded bg-muted" />
          <div className="flex-1 space-y-2">
            <div className="h-3.5 w-48 max-w-[55%] animate-pulse rounded bg-muted" />
            <div className="h-3 w-32 max-w-[40%] animate-pulse rounded bg-muted/70" />
          </div>
          <div className="h-8 w-[82px] animate-pulse rounded-full bg-muted sm:w-[92px]" />
        </div>
      ))}
    </div>
  );
}
