import { useMemo, useState, type ReactNode } from "react";
import { Clipboard, ExternalLink, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  CHANNEL_PRESENTATION,
  docsUrlWithBase,
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
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { copyTextToClipboard } from "@/lib/clipboard";
import { logoFallbackUrls } from "@/lib/provider-brand";
import type {
  ChannelValidationPayload,
  NanobotFeatureInfo,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export function ChannelGuideLink({
  feature,
  setup,
  chatAppsDocsUrl,
  compact = false,
}: {
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
  chatAppsDocsUrl?: string;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const presentation = CHANNEL_PRESENTATION[feature.name];
  const logoUrls = useMemo(
    () => logoFallbackUrls(setup.docsLogoUrl ?? presentation?.logoUrl),
    [presentation?.logoUrl, setup.docsLogoUrl],
  );
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const Icon = presentation?.icon;
  const initials = presentation?.initials ?? feature.display_name.slice(0, 2).toUpperCase();
  const color = presentation?.color ?? "#6B7280";
  const docsUrl = docsUrlWithBase(setup.docsUrl, chatAppsDocsUrl);

  if (!docsUrl) return null;

  return (
    <a
      href={docsUrl}
      target="_blank"
      rel="noreferrer"
      className={cn(
        "inline-flex max-w-full items-center gap-2 border border-border/65 bg-background/90 font-semibold text-foreground shadow-sm transition-colors hover:border-border hover:bg-muted/45",
        compact
          ? "shrink-0 rounded-full py-1 pl-1 pr-2.5 text-[11.5px]"
          : "mt-3 rounded-[12px] py-1.5 pl-1.5 pr-3 text-[12px]",
      )}
    >
      <span
        className={cn(
          "grid shrink-0 place-items-center overflow-hidden border border-border/45 bg-background font-bold",
          compact ? "h-5 w-5 rounded-full text-[9px]" : "h-6 w-6 rounded-[7px] text-[10px]",
        )}
        style={{ color, boxShadow: `inset 0 0 0 1px ${color}16` }}
        aria-hidden
      >
        {logoUrl ? (
          <img
            src={logoUrl}
            alt=""
            decoding="async"
            loading="lazy"
            className={cn("object-contain", compact ? "h-3.5 w-3.5" : "h-4 w-4")}
            onLoad={onLogoLoad}
            onError={onLogoError}
          />
        ) : Icon ? (
          <Icon className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} strokeWidth={2.25} />
        ) : (
          initials
        )}
      </span>
      <span className="truncate">
        {t(`settings.channels.items.${feature.name}.setup.docsLabel`, {
          defaultValue: setup.docsLabel ?? tx("settings.channels.officialGuide", "Official guide"),
        })}
      </span>
      <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
    </a>
  );
}

export function ChannelSetupLinks({
  feature,
  setup,
  chatAppsDocsUrl,
}: {
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
  chatAppsDocsUrl?: string;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <ChannelOfficialLink feature={feature} setup={setup} />
      <ChannelGuideLink feature={feature} setup={setup} chatAppsDocsUrl={chatAppsDocsUrl} compact />
    </div>
  );
}

export function ChannelOfficialLink({
  feature,
  setup,
}: {
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
}) {
  const presentation = CHANNEL_PRESENTATION[feature.name];
  const logoUrls = useMemo(
    () => logoFallbackUrls(setup.docsLogoUrl ?? presentation?.logoUrl),
    [presentation?.logoUrl, setup.docsLogoUrl],
  );
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const Icon = presentation?.icon;
  const color = presentation?.color ?? "#6B7280";
  const label = setup.officialLabel;
  if (!setup.officialUrl || !label) return null;
  return (
    <a
      href={setup.officialUrl}
      target="_blank"
      rel="noreferrer"
      className="inline-flex max-w-full shrink-0 items-center gap-2 rounded-full border border-border/65 bg-background/90 py-1 pl-1 pr-2.5 text-[11.5px] font-semibold text-foreground shadow-sm transition-colors hover:border-border hover:bg-muted/45"
    >
      <span
        className="grid h-5 w-5 shrink-0 place-items-center overflow-hidden rounded-full border border-border/45 bg-background"
        style={{ color, boxShadow: `inset 0 0 0 1px ${color}16` }}
        aria-hidden
      >
        {logoUrl ? (
          <img
            src={logoUrl}
            alt=""
            decoding="async"
            loading="lazy"
            className="h-3.5 w-3.5 object-contain"
            onLoad={onLogoLoad}
            onError={onLogoError}
          />
        ) : Icon ? (
          <Icon className="h-3 w-3" strokeWidth={2.25} />
        ) : null}
      </span>
      <span className="truncate">{label}</span>
      <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
    </a>
  );
}

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
          variant="outline"
          className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold hover:bg-muted/70"
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
        {CHANNEL_PRESENTATION[feature.name]?.displayName ?? feature.display_name}
      </span>
    </div>
  );
}

