import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";

import { ModelIdPicker, ProviderPicker, optionRowsWithCurrent } from "@/components/settings/shared/ModelControls";
import {
  NumberInput,
  ReadOnlyRow,
  RestartSettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
  StatusPill,
} from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import type { ImageGenerationSettingsUpdate, SettingsPayload } from "@/lib/types";

const IMAGE_ASPECT_RATIO_OPTIONS = ["1:1", "3:4", "9:16", "4:3", "16:9", "3:2", "2:3", "21:9"];
const IMAGE_SIZE_OPTIONS = ["1K", "2K", "4K", "1024x1024", "1536x1024", "1024x1536"];

export const DEFAULT_IMAGE_GENERATION_FORM: ImageGenerationSettingsUpdate = {
  enabled: false,
  provider: "openrouter",
  model: "openai/gpt-5.4-image-2",
  defaultAspectRatio: "1:1",
  defaultImageSize: "1K",
  maxImagesPerTurn: 4,
};

export function imageGenerationFormFromPayload(payload: SettingsPayload): ImageGenerationSettingsUpdate {
  return {
    enabled: payload.image_generation.enabled,
    provider: payload.image_generation.provider,
    model: payload.image_generation.model,
    defaultAspectRatio: payload.image_generation.default_aspect_ratio,
    defaultImageSize: payload.image_generation.default_image_size,
    maxImagesPerTurn: payload.image_generation.max_images_per_turn,
  };
}

export function ImageGenerationSettings({
  token,
  settings,
  form,
  dirty,
  saving,
  onChangeForm,
  onSave,
  onOpenProviders,
  showBrandLogos,
  onRestart,
  isRestarting,
  requiresRestartPending,
}: {
  token: string;
  settings: SettingsPayload;
  form: ImageGenerationSettingsUpdate;
  dirty: boolean;
  saving: boolean;
  onChangeForm: Dispatch<SetStateAction<ImageGenerationSettingsUpdate>>;
  onSave: () => void;
  onOpenProviders: () => void;
  showBrandLogos: boolean;
  onRestart?: () => void;
  isRestarting?: boolean;
  requiresRestartPending: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const selectedProvider =
    settings.image_generation.providers.find((provider) => provider.name === form.provider) ??
    settings.image_generation.providers[0];
  const providerConfigured = !!selectedProvider?.configured;
  const missingCredential = form.enabled && !providerConfigured;
  const aspectOptions = optionRowsWithCurrent(
    IMAGE_ASPECT_RATIO_OPTIONS.map((value) => ({ name: value, label: value })),
    form.defaultAspectRatio,
  );
  const sizeOptions = optionRowsWithCurrent(
    IMAGE_SIZE_OPTIONS.map((value) => ({ name: value, label: value })),
    form.defaultImageSize,
  );
  const selectProvider = (provider: string) => {
    const nextProvider = settings.image_generation.providers.find((row) => row.name === provider);
    onChangeForm((prev) => ({
      ...prev,
      provider,
      model: nextProvider?.default_model || nextProvider?.models?.[0] || prev.model,
    }));
  };

  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>{tx("settings.sections.imageGeneration", "Image generation")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow title={tx("settings.rows.imageGeneration", "Image generation")}>
            <ToggleButton
              checked={form.enabled}
              onChange={(enabled) => onChangeForm((prev) => ({ ...prev, enabled }))}
              ariaLabel={tx("settings.rows.imageGeneration", "Image generation")}
              label={form.enabled ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.imageProvider", "Image provider")}>
            <ProviderPicker
              providers={settings.image_generation.providers}
              value={form.provider}
              emptyLabel={tx("settings.image.selectProvider", "Select provider")}
              showProviderLogos={showBrandLogos}
              onChange={selectProvider}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.imageProviderStatus", "Provider status")}
            description={tx("settings.help.imageProviderStatus", "Image generation reuses provider credentials from Providers.")}
          >
            <div className="flex flex-wrap items-center justify-end gap-2">
              <StatusPill tone={providerConfigured ? "success" : "neutral"}>
                {providerConfigured
                  ? tx("settings.values.configured", "Configured")
                  : tx("settings.values.notConfigured", "Not configured")}
              </StatusPill>
              {!providerConfigured ? (
                <Button size="sm" variant="outline" onClick={onOpenProviders} className="rounded-full">
                  {tx("settings.image.configureProvider", "Configure provider")}
                </Button>
              ) : null}
            </div>
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.imageProviderBase", "Provider base")}>
            <span className="max-w-[320px] truncate text-right text-[13px] text-muted-foreground">
              {selectedProvider?.api_base || selectedProvider?.default_api_base || selectedProvider?.name || tx("settings.values.notAvailable", "Not available")}
            </span>
          </SettingsRow>
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.imageDefaults", "Defaults")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow title={tx("settings.rows.imageModel", "Image model")}>
            <ModelIdPicker
              token={token}
              settings={settings}
              provider={form.provider}
              models={selectedProvider?.models ?? []}
              value={form.model}
              showProviderLogos={showBrandLogos}
              emptyLabel={tx("settings.image.selectModel", "Select image model")}
              searchPlaceholder={tx(
                "settings.image.searchOrTypeModel",
                "Search or type model ID",
              )}
              emptyMessage={tx(
                "settings.image.typeModelId",
                "Type the model ID supported by this provider.",
              )}
              onChange={(model) => onChangeForm((prev) => ({ ...prev, model }))}
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.defaultAspectRatio", "Default aspect")}>
            <ProviderPicker
              providers={aspectOptions}
              value={form.defaultAspectRatio}
              emptyLabel={tx("settings.image.selectAspect", "Select aspect")}
              onChange={(defaultAspectRatio) =>
                onChangeForm((prev) => ({ ...prev, defaultAspectRatio }))
              }
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.defaultImageSize", "Default size")}>
            <ProviderPicker
              providers={sizeOptions}
              value={form.defaultImageSize}
              emptyLabel={tx("settings.image.selectSize", "Select size")}
              onChange={(defaultImageSize) =>
                onChangeForm((prev) => ({ ...prev, defaultImageSize }))
              }
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.maxImagesPerTurn", "Max images per turn")}>
            <NumberInput
              value={form.maxImagesPerTurn}
              min={1}
              max={8}
              onChange={(maxImagesPerTurn) =>
                onChangeForm((prev) => ({ ...prev, maxImagesPerTurn }))
              }
            />
          </SettingsRow>
          <ReadOnlyRow title={tx("settings.rows.imageSaveDir", "Save directory")} value={settings.image_generation.save_dir} />
          <RestartSettingsFooter
            dirty={dirty}
            saving={saving}
            pendingRestart={requiresRestartPending}
            disabled={missingCredential}
            message={
              missingCredential
                ? tx("settings.image.missingCredential", "Configure this provider before enabling image generation.")
                : undefined
            }
            dirtyMessage={tx("settings.status.restartAfterSaving", "Save changes, then restart when ready.")}
            pendingMessage={tx("settings.status.savedRestartApply", "Saved. Restart when ready.")}
            onSave={onSave}
            onRestart={onRestart}
            isRestarting={isRestarting}
          />
        </SettingsGroup>
      </section>
    </div>
  );
}
