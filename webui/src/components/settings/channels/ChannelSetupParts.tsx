import { Clipboard } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelUiPresentation } from "@/channel-plugins/registry";
import { Button } from "@/components/ui/button";
import {
  type ChannelProviderPreset,
  type ChannelSetupPresentation,
} from "@/components/settings/channels/catalog";
import { copyTextToClipboard } from "@/lib/clipboard";
import type { NanobotFeatureInfo } from "@/lib/types";

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
