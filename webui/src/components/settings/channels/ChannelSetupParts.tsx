import { channelValidationMessage } from "./validationMessages";
import { useEffect, useMemo, useState } from "react";
import { Clipboard, ExternalLink, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelUiPresentation } from "@/channel-plugins/registry";
import { Button } from "@/components/ui/button";
import {
  type ChannelProviderPreset,
  type ChannelSetupPresentation,
} from "@/components/settings/channels/catalog";
import {
  channelValidationCheckIcon,
  channelValidationCheckIconClass,
  channelValidationStatusClass,
  channelValidationStatusIcon,
  channelValidationStatusLabel,
} from "@/components/settings/channels/CredentialForm";
import { copyTextToClipboard } from "@/lib/clipboard";
import type {
  ChannelValidationPayload,
  NanobotFeatureInfo,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export function ChannelSetupActions({
  feature,
  setup,
  onNotice,
}: {
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
  onNotice: (message: string | null) => void;
}) {
  const { t } = useTranslation();
  if (!setup.actions?.length) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      {setup.actions.map((action) => (
        <Button
          key={action.id}
          type="button"
          size="sm"
          variant="secondary"
          className="h-8 rounded-full bg-background/80 px-3 text-[12px] font-semibold settings-hover"
          onClick={() => {
            if (action.copyText) {
              void copyTextToClipboard(action.copyText).then((ok) =>
                onNotice(
                  ok
                    ? t("settings.channels.helperCopied", {
                      name: action.label,
                      defaultValue: "{{name}} copied.",
                    })
                    : t("settings.channels.helperCopyFailed", {
                      name: action.label,
                      defaultValue: "Could not copy {{name}}.",
                    }),
                ),
              );
            }
          }}
        >
          {action.copyText ? <Clipboard className="mr-1.5 h-3.5 w-3.5" aria-hidden /> : null}
          {action.label}
        </Button>
      ))}
      <span className="sr-only">
        {channelUiPresentation(feature.name, feature.webui)?.displayName ?? feature.display_name}
      </span>
    </div>
  );
}

export function ChannelProviderPresets({
  presets,
  onApply,
  label,
  disabled = false,
}: {
  presets: ChannelProviderPreset[];
  onApply: (preset: ChannelProviderPreset) => void;
  label?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  if (!presets.length) return null;
  return (
    <fieldset>
      <legend className="mb-1 text-[11px] font-medium text-foreground/85">
        {label ?? t("settings.channels.providerPreset", { defaultValue: "Provider" })}
      </legend>
      <div className="flex flex-wrap gap-2">
        {presets.map((preset) => (
          <Button
            key={preset.id}
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled}
            className="h-8 rounded-full px-3 text-[12px] font-medium"
            onClick={() => onApply(preset)}
          >
            {preset.label}
          </Button>
        ))}
      </div>
    </fieldset>
  );
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
