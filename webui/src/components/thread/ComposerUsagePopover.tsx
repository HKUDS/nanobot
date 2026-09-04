import { Fragment, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatCompactTokenCount, formatTurnLatency } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface ComposerContextUsage {
  contextTokens: number;
  contextWindowTokens?: number;
}

export interface ComposerRoundUsage {
  id: string;
  timestamp: number;
  inputTokens: number;
  outputTokens?: number;
  cachedTokens?: number;
  estimatedTokens?: number;
  generationMs?: number;
}

interface NormalizedRoundUsage extends ComposerRoundUsage {
  cachedTokens?: number;
  outputTokens: number;
}

function normalizeRounds(
  rounds: readonly ComposerRoundUsage[],
): NormalizedRoundUsage[] {
  return rounds
    .filter((round) => Number.isFinite(round.inputTokens) && round.inputTokens > 0)
    .map((round) => ({
      ...round,
      inputTokens: Math.max(0, round.inputTokens),
      outputTokens: Number.isFinite(round.outputTokens)
        ? Math.max(0, round.outputTokens ?? 0)
        : 0,
      ...(Number.isFinite(round.cachedTokens)
        ? { cachedTokens: Math.min(round.inputTokens, Math.max(0, round.cachedTokens ?? 0)) }
        : {}),
    }));
}

