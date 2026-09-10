import { channelValidationMessage } from "./validationMessages";
import { useState } from "react";
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
}: {
  presets: ChannelProviderPreset[];
  onApply: (preset: ChannelProviderPreset) => void;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState("");
  if (!presets.length) return null;
  return (
    <fieldset className="mt-3">
      <legend className="mb-1 text-[11px] font-medium text-foreground/85">
        {t("settings.channels.providerPreset", { defaultValue: "Provider" })}
      </legend>
      <div
        className="grid rounded-control bg-muted p-0.5 text-[12px] font-medium text-muted-foreground"
        style={{ gridTemplateColumns: `repeat(${presets.length}, minmax(0, 1fr))` }}
      >
        {presets.map((preset) => (
          <label key={preset.id} className="relative block">
            <input
              type="radio"
              name="channel-provider-preset"
              value={preset.id}
              checked={selected === preset.id}
              onChange={() => {
                setSelected(preset.id);
                onApply(preset);
              }}
              className="peer sr-only"
            />
            <span className="grid min-h-11 cursor-pointer place-items-center rounded-compact px-2 py-1.5 transition-colors hover:text-foreground peer-checked:bg-background peer-checked:text-foreground peer-focus-visible:ring-2 peer-focus-visible:ring-ring sm:min-h-9">
              {preset.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
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
  const { t } = useTranslation();
  const message = validation?.message ? channelValidationMessage(validation.message, t) : undefined;
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
  const { t } = useTranslation();
  const checks = validation.checks.filter((check) => check.id !== "manual_review" && !(check.id.startsWith("field:") && check.status === "pass"));
  if (checks.length <= 1) return null;
  return (
    <div>
      <div className="mb-2 text-[12px] font-semibold text-foreground">
        {t("settings.channels.connectionChecks")}
      </div>
      <div className="space-y-2">
        {checks.slice(0, 6).map((check) => (
          <div key={check.id} className="flex gap-2 text-[12px] leading-5">
            <span className={cn("mt-0.5", channelValidationCheckIconClass(check.status))}>
              {channelValidationCheckIcon(check.status)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-medium text-foreground/85">{channelValidationMessage(check.label, t)}</div>
              {check.message ? (
                <div className="text-muted-foreground">{channelValidationMessage(check.message, t)}</div>
              ) : null}
              {check.action_url ? (
                <a
                  href={check.action_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-foreground underline decoration-border underline-offset-4"
                >
                  {t("settings.channels.open")}
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
