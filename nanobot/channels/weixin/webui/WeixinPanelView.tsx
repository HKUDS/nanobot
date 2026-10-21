import { useEffect, useId, useState, type ReactNode } from "react";
import { Check, ChevronDown, Loader2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelConfigField } from "@/channel-plugins/catalog";
import { CredentialForm } from "@/components/settings/channels/CredentialForm";
import { CHANNEL_SETUP_PANEL_CLASS_NAME, ChannelLogo } from "@/components/settings/channels/ChannelIdentity";
import { Button } from "@/components/ui/button";
import { DisclosureContent } from "@/components/ui/disclosure";
import type { NanobotFeatureInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export type WeixinPanelViewProps = {
  feature: NanobotFeatureInfo;
  actionKey: string | null;
  showBrandLogos: boolean;
  primaryFields: ChannelConfigField[];
  advancedFields: ChannelConfigField[];
  fieldValues: Record<string, string>;
  configuredFields: Set<string>;
  secretVisibilityKey: string;
  runtimeError?: string;
  saving: boolean;
  saveState: "idle" | "saved";
  saveError: string | null;
  connectFlow: ReactNode;
  onInstall: () => void;
  onFieldChange: (key: string, value: string) => void;
};

export function WeixinPanelView({
  feature, actionKey, showBrandLogos, primaryFields, advancedFields, fieldValues,
  configuredFields, secretVisibilityKey, runtimeError, saving, saveState, saveError,
  connectFlow, onInstall, onFieldChange,
}: WeixinPanelViewProps) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const channelTx = channelTranslator(t, "weixin");
  const displayName = channelTx("displayName", "WeChat");
  const enabledBusy = actionKey === `enable:${feature.name}`;
  const missingSupport = feature.enabled && !feature.installed;
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const advancedPanelId = useId();
  useEffect(() => setVisibleSecrets({}), [secretVisibilityKey]);

  return (
    <aside className={CHANNEL_SETUP_PANEL_CLASS_NAME}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 pe-20">
        <div className="flex min-w-0 max-w-full items-center gap-3">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <h3 className="sr-only">{displayName}</h3>
          {missingSupport && feature.install_supported ? (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={enabledBusy}
              onClick={onInstall}
              className="h-8 rounded-full px-3 text-[12px] font-semibold"
            >
              {enabledBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden />
              )}
              {tx("settings.nanobotFeatures.installSupport", "Install support")}
            </Button>
          ) : null}
        </div>
        {advancedFields.length ? (
          <button
            type="button"
            className="ms-auto inline-flex min-h-8 items-center gap-1.5 rounded px-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-offset-2"
            aria-expanded={advancedOpen}
            aria-controls={advancedPanelId}
            onClick={() => setAdvancedOpen((current) => !current)}
          >
            {tx("settings.channels.advanced", "Advanced")}
            <ChevronDown className={cn(
              "h-3.5 w-3.5 transition-transform motion-reduce:transition-none",
              advancedOpen && "rotate-180",
            )} aria-hidden />
          </button>
        ) : null}
      </div>

      {runtimeError ? (
        <div role="alert" className="mt-4 rounded-control border border-destructive/20 bg-destructive/5 px-3 py-2 text-[12px] leading-5 text-destructive">
          {runtimeError}
        </div>
      ) : null}

      <div className="mt-4 space-y-4">
        {connectFlow}

        {primaryFields.length ? (
          <CredentialForm
            fields={primaryFields}
            values={fieldValues}
            configuredFields={configuredFields}
            visibleSecrets={visibleSecrets}
            onChange={onFieldChange}
            onToggleSecret={(key) => {
              setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }));
            }}
            compact
          />
        ) : null}

        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className={cn(
            "flex items-center justify-end gap-1.5 text-[11px] leading-4 text-muted-foreground",
            !saving && saveState !== "saved" && "sr-only",
          )}
        >
          {saving ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
              {tx("settings.actions.saving", "Saving")}
            </>
          ) : saveState === "saved" ? (
            <>
              <Check className="h-3 w-3" aria-hidden />
              {tx("settings.channels.savedSettings", "Saved settings.")}
            </>
          ) : null}
        </div>

        {saveError ? (
          <div
            role="alert"
            className="rounded-control border border-destructive/20 bg-destructive/5 px-3 py-2 text-[12px] leading-5 text-destructive"
          >
            {saveError}
          </div>
        ) : null}

        {advancedFields.length ? (
          <DisclosureContent id={advancedPanelId} open={advancedOpen} className="text-[12px] leading-5 text-muted-foreground">
            <CredentialForm
              fields={advancedFields}
              values={fieldValues}
              configuredFields={configuredFields}
              visibleSecrets={visibleSecrets}
              onChange={onFieldChange}
              onToggleSecret={(key) => {
                setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }));
              }}
              compact
            />
          </DisclosureContent>
        ) : null}

      </div>
    </aside>
  );
}
