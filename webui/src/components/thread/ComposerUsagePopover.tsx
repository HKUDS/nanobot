import { useMemo, useRef } from "react";
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
import { fmtDateTime, formatCompactTokenCount } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface ComposerContextUsage {
  contextTokens: number;
  contextWindowTokens?: number;
}

export interface ComposerRequestUsage {
  id: string;
  timestamp: number;
  inputTokens: number;
  outputTokens?: number;
  cachedTokens?: number;
  estimatedTokens?: number;
  generationMs?: number;
}

interface NormalizedRequestUsage extends ComposerRequestUsage {
  cachedTokens?: number;
  outputTokens: number;
}

function compactDuration(milliseconds: number): string {
  const seconds = milliseconds / 1_000;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

function normalizeRequests(
  requests: readonly ComposerRequestUsage[],
): NormalizedRequestUsage[] {
  return requests
    .filter((request) => Number.isFinite(request.inputTokens) && request.inputTokens > 0)
    .map((request) => ({
      ...request,
      inputTokens: Math.max(0, request.inputTokens),
      outputTokens: Number.isFinite(request.outputTokens)
        ? Math.max(0, request.outputTokens ?? 0)
        : 0,
      ...(Number.isFinite(request.cachedTokens)
        ? { cachedTokens: Math.min(request.inputTokens, Math.max(0, request.cachedTokens ?? 0)) }
        : {}),
    }));
}

export function ComposerUsagePopover({
  context,
  requests,
  requestsUnavailable = false,
}: {
  context: ComposerContextUsage | null;
  requests: readonly ComposerRequestUsage[];
  requestsUnavailable?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  const normalizedRequests = useMemo(() => normalizeRequests(requests), [requests]);
  const hasContext = !!context
    && Number.isFinite(context.contextTokens)
    && context.contextTokens >= 0
    && Number.isFinite(context.contextWindowTokens)
    && (context.contextWindowTokens ?? 0) > 0;
  if (!hasContext && normalizedRequests.length === 0) {
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
    defaultValue: "Open context and reuse details",
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
  const maxInputTokens = Math.max(0, ...normalizedRequests.map((request) => request.inputTokens));
  const hasCacheBreakdown = normalizedRequests.some(
    (request) => typeof request.cachedTokens === "number",
  );
  const numberFormatter = new Intl.NumberFormat(i18n.language);

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
            defaultValue: "Context and reuse",
          })}
          className="w-[min(22rem,calc(100vw-1.5rem))] p-0"
        >
          <div className="px-4 pb-4 pt-3.5">
            {contextPercentage !== null ? (
              <>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[12px] font-medium text-foreground">
                    {t("thread.composer.context.contextTitle", {
                      defaultValue: "Context",
                    })}
                  </span>
                  <span className="text-[11px] tabular-nums text-muted-foreground">
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

            {normalizedRequests.length > 0 && hasCacheBreakdown ? (
              <>
                <div className={cn(
                  "grid grid-cols-[2.5rem_1fr] gap-2",
                  contextPercentage === null ? "mt-0" : "mt-5",
                )}>
                  <div
                    aria-hidden="true"
                    className="flex h-28 flex-col justify-between text-right text-[10px] tabular-nums text-muted-foreground/70"
                  >
                    <span>{formatCompactTokenCount(maxInputTokens)}</span>
                    <span>0</span>
                  </div>
                  <div
                    role="group"
                    aria-label={t("thread.composer.context.cacheTitle", {
                      defaultValue: "Reuse",
                    })}
                    className="flex h-28 items-end gap-1.5 border-b border-border/60"
                  >
                    {normalizedRequests.map((request, index) => {
                      const cachedKnown = typeof request.cachedTokens === "number";
                      const cachedTokens = request.cachedTokens ?? 0;
                      const notReusedTokens = Math.max(0, request.inputTokens - cachedTokens);
                      const cachedPercentage = cachedKnown
                        ? Math.round(cachedTokens / request.inputTokens * 100)
                        : null;
                      const cachedHeight = cachedKnown
                        ? cachedTokens / request.inputTokens * 100
                        : 0;
                      const barHeight = request.inputTokens / maxInputTokens * 108;
                      const detailParts = [
                        fmtDateTime(request.timestamp, i18n.language),
                        t("thread.composer.context.input", {
                          defaultValue: "{{tokens}} input",
                          tokens: numberFormatter.format(request.inputTokens),
                        }),
                        cachedKnown
                          ? t("thread.composer.context.reusedDetail", {
                              defaultValue: "{{tokens}} reused ({{percent}}%)",
                              tokens: numberFormatter.format(cachedTokens),
                              percent: cachedPercentage,
                            })
                          : null,
                        t("thread.composer.context.output", {
                          defaultValue: "{{tokens}} output",
                          tokens: numberFormatter.format(request.outputTokens),
                        }),
                        typeof request.generationMs === "number"
                          ? t("thread.composer.context.duration", {
                              defaultValue: "{{duration}} generation",
                              duration: compactDuration(request.generationMs),
                            })
                          : null,
                        (request.estimatedTokens ?? 0) > 0
                          ? t("message.usage.estimated", {
                              defaultValue: "Includes estimated usage",
                            })
                          : null,
                      ].filter((part): part is string => !!part);

                      return (
                        <span
                          key={request.id}
                          className={cn(
                            "flex h-full min-w-0 flex-1 items-end justify-center rounded-sm",
                            "opacity-70 transition-opacity hover:opacity-100",
                            index === normalizedRequests.length - 1 && "opacity-100",
                          )}
                        >
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span
                                role="img"
                                tabIndex={0}
                                aria-label={detailParts.join(". ")}
                                data-testid="cache-usage-bar"
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
                                {detailParts[0]}
                              </span>
                              {detailParts.slice(1).map((part, detailIndex) => (
                                <span
                                  key={detailIndex}
                                  className="mt-0.5 block text-muted-foreground"
                                >
                                  {part}
                                </span>
                              ))}
                            </TooltipContent>
                          </Tooltip>
                        </span>
                      );
                    })}
                  </div>
                </div>
                <div className="ml-[3.25rem] mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="kv-cache-reused h-2.5 w-4 rounded-[2px]" aria-hidden="true" />
                    {t("thread.composer.context.reused", {
                      defaultValue: "Reused",
                    })}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="kv-cache-not-reused h-2.5 w-4 rounded-[2px]" aria-hidden="true" />
                    {t("thread.composer.context.notReused", { defaultValue: "Not reused" })}
                  </span>
                </div>
              </>
            ) : null}

            {normalizedRequests.length === 0 && !requestsUnavailable ? (
              <p className="mt-3 text-[12px] leading-relaxed text-muted-foreground">
                {t("thread.composer.context.empty", {
                  defaultValue: "Usage appears after the first response.",
                })}
              </p>
            ) : null}
          </div>
        </PopoverContent>
      </TooltipProvider>
    </Popover>
  );
}