export function ComposerUsagePopover({
  context,
  rounds,
}: {
  context: ComposerContextUsage | null;
  rounds: readonly ComposerRoundUsage[];
}) {
  const { t, i18n } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  const normalizedRounds = useMemo(() => normalizeRounds(rounds), [rounds]);
  const hasContext = !!context
    && Number.isFinite(context.contextTokens)
    && context.contextTokens >= 0
    && Number.isFinite(context.contextWindowTokens)
    && (context.contextWindowTokens ?? 0) > 0;
  if (!hasContext && normalizedRounds.length === 0) {
    return null;
  }

  const contextPercentage = hasContext
    ? Math.min(
        100,
        Math.round(context!.contextTokens / context!.contextWindowTokens! * 100),
      )
    : null;
  const meterPercentage = contextPercentage ?? 0;
  const status = meterPercentage >= 90
    ? "critical"
    : meterPercentage >= 75
      ? "caution"
      : "normal";
  const detailsLabel = t("thread.composer.context.detailsLabel", {
    defaultValue: "Open context usage",
  });
  const contextDescription = contextPercentage === null
    ? detailsLabel
    : t("thread.composer.context.tooltip", {
        defaultValue: "Context {{percent}}%",
        percent: contextPercentage,
      });
  const triggerLabel = contextPercentage === null
    ? detailsLabel
    : `${contextDescription}. ${detailsLabel}`;
  const ringCircumference = 2 * Math.PI * 6;
  const ringLength = ringCircumference * meterPercentage / 100;
  const maxInputTokens = Math.max(0, ...normalizedRounds.map((round) => round.inputTokens));
  const numberFormatter = new Intl.NumberFormat(i18n.language);
  const percentageFormatter = new Intl.NumberFormat(i18n.language, {
    style: "percent",
    maximumFractionDigits: 0,
  });
  const roundDateFormatter = new Intl.DateTimeFormat(i18n.language, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <Popover>
      <TooltipProvider delayDuration={300} skipDelayDuration={80}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                data-testid="composer-context-usage"
                aria-label={triggerLabel}
                className={cn(
                  "touch-target inline-flex size-5 shrink-0 items-center justify-center rounded-full",
                  "text-muted-foreground/75 transition-colors hover:text-foreground/85",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
              >
                {contextPercentage === null ? (
                  <svg viewBox="0 0 16 16" aria-hidden="true" className="size-[15px]">
                    <path
                      d="M3 12V9m5 3V5m5 7V2"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                ) : (
                  <svg
                    viewBox="0 0 16 16"
                    aria-hidden="true"
                    className={cn(
                      "size-[15px] shrink-0 -rotate-90",
                      status === "critical" && "text-destructive",
                      status === "caution" && "text-amber-600 dark:text-amber-400",
                      status === "normal" && "text-muted-foreground/75",
                    )}
                  >
                    <circle
                      cx="8"
                      cy="8"
                      r="6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      className="opacity-20"
                    />
                    <circle
                      cx="8"
                      cy="8"
                      r="6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeDasharray={`${ringLength} ${ringCircumference}`}
                      data-testid="composer-context-meter"
                    />
                  </svg>
                )}
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent
            side="top"
            align="center"
            sideOffset={8}
            className="w-fit max-w-[calc(100vw-2rem)] rounded-full border-border/70 px-2.5 py-1 text-xs font-medium shadow-[0_8px_24px_rgba(15,23,42,0.13)]"
          >
            <span className="whitespace-nowrap tabular-nums">{contextDescription}</span>
          </TooltipContent>
        </Tooltip>

        <PopoverContent
          ref={panelRef}
          side="top"
          align="end"
          sideOffset={10}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            panelRef.current?.focus();
          }}
          aria-label={t("thread.composer.context.panelTitle", {
            defaultValue: "Context usage",
          })}
          className="w-[min(22rem,calc(100vw-1.5rem))] p-0"
        >
          <div className="px-4 pb-4 pt-3.5">
            {contextPercentage !== null ? (
              <>
                <div className="flex items-baseline justify-between gap-3">
                  <div className="flex min-w-0 items-baseline gap-2">
                    <span className="shrink-0 text-[12px] font-medium text-foreground">
                      {t("thread.composer.context.contextTitle", {
                        defaultValue: "Context",
                      })}
                    </span>
                    <span className="truncate text-[11px] tabular-nums text-muted-foreground">
                      {formatCompactTokenCount(context!.contextTokens)} / {formatCompactTokenCount(
                        context!.contextWindowTokens!,
                      )}
                    </span>
                  </div>
                  <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                    {contextPercentage}%
                  </span>
                </div>
                <div
                  role="progressbar"
                  aria-label={contextDescription}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={contextPercentage}
                  className="mt-2 h-1 overflow-hidden rounded-full bg-muted"
                >
                  <div
                    className={cn(
                      "h-full rounded-full",
                      status === "critical" && "bg-destructive",
                      status === "caution" && "bg-amber-500",
                      status === "normal" && "bg-foreground/45",
                    )}
                    style={{ width: `${contextPercentage}%` }}
                  />
                </div>
              </>
            ) : null}

            {normalizedRounds.length > 0 ? (
              <>
                <div className={cn(
                  "flex items-baseline justify-between gap-3",
                  contextPercentage === null ? "mt-0" : "mt-5",
                )}>
                  <span className="text-[12px] font-medium text-foreground">
                    {t("thread.composer.context.recentRounds", {
                      defaultValue: "Recent rounds",
                    })}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {t("thread.composer.context.inputTrend", {
                      defaultValue: "Input tokens",
                    })}
                  </span>
                </div>
                <div
                  role="group"
                  aria-label={t("thread.composer.context.inputTrend", {
                    defaultValue: "Input tokens",
                  })}
                  className="mt-2 flex h-28 items-end gap-1.5 border-b border-border/60"
                >
                    {normalizedRounds.map((round, index) => {
                      const cachedKnown = typeof round.cachedTokens === "number";
                      const cachedTokens = round.cachedTokens ?? 0;
                      const notReusedTokens = Math.max(0, round.inputTokens - cachedTokens);
                      const cacheHitRate = cachedKnown
                        ? percentageFormatter.format(cachedTokens / round.inputTokens)
                        : null;
                      const cachedHeight = cachedKnown
                        ? cachedTokens / round.inputTokens * 100
                        : 0;
                      const barHeight = round.inputTokens / maxInputTokens * 108;
                      const timestampLabel = roundDateFormatter.format(round.timestamp);
                      const detailRows = [
                        {
                          key: "input",
                          label: t("thread.composer.context.input", {
                            defaultValue: "Input tokens",
                          }),
                          value: numberFormatter.format(round.inputTokens),
                        },
                        cachedKnown
                          ? {
                              key: "cache-hit-rate",
                              label: t("thread.composer.context.cacheHitRate", {
                                defaultValue: "KV cache hit rate",
                              }),
                              value: cacheHitRate!,
                            }
                          : null,
                        {
                          key: "output",
                          label: t("thread.composer.context.output", {
                            defaultValue: "Output tokens",
                          }),
                          value: numberFormatter.format(round.outputTokens),
                        },
                        typeof round.generationMs === "number"
                          ? {
                              key: "duration",
                              label: t("thread.composer.context.duration", {
                                defaultValue: "Generation time",
                              }),
                              value: formatTurnLatency(round.generationMs, i18n.language),
                            }
                          : null,
                      ].filter((row): row is NonNullable<typeof row> => !!row);
                      const detailNote = (round.estimatedTokens ?? 0) > 0
                        ? t("message.usage.estimated", {
                            defaultValue: "Includes estimated usage",
                          })
                        : null;
                      const detailLabel = [
                        timestampLabel,
                        ...detailRows.map((row) => `${row.label} ${row.value}`),
                        detailNote,
                      ].filter((part): part is string => !!part).join(". ");

                      return (
                        <span
                          key={round.id}
                          className={cn(
                            "flex h-full min-w-0 flex-1 items-end justify-center rounded-sm",
                            "opacity-70 transition-opacity hover:opacity-100",
                            index === 0 && "justify-start",
                            normalizedRounds.length > 1
                              && index === normalizedRounds.length - 1
                              && "justify-end",
                            index === normalizedRounds.length - 1 && "opacity-100",
                          )}
                        >
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span
                                role="img"
                                tabIndex={0}
                                aria-label={detailLabel}
                                data-testid="round-usage-bar"
                                className={cn(
                                  "flex w-full max-w-7 flex-col overflow-hidden rounded-t-[3px] bg-muted",
                                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                )}
                                style={{ height: `${barHeight}px` }}
                              >
                                {cachedKnown ? (
                                  <>
                                    {notReusedTokens > 0 ? (
                                      <span
                                        className="kv-cache-not-reused block w-full"
                                        style={{ height: `${100 - cachedHeight}%` }}
                                      />
                                    ) : null}
                                    {cachedTokens > 0 ? (
                                      <span
                                        className="kv-cache-reused block w-full"
                                        style={{ height: `${cachedHeight}%` }}
                                      />
                                    ) : null}
                                  </>
                                ) : (
                                  <span className="block h-full w-full bg-muted-foreground/25" />
                                )}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent
                              side="top"
                              align="center"
                              className="max-w-72 px-3 py-2 text-[11px]"
                            >
                              <span
                                className="block font-medium text-foreground"
                              >
                                {timestampLabel}
                              </span>
                              <span className="mt-1 grid grid-cols-[max-content_max-content] gap-x-3 gap-y-0.5">
                                {detailRows.map((row) => (
                                  <Fragment key={row.key}>
                                    <span className="text-muted-foreground">
                                      {row.label}
                                    </span>
                                    <span className="text-end tabular-nums text-foreground">
                                      {row.value}
                                    </span>
                                  </Fragment>
                                ))}
                              </span>
                              {detailNote ? (
                                <span
                                  className="mt-1 block text-muted-foreground"
                                >
                                  {detailNote}
                                </span>
                              ) : null}
                            </TooltipContent>
                          </Tooltip>
                        </span>
                      );
                    })}
                </div>
              </>
            ) : null}

          </div>
        </PopoverContent>
      </TooltipProvider>
    </Popover>
  );
}
