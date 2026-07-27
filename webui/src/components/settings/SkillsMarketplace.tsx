import { useEffect, useMemo, useState } from "react";
import {
  Check,
  Download,
  ExternalLink,
  Loader2,
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
import type { MarketplaceSkillSummary, SkillSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export function SkillsMarketplace({ installedSkills }: { installedSkills: SkillSummary[] }) {
  const { token } = useClient();
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketplaceSkillSummary[]>([]);
  const [trending, setTrending] = useState<MarketplaceSkillSummary[]>([]);
  const [trends, setTrends] = useState<Record<string, number[]>>({});
  const [loading, setLoading] = useState(false);
  const [trendingLoading, setTrendingLoading] = useState(true);
  const [error, setError] = useState("");
  const [installSupported, setInstallSupported] = useState<boolean | null>(null);
  const [selected, setSelected] = useState<MarketplaceSkillSummary | null>(null);
  const [installing, setInstalling] = useState("");
  const installedNames = useMemo(
    () => new Set(installedSkills.map((skill) => skill.name)),
    [installedSkills],
  );

  useEffect(() => {
    let cancelled = false;
    setTrendingLoading(true);
    fetchTrendingMarketplaceSkills(token)
      .then((payload) => {
        if (cancelled) return;
        setTrending(payload.skills);
        setInstallSupported(payload.install_supported);
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
    const unresolved = skills.filter((skill) => !(skill.id in trends));
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
          setInstallSupported(payload.install_supported);
        })
        .catch((reason: unknown) => {
          if (cancelled) return;
          setResults([]);
          setError(
            reason instanceof Error
              ? reason.message
              : t("settings.skills.marketplaceSearchFailed", {
                  defaultValue: "Could not search skills.sh.",
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
    setInstalling(skill.skill_id);
    setError("");
    try {
      const payload = await installMarketplaceSkill(token, skill.source, skill.skill_id);
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
      setInstalling("");
    }
  };

  return (
    <section className="space-y-4">
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("settings.skills.marketplaceSearchPlaceholder", {
            defaultValue: "Search skills.sh",
          })}
          aria-label={t("settings.skills.marketplaceSearchLabel", {
            defaultValue: "Search skills.sh",
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
                    defaultValue: "Trending today",
                  })}
                </h2>
                <p className="mt-0.5 text-[12px] text-muted-foreground">
                  {t("settings.skills.marketplaceTrendingDescription", {
                    defaultValue:
                      "Most installed across sources in 24h · curves show the 8-week trend",
                  })}
                </p>
              </div>
              <a
                href="https://skills.sh/trending"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {t("settings.skills.marketplaceViewAll", { defaultValue: "View all" })}
                <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            </div>
            {trendingLoading ? (
              <TrendingSkeleton />
            ) : trending.length ? (
              <MarketplaceSkillList
                skills={trending}
                installedNames={installedNames}
                installing={installing}
                installSupported={installSupported}
                metric="24h"
                trends={trends}
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
      ) : !loading && results.length === 0 && !error ? (
        <div className="rounded-[22px] bg-settings-surface px-5 py-12 text-center text-sm text-muted-foreground">
          {t("settings.skills.marketplaceEmpty", {
            query: query.trim(),
            defaultValue: "No skills found for “{{query}}”.",
          })}
        </div>
      ) : (
        <div className="overflow-hidden rounded-[22px] bg-settings-surface">
          <MarketplaceSkillList
            skills={results}
            installedNames={installedNames}
            installing={installing}
            installSupported={installSupported}
            metric="total"
            trends={trends}
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
                  defaultValue:
                    "This third-party skill comes from {{source}} and may include instructions or executable scripts.",
                })}
              </span>
              <code className="block rounded-md bg-muted px-2 py-1 text-[12px] text-foreground">
                {selected?.source}
              </code>
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

function MarketplaceSkillList({
  skills,
  installedNames,
  installing,
  installSupported,
  metric,
  trends,
  onSelect,
}: {
  skills: MarketplaceSkillSummary[];
  installedNames: Set<string>;
  installing: string;
  installSupported: boolean | null;
  metric: "total" | "24h";
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
          isInstalling={installing === skill.skill_id}
          installBusy={Boolean(installing)}
          installSupported={installSupported}
          metric={metric}
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
  installSupported,
  metric,
  trend,
  onSelect,
}: {
  skill: MarketplaceSkillSummary;
  installed: boolean;
  isInstalling: boolean;
  installBusy: boolean;
  installSupported: boolean | null;
  metric: "total" | "24h";
  trend?: number[];
  onSelect: (skill: MarketplaceSkillSummary) => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex min-w-0 items-center gap-2 px-1 py-3.5 sm:gap-3 sm:px-2">
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
              defaultValue: "Open {{name}} on skills.sh",
            })}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        </div>
        <p className="mt-1 truncate text-[12px] text-muted-foreground">
          {skill.source}
          <span className="mx-1.5">·</span>
          {metric === "24h"
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
        </p>
      </div>
      <TrendSparkline values={trend} />
      <Button
        type="button"
        size="sm"
        variant={installed ? "secondary" : "default"}
        disabled={installed || installBusy || installSupported === false}
        onClick={() => onSelect(skill)}
        className={cn(
          "min-w-[82px] rounded-full px-2.5 sm:min-w-[92px] sm:px-3",
          installed && "text-emerald-700",
        )}
        title={
          installSupported === false
            ? t("settings.skills.marketplaceNpxRequired", {
                defaultValue: "Node.js with npx is required",
              })
            : undefined
        }
      >
        {isInstalling ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : installed ? (
          <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden />
        ) : (
          <Download className="mr-1.5 h-3.5 w-3.5" aria-hidden />
        )}
        {isInstalling
          ? t("settings.skills.marketplaceInstalling", {
              defaultValue: "Installing",
            })
          : installed
            ? t("settings.skills.marketplaceInstalled", {
                defaultValue: "Installed",
              })
            : t("settings.skills.marketplaceInstall", {
                defaultValue: "Install",
              })}
      </Button>
    </div>
  );
}

function TrendSparkline({ values }: { values?: number[] }) {
  const { t } = useTranslation();

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
      aria-label="8-week install trend"
    >
      <title>8-week install trend</title>
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
