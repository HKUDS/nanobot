import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Check, CircleAlert, ExternalLink, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelUiPresentation } from "@/channel-plugins/registry";
import { channelValidationMessage } from "@/components/settings/channels/validationMessages";
import type { ChannelValidationPayload, NanobotFeatureInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export function channelValidationStatusLabel(
  status: string,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  const labels: Record<string, string> = {
    connected: "Connected",
    configured: "Not verified",
    needs_setup: "Needs setup",
    invalid: "Invalid",
    unsupported: "Manual setup",
  };
  return t(`settings.channels.validation.${status}`, {
    defaultValue: labels[status] ?? "Checked",
  });
}

export function channelValidationStatusClass(status: string): string {
  if (status === "connected") {
    return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-200";
  }
  if (status === "configured") {
    return "bg-blue-500/10 text-blue-700 dark:text-blue-200";
  }
  if (status === "invalid") {
    return "bg-destructive/10 text-destructive";
  }
  return "bg-muted text-muted-foreground";
}

export function channelValidationStatusIcon(status: string): ReactNode {
  if (status === "connected") {
    return <Check className="h-3.5 w-3.5" aria-hidden />;
  }
  if (status === "invalid") {
    return <X className="h-3.5 w-3.5" aria-hidden />;
  }
  return <CircleAlert className="h-3.5 w-3.5" aria-hidden />;
}

function channelValidationCheckIcon(status: string): ReactNode {
  if (status === "pass") return <Check className="h-3.5 w-3.5" aria-hidden />;
  if (status === "fail") return <X className="h-3.5 w-3.5" aria-hidden />;
  return <CircleAlert className="h-3.5 w-3.5" aria-hidden />;
}

function channelValidationCheckIconClass(status: string): string {
  if (status === "pass") return "text-emerald-600";
  if (status === "fail") return "text-destructive";
  if (status === "warn") return "text-amber-600";
  return "text-muted-foreground";
}

function visibleValidationChecks(validation: ChannelValidationPayload | null) {
  return (validation?.checks ?? []).filter(
    (check) => check.id !== "manual_review"
      && !(check.id.startsWith("field:") && check.status === "pass"),
  ).slice(0, 6);
}

export function ChannelValidationProgress({
  validation,
  validating,
  feature,
}: {
  validation: ChannelValidationPayload | null;
  validating: boolean;
  feature: NanobotFeatureInfo;
}) {
  const { t } = useTranslation();
  const checks = useMemo(() => visibleValidationChecks(validation), [validation]);
  const [reveal, setReveal] = useState<{
    validation: ChannelValidationPayload | null;
    settledCheckCount: number;
  }>({ validation: null, settledCheckCount: 0 });
  const settledCheckCount = reveal.validation === validation ? reveal.settledCheckCount : 0;

  useEffect(() => {
    if (validating || !validation) {
      setReveal({ validation: null, settledCheckCount: 0 });
      return;
    }
    setReveal({ validation, settledCheckCount: 0 });
    const timers = checks.map((_, index) => window.setTimeout(
      () => setReveal((current) => (
        current.validation === validation
          ? { validation, settledCheckCount: index + 1 }
          : current
      )),
      (index + 1) * 260,
    ));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [checks, validating, validation]);

  if (!validating && !validation) return null;

  const finished = Boolean(validation) && !validating && settledCheckCount >= checks.length;
  const shownChecks = finished ? checks : checks.slice(0, settledCheckCount + 1);
  const status = validation?.status ?? (feature.configured ? "configured" : "needs_setup");
  const presentation = channelUiPresentation(feature.name, feature.webui);
  const identity = validation?.identity?.name
    ? validation.identity.workspace
      ? `${validation.identity.name} · ${validation.identity.workspace}`
      : validation.identity.name
    : presentation?.displayName ?? feature.display_name;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="rounded-control border border-border/60 bg-muted/25 px-3 py-3"
    >
      <div className="space-y-2.5">
        {validating ? (
          <div className="flex items-center gap-2 px-2.5 text-[12px] font-medium text-foreground/85">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden />
            {t("settings.channels.checking", { defaultValue: "Checking..." })}
          </div>
        ) : null}
        {!validating ? shownChecks.map((check, index) => {
          const pending = !finished && index === settledCheckCount;
          return (
            <div
              key={check.id}
              className="flex animate-in gap-2 px-2.5 fade-in-0 slide-in-from-top-1 text-[12px] leading-5 duration-200 motion-reduce:animate-none"
            >
              <span className={cn(
                "mt-0.5",
                pending ? "text-muted-foreground" : channelValidationCheckIconClass(check.status),
              )}>
                {pending
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  : channelValidationCheckIcon(check.status)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-x-2 font-medium text-foreground/85">
                  <span className="min-w-0 truncate">{channelValidationMessage(check.label, t)}</span>
                  {!pending && check.action_url ? (
                    <a
                      href={check.action_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-foreground underline decoration-border underline-offset-4"
                    >
                      {t("settings.channels.open")}
                      <ExternalLink className="h-3 w-3" aria-hidden />
                    </a>
                  ) : null}
                </div>
                {!pending && check.status !== "pass" && check.message ? (
                  <div className="text-muted-foreground">
                    {channelValidationMessage(check.message, t)}
                  </div>
                ) : null}
              </div>
            </div>
          );
        }) : null}
        {finished ? (
          <div
            className={cn(
              "flex animate-in items-center gap-2 rounded-control px-2.5 py-2 text-[12px] font-medium fade-in-0 duration-200 motion-reduce:animate-none",
              channelValidationStatusClass(status),
            )}
          >
            {channelValidationStatusIcon(status)}
            <span className="min-w-0 truncate font-semibold">{identity}</span>
            <span className="lowercase">{channelValidationStatusLabel(status, t)}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