export function ChannelProviderPresets({
  featureName,
  presets,
  onApply,
}: {
  featureName: string;
  presets: ChannelProviderPreset[];
  onApply: (preset: ChannelProviderPreset) => void;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState("");
  if (!presets.length) return null;
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] font-medium text-foreground/85">
        {t(`settings.channels.items.${featureName}.providerPreset`, {
          defaultValue: "Provider",
        })}
      </div>
      <div
        role="radiogroup"
        aria-label={t(`settings.channels.items.${featureName}.providerPreset`, {
          defaultValue: "Provider",
        })}
        className="grid rounded-[10px] bg-muted/75 p-0.5 text-[12px] font-medium text-muted-foreground shadow-[inset_0_0_0_1px_rgba(15,23,42,0.035)]"
        style={{ gridTemplateColumns: `repeat(${presets.length}, minmax(0, 1fr))` }}
      >
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            role="radio"
            aria-checked={selected === preset.id}
            onClick={() => {
              setSelected(preset.id);
              onApply(preset);
            }}
            className={cn(
              "min-h-8 rounded-[8px] px-2 py-1.5 transition-colors hover:text-foreground",
              selected === preset.id
                && "bg-background text-foreground shadow-[0_1px_2px_rgba(15,23,42,0.10),inset_0_0_0_1px_rgba(15,23,42,0.055)]",
            )}
          >
            {preset.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ChannelValidationBadge({
  validation,
  validating,
  feature,
}: {
  validation: ChannelValidationPayload | null;
  validating: boolean;
  feature: NanobotFeatureInfo;
}) {
  const { t } = useTranslation();
  const status = validation?.status ?? (feature.configured ? "configured" : "needs_setup");
  const label = validating
    ? t("settings.channels.checking", { defaultValue: "Checking..." })
    : channelValidationStatusLabel(status, t);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-medium",
        channelValidationStatusClass(status),
      )}
    >
      {validating ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      ) : (
        channelValidationStatusIcon(status)
      )}
      {label}
    </span>
  );
}

export function ChannelValidationDetails({ validation }: { validation: ChannelValidationPayload | null }) {
  const message = validation?.message;
  if (!validation?.identity?.name && !message) return null;
  return (
    <div className="mt-2 truncate text-[11.5px] text-muted-foreground">
      {validation?.identity?.name
        ? validation.identity.workspace
          ? `${validation.identity.name} · ${validation.identity.workspace}`
          : validation.identity.name
        : message}
    </div>
  );
}

export function ChannelValidationChecks({ validation }: { validation: ChannelValidationPayload }) {
  if (!validation.checks.length) return null;
  return (
    <div className="border-t border-border/60 px-4 py-4">
      <div className="mb-2 text-[12px] font-semibold text-foreground">Connection checks</div>
      <div className="space-y-2">
        {validation.checks.slice(0, 6).map((check) => (
          <div key={check.id} className="flex gap-2 text-[12px] leading-5">
            <span className={cn("mt-0.5", channelValidationCheckIconClass(check.status))}>
              {channelValidationCheckIcon(check.status)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-medium text-foreground/85">{check.label}</div>
              {check.message ? (
                <div className="text-muted-foreground">{check.message}</div>
              ) : null}
              {check.action_url ? (
                <a
                  href={check.action_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-foreground underline decoration-border underline-offset-4"
                >
                  Open
                  <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChannelSetupSteps({
  featureName,
  steps,
  action,
  tryIt,
}: {
  featureName: string;
  steps: string[];
  action?: ReactNode;
  tryIt?: string;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className="border-t border-border/60 px-4 py-4 text-[12.5px] leading-5 text-muted-foreground">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-[12px] font-semibold text-foreground">
          {tx("settings.channels.setupSteps", "Next steps")}
        </div>
        {action}
      </div>
      <ol className="space-y-1.5">
        {steps.map((step, index) => (
          <li key={step} className="flex gap-2">
            <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-background text-[10px] font-semibold text-muted-foreground shadow-sm">
              {index + 1}
            </span>
            <span>
              {t(`settings.channels.items.${featureName}.setup.steps.${index}`, {
                defaultValue: step,
              })}
            </span>
          </li>
        ))}
      </ol>
      {tryIt ? (
        <div className="mt-3 rounded-[12px] border border-border/55 bg-background px-3 py-2 text-[12px] text-muted-foreground">
          <span className="font-medium text-foreground">
            {tx("settings.channels.tryIt", "Try it")}
          </span>
          <span className="ml-2">
            {t(`settings.channels.items.${featureName}.setup.tryIt`, { defaultValue: tryIt })}
          </span>
        </div>
      ) : null}
    </div>
  );
}
