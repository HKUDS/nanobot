import { ProviderIcon } from "@/components/settings/shared/ProviderIcon";
import { ModelAPIControl } from "@/components/settings/models/ModelAPIControl";
import { useAutomaticModelAPI } from "@/components/settings/models/useAutomaticModelAPI";
import { useModelPresetDrag } from "@/components/settings/models/useModelPresetDrag";
import { ReasoningEffortPicker } from "@/components/settings/models/ReasoningEffortPicker";
import { RemoveActionButton } from "@/components/settings/shared/RemoveActionButton";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { useAutoSave } from "@/components/settings/shared/useAutoSave";
import { Fragment, useEffect, useId, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { DisclosureContent } from "@/components/ui/disclosure";
import {
  GripVertical,
  ListOrdered,
  Loader2,
  Pencil,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ModelIdPicker,
  ProviderPicker,
  ProviderPickerIcon,
  formatContextWindow,
  formatContextWindowInput,
  parseContextWindowTokens,
  formatModelContextWindow,
  normalizeContextWindowTokens,
  settingsProviderConfigured,
} from "@/components/settings/shared/ModelControls";
import {
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
  SettingsStatusMessage,
  StatusPill,
} from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import { HoverHint } from "@/components/ui/hover-hint";
import { ControlChevron } from "@/components/ui/control-chevron";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { ModelAPIConfig, SettingsPayload } from "@/lib/types";

export interface AgentSettingsDraft {
  model: string;
  provider: string;
  modelPreset: string;
  maxTokens: number;
  contextWindowTokens: number;
  temperature: number;
  reasoningEffort: string;
  api: ModelAPIConfig | null;
  timezone: string;
  toolHintMaxLength: number;
}

function modelPresetValue(payload: SettingsPayload): string {
  return (
    payload.model_call_order?.[0] ??
    payload.model_presets.find((preset) => !preset.is_default)?.name ??
    ""
  );
}

function suggestedPresetName(
  model: string,
  presets: SettingsPayload["model_presets"],
): string {
  const modelName = model.trim().split("/").filter(Boolean).at(-1) ?? "";
  const base = (modelName.toLowerCase() === "default" ? "model" : modelName).slice(0, 48);
  if (!base) return "";

  const existing = new Set(
    presets.filter((preset) => !preset.is_default).map((preset) => preset.name.toLowerCase()),
  );
  if (!existing.has(base.toLowerCase())) return base;

  for (let index = 2; ; index += 1) {
    const suffix = ` ${index}`;
    const candidate = `${base.slice(0, 48 - suffix.length)}${suffix}`;
    if (!existing.has(candidate.toLowerCase())) return candidate;
  }
}

export const DEFAULT_AGENT_SETTINGS_DRAFT: AgentSettingsDraft = {
  model: "",
  provider: "",
  modelPreset: "",
  maxTokens: 8192,
  contextWindowTokens: 200_000,
  temperature: 0.1,
  reasoningEffort: "",
  api: null,
  timezone: "UTC",
  toolHintMaxLength: 40,
};

export function agentDraftFromPayload(
  payload: SettingsPayload,
  preferredPresetName?: string,
): AgentSettingsDraft {
  const activePresetName = preferredPresetName ?? modelPresetValue(payload);
  const activePreset =
    payload.model_presets.find(
      (preset) => !preset.is_default && preset.name === activePresetName,
    ) ?? null;
  return {
    model: activePreset?.model ?? payload.agent.model,
    provider: activePreset?.provider ?? payload.agent.provider ?? payload.agent.resolved_provider ?? "",
    modelPreset: activePresetName,
    maxTokens: activePreset?.max_tokens ?? payload.agent.max_tokens,
    contextWindowTokens: normalizeContextWindowTokens(
      activePreset?.context_window_tokens ?? payload.agent.context_window_tokens,
    ),
    temperature: activePreset?.temperature ?? payload.agent.temperature,
    reasoningEffort: activePreset?.reasoning_effort ?? "",
    api: activePreset ? activePreset.api ?? null : payload.agent.api ?? null,
    timezone: payload.agent.timezone,
    toolHintMaxLength: payload.agent.tool_hint_max_length,
  };
}

export function ModelPresetDeleteDialog({
  preset,
  deleting,
  onOpenChange,
  onConfirm,
}: {
  preset: SettingsPayload["model_presets"][number] | null;
  deleting: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  return (
    <Dialog open={preset !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[440px]">
        <DialogHeader className="text-left">
          <DialogTitle>
            {tx("settings.models.deletePresetTitle", "Delete model preset?")}
          </DialogTitle>
          <DialogDescription className="leading-5">
            {tx(
              "settings.models.deletePresetHelp",
              "Delete “{{name}}” and remove it from the fallback list. Provider credentials will be kept.",
              { name: preset?.name ?? "" },
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            disabled={deleting}
            onClick={() => onOpenChange(false)}
          >
            {tx("settings.actions.cancel", "Cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={deleting}
            onClick={onConfirm}
          >
            {deleting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : null}
            {deleting
              ? tx("settings.actions.deleting", "Deleting...")
              : tx("settings.actions.delete", "Delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ModelsSettings({
  token,
  form,
  setForm,
  editingPresetName,
  presetNameError,
  settings,
  dirty,
  creating,
  creatingSaving,
  callOrder,
  saving,
  orderSaving,
  migrationSaving,
  showBrandLogos,
  providerSaving,
  onChangeCallOrder,
  onProviderOAuthLogin,
  onAddProvider,
  onConfigureProvider,
  onManageProviders,
  onSave,
  onMigrate,
  onBeginCreate,
  onCancelCreate,
  onClearPresetNameError,
  onSelectConfiguration,
  onDeleteConfiguration,
}: {
  token: string;
  form: AgentSettingsDraft;
  setForm: Dispatch<SetStateAction<AgentSettingsDraft>>;
  editingPresetName: string;
  presetNameError: string | null;
  settings: SettingsPayload;
  dirty: boolean;
  creating: boolean;
  creatingSaving: boolean;
  callOrder: string[];
  saving: boolean;
  orderSaving: boolean;
  migrationSaving: boolean;
  showBrandLogos: boolean;
  providerSaving: string | null;
  onChangeCallOrder: (order: string[]) => void;
  onProviderOAuthLogin: (provider: string) => void;
  onAddProvider: (trigger: HTMLButtonElement | null, onAdded: (provider: string) => void) => void;
  onConfigureProvider: (provider: string, trigger: HTMLButtonElement | null) => void;
  onManageProviders: (trigger: HTMLButtonElement) => void;
  onSave: () => void;
  onMigrate: () => void;
  onBeginCreate: () => void;
  onCancelCreate: () => void;
  onClearPresetNameError: () => void;
  onSelectConfiguration: (name: string) => void;
  onDeleteConfiguration: (preset: SettingsPayload["model_presets"][number]) => void;
}) {
  const { t } = useTranslation();
  useAutoSave(form, dirty, saving, onSave, !creating && !!form.model.trim());
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const [editorOpen, setEditorOpen] = useState(false);
  const [hideEditorReturnFocus, setHideEditorReturnFocus] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const resolvedAutomaticAPI = useAutomaticModelAPI({
    token,
    provider: form.provider,
    model: form.model,
    reasoningEffort: form.reasoningEffort,
    providers: settings.providers,
    supported: settings.model_api_resolution_supported === true,
    editorOpen: editorOpen && advancedOpen,
  });
  const editorTriggerRef = useRef<HTMLElement | null>(null);
  const presetNameInputRef = useRef<HTMLInputElement>(null);
  const suggestedPresetNameRef = useRef<string | null>(null);
  const presetContextInitializedRef = useRef(false);
  const [editorRowKey, setEditorRowKey] = useState<string | null>(null);
  const advancedId = useId();

  useEffect(() => {
    if (presetNameError) presetNameInputRef.current?.focus();
  }, [presetNameError]);
  useEffect(() => {
    if (!creating) {
      suggestedPresetNameRef.current = null;
      presetContextInitializedRef.current = false;
    }
  }, [creating]);
  const namedPresets = settings.model_presets.filter((preset) => !preset.is_default);
  const namedPresetsByName = new Map(namedPresets.map((preset) => [preset.name, preset]));
  const unorderedPresets = namedPresets.filter((preset) => !callOrder.includes(preset.name));
  const callOrderOccurrences = new Map<string, number>();
  const presetRows = [
    ...callOrder.map((name, orderIndex) => {
      const occurrence = callOrderOccurrences.get(name) ?? 0;
      callOrderOccurrences.set(name, occurrence + 1);
      return {
        key: `ordered:${name}:${occurrence}`,
        name,
        orderIndex,
        preset: namedPresetsByName.get(name),
      };
    }),
    ...unorderedPresets.map((preset) => ({
      key: `disabled:${preset.name}`,
      name: preset.name,
      orderIndex: -1,
      preset,
    })),
  ];
  const selectedPreset = namedPresetsByName.get(editingPresetName) ?? null;
  const activeEditorRowKey =
    editorRowKey ??
    presetRows.find((row) => row.name === selectedPreset?.name)?.key ??
    null;
  useEffect(() => {
    setAdvancedOpen(false);
  }, [editorOpen, selectedPreset?.name]);

  const configuredProviders = settings.providers.filter((provider) => provider.configured);
  const selectedProvider = settings.providers.find((provider) => provider.name === form.provider);
  const selectableProviders = uniqueProviders([
    ...configuredProviders,
    ...(selectedProvider ? [selectedProvider] : []),
  ]);
  const showAutoProvider = selectedPreset?.provider === "auto" || form.provider === "auto";
  const providerOptions = showAutoProvider
    ? [{ name: "auto", label: tx("settings.values.auto", "Auto") }, ...selectableProviders]
    : selectableProviders;
  const providerValue = providerOptions.some((provider) => provider.name === form.provider)
    ? form.provider
    : "";
  const selectProvider = (provider: string) => {
    const clearSuggestedName =
      creating &&
      provider !== form.provider &&
      suggestedPresetNameRef.current !== null &&
      form.modelPreset === suggestedPresetNameRef.current;
    if (clearSuggestedName) suggestedPresetNameRef.current = null;
    setForm((prev) => ({
      ...prev,
      provider,
      model: provider === prev.provider ? prev.model : "",
      api: provider === prev.provider ? prev.api : null,
      modelPreset: clearSuggestedName ? "" : prev.modelPreset,
    }));
  };
  const selectedProviderNeedsSignIn =
    selectedProvider?.auth_type === "oauth" && !selectedProvider.configured;
  const selectedProviderSigningIn = providerSaving === selectedProvider?.name;
  const selectedProviderConfigured = settingsProviderConfigured(
    settings,
    form.provider,
    selectedPreset?.resolved_provider,
  );
  const modelFieldsMissing =
    !form.model.trim() ||
    !form.provider.trim() ||
    !form.modelPreset.trim() ||
    !Number.isSafeInteger(form.maxTokens) ||
    form.maxTokens <= 0 ||
    !Number.isSafeInteger(form.contextWindowTokens) ||
    form.contextWindowTokens <= 0 ||
    form.temperature < 0 ||
    form.temperature > 2;
  const selectedPresetReferenced = Boolean(
    selectedPreset && callOrder[0] === selectedPreset.name,
  );
  const callOrderBusy = orderSaving || saving;
  const presetDrag = useModelPresetDrag({
    keys: presetRows.filter((row) => row.orderIndex >= 0).map((row) => row.key),
    disabled: callOrderBusy,
    onReorder: (keys) => onChangeCallOrder(keys.map((key) => presetRows.find((row) => row.key === key)!.name)),
  });
  const selectPreset = (
    preset: SettingsPayload["model_presets"][number],
    rowKey: string,
  ) => {
    setHideEditorReturnFocus(false);
    editorTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const toggleCurrentPreset =
      !creating && selectedPreset?.name === preset.name && activeEditorRowKey === rowKey;
    onSelectConfiguration(preset.name);
    if (toggleCurrentPreset) {
      setEditorOpen((open) => !open);
      return;
    }
    setForm((prev) => ({
      ...prev,
      modelPreset: preset.name,
      model: preset.model,
      provider: preset.provider,
      maxTokens: preset.max_tokens,
      contextWindowTokens: normalizeContextWindowTokens(preset.context_window_tokens),
      temperature: preset.temperature,
      reasoningEffort: preset.reasoning_effort ?? "",
      api: preset.api ?? null,
    }));
    setEditorRowKey(rowKey);
    setEditorOpen(true);
  };

  const moveCallOrderItem = (index: number, offset: -1 | 1) => {
    if (callOrderBusy) return;
    const nextIndex = index + offset;
    if (nextIndex < 0 || nextIndex >= callOrder.length) return;
    const next = [...callOrder];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    onChangeCallOrder(next);
  };

  const removeCallOrderItem = (index: number) => {
    if (callOrderBusy || callOrder.length <= 1) return;
    onChangeCallOrder(callOrder.filter((_, itemIndex) => itemIndex !== index));
  };

  const renderPresetEditor = () => (
    <div
      id="model-preset-editor"
      data-testid="model-preset-editor"
      className="space-y-1 pb-4 [&_.settings-row>div:first-child]:pl-3"
    >
      <SettingsRow
        title={tx("settings.models.presetName", "Preset name")}
        description={tx(
          "settings.models.presetNameHelp",
          "Used everywhere, including /model commands. Names must be unique.",
        )}
      >
        <div
          className={cn(
            "w-full motion-reduce:animate-none",
            presetNameError && "animate-[preset-name-shake_180ms_ease-in-out]",
          )}
        >
          <Input
            ref={presetNameInputRef}
            autoFocus={creating}
            aria-label={tx("settings.models.presetName", "Preset name")}
            aria-invalid={Boolean(presetNameError)}
            aria-describedby={presetNameError ? "model-preset-name-error" : undefined}
            value={form.modelPreset}
            placeholder={tx("settings.models.presetNamePlaceholder", "e.g. Fast writing")}
            onChange={(event) => {
              suggestedPresetNameRef.current = null;
              onClearPresetNameError();
              setForm((prev) => ({ ...prev, modelPreset: event.target.value }));
            }}
            className={cn(
              "h-9 rounded-full text-[13px]",
              presetNameError &&
                "border-destructive/70 focus-visible:border-destructive focus-visible:ring-destructive/25",
            )}
          />
          {presetNameError ? (
            <p
              id="model-preset-name-error"
              role="alert"
              className="mt-1.5 px-1 text-[12px] leading-4 text-destructive"
            >
              {presetNameError}
            </p>
          ) : null}
        </div>
      </SettingsRow>
      <SettingsRow title={t("settings.rows.provider")}>
        <ProviderPicker
          providers={providerOptions}
          value={providerValue}
          emptyLabel={t("settings.byok.noConfiguredProviders")}
          showProviderLogos={showBrandLogos}
          onAddProvider={(trigger) => onAddProvider(trigger, selectProvider)}
          onConfigureProvider={selectedProvider ? onConfigureProvider : undefined}
          onChange={selectProvider}
        />
      </SettingsRow>
      {selectedProviderNeedsSignIn ? (
        <SettingsRow
          title={tx("settings.oauth.signInRequired", "Sign in required")}
          description={tx(
            "settings.oauth.signInBeforeSaving",
            "Sign in before saving this provider in the preset.",
          )}
        >
          <Button
            size="sm"
            variant="outline"
            onClick={() => selectedProvider && onProviderOAuthLogin(selectedProvider.name)}
            disabled={!selectedProvider?.oauth_login_supported || selectedProviderSigningIn}
            className="rounded-full"
          >
            {selectedProviderSigningIn ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : null}
            {selectedProviderSigningIn
              ? tx("settings.oauth.signingIn", "Signing in...")
              : tx("settings.oauth.signIn", "Sign in")}
          </Button>
        </SettingsRow>
      ) : null}
      <SettingsRow title={t("settings.rows.model")}>
        <ModelIdPicker
          token={token}
          settings={settings}
          provider={form.provider}
          value={form.model}
          showProviderLogos={showBrandLogos}
          onProviderOAuthLogin={onProviderOAuthLogin}
          providerSigningIn={selectedProviderSigningIn}
          onChange={(model, info) => {
            const contextWindow = info?.context_window;
            const initializeContext = creating && !presetContextInitializedRef.current
              && typeof contextWindow === "number" && Number.isSafeInteger(contextWindow) && contextWindow > 0;
            if (creating) presetContextInitializedRef.current = true;
            const canSuggestName =
              creating &&
              (!form.modelPreset.trim() || form.modelPreset === suggestedPresetNameRef.current);
            const suggestion = canSuggestName
              ? suggestedPresetName(model, settings.model_presets)
              : "";
            if (canSuggestName) suggestedPresetNameRef.current = suggestion;
            setForm((prev) => ({
              ...prev,
              model,
              contextWindowTokens: initializeContext ? contextWindow : prev.contextWindowTokens,
              api: model === prev.model ? prev.api : null,
              modelPreset: canSuggestName ? suggestion : prev.modelPreset,
            }));
          }}
        />
      </SettingsRow>
      <SettingsRow title={tx("settings.models.reasoningEffort", "Reasoning effort")}>
        <ReasoningEffortPicker
          token={token}
          provider={selectedProvider ?? settings.providers.find((provider) => provider.name === selectedPreset?.resolved_provider)}
          model={form.model}
          savedValues={form.model === selectedPreset?.model && form.provider === selectedPreset.provider
            ? selectedPreset.reasoning_effort_values : undefined}
          value={form.reasoningEffort}
          onChange={(reasoningEffort) => setForm((prev) => ({ ...prev, reasoningEffort }))}
        />
      </SettingsRow>
      <button
        type="button"
        aria-expanded={advancedOpen}
        aria-controls={advancedId}
        onClick={() => setAdvancedOpen((value) => !value)}
        className="settings-disclosure-row w-full text-left transition-colors settings-hover"
      >
        <span className="min-w-0 pl-3">
          <span className="block text-[14px] font-medium text-foreground">
            {tx("settings.models.advancedOptions", "Advanced options")}
          </span>
          <span className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] tabular-nums text-muted-foreground">
            <span>{tx("settings.models.contextSummary", "Context {{context}}", {
              context: Number.isFinite(form.contextWindowTokens) ? formatModelContextWindow(form.contextWindowTokens) : "—",
            })}</span>{" "}
            <span>{tx("settings.models.outputSummary", "Max {{max}} tokens", {
              max: Number.isFinite(form.maxTokens) ? formatContextWindow(form.maxTokens) : "—",
            })}</span>
          </span>
        </span>
        <span className="settings-control">
          <span className="control-layout justify-end border-transparent">
            <ControlChevron
              className={cn(
                "transition-transform duration-200 motion-reduce:transition-none",
                advancedOpen && "rotate-180",
              )}
            />
          </span>
        </span>
      </button>
      <DisclosureContent id={advancedId} open={advancedOpen}>
        <div className="bg-muted/12">
          <ModelAPIControl
            provider={selectedProvider ?? settings.providers.find(
              (provider) => provider.name === (resolvedAutomaticAPI?.provider ?? selectedPreset?.resolved_provider),
            )}
            automaticAPI={resolvedAutomaticAPI?.api}
            value={form.api}
            onChange={(api) => setForm((prev) => ({ ...prev, api }))}
          />
          <ModelAdvancedFields
            maxTokens={form.maxTokens}
            contextWindowTokens={form.contextWindowTokens}
            temperature={form.temperature}
            onChange={(value) => {
              if (creating && value.contextWindowTokens !== undefined) presetContextInitializedRef.current = true;
              setForm((prev) => ({ ...prev, ...value }));
            }}
          />
        </div>
      </DisclosureContent>
      <div className="settings-list-inset flex min-h-[58px] flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
        {creating ? (
          <Button
            size="sm"
            variant="ghost"
            className="self-start rounded-full text-muted-foreground"
            disabled={creatingSaving}
            onClick={() => {
              setEditorOpen(false);
              onCancelCreate();
            }}
          >
            {tx("settings.actions.cancel", "Cancel")}
          </Button>
        ) : selectedPreset ? (
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <HoverHint
              enabled={selectedPresetReferenced}
              content={tx("settings.models.removeBeforeDelete", "Cannot delete the primary model")}
            >
              <span className="inline-flex">
                <RemoveActionButton
                  disabled={selectedPresetReferenced || saving || orderSaving}
                  aria-describedby={
                    selectedPresetReferenced ? "model-preset-delete-hint" : undefined
                  }
                  onClick={() => onDeleteConfiguration(selectedPreset)}
                >
                  {tx("settings.actions.delete", "Delete")}
                </RemoveActionButton>
              </span>
            </HoverHint>
            {selectedPresetReferenced ? (
              <span
                id="model-preset-delete-hint"
                className="sr-only"
              >
                {tx(
                  "settings.models.removeBeforeDelete",
                  "Cannot delete the primary model",
                )}
              </span>
            ) : null}
          </div>
        ) : null}
        <div className="flex items-center justify-end gap-3">
          <Button
            size="sm"
            variant="outline"
            className="rounded-full"
            disabled={
              (!creating && !dirty) ||
              !selectedProviderConfigured ||
              modelFieldsMissing ||
              saving ||
              orderSaving
            }
            onClick={onSave}
          >
            {saving || creatingSaving
              ? tx("settings.actions.saving", "Saving...")
              : tx("settings.actions.savePreset", "Save")}
          </Button>
        </div>
      </div>
    </div>
  );

  const showMigration = !settings.model_call_order_editable
    && settings.model_configuration_migratable !== false;

  return (
    <div className="settings-stack">
      <section>
        <SettingsSectionTitle>{t("settings.models.presets")}</SettingsSectionTitle>
        {showMigration ? (
          <SettingsGroup>
            <div className="flex flex-col gap-4 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
              <div className="flex min-w-0 items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-control bg-muted text-muted-foreground">
                  <ListOrdered className="h-4 w-4" aria-hidden />
                </span>
                <div className="min-w-0">
                  <p className="text-[14px] font-medium text-foreground">
                    {tx("settings.models.convertTitle", "Convert the current model setup")}
                  </p>
                  <p className="mt-0.5 max-w-[34rem] text-[12px] leading-5 text-muted-foreground">
                    {tx(
                      "settings.models.convertHelp",
                      "Turn the existing primary and fallback models into presets so their order can be managed here.",
                    )}
                  </p>
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="shrink-0 rounded-full"
                disabled={migrationSaving}
                onClick={onMigrate}
              >
                {migrationSaving ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : null}
                {migrationSaving
                  ? tx("settings.models.converting", "Converting...")
                  : tx("settings.models.convertAction", "Convert to presets")}
              </Button>
            </div>
          </SettingsGroup>
        ) : presetRows.length ? (
          <div ref={presetDrag.listRef} {...presetDrag.listProps} className="flex flex-col"
            role="list" aria-label={t("settings.models.callOrder")}>
            {/* Preview with CSS order so moving a card does not interrupt its height transition. */}
            {presetRows.map(({ key, name, preset }, rowIndex) => {
              const orderIndex = presetDrag.previewKeys.indexOf(key);
              const ordered = orderIndex >= 0;
              const primary = orderIndex === 0;
              const provider = preset ? modelPresetProviderKey(preset, settings) : "";
              const presetConfigured = preset
                ? settingsProviderConfigured(settings, preset.provider, preset.resolved_provider)
                : true;
              const isDragging = key === presetDrag.draggedKey;
              const isSelected = editorOpen && !creating && activeEditorRowKey === key
                && selectedPreset?.name === name;
              return (
                <Fragment key={key}>
                  {callOrder.length > 0 && rowIndex === 1 ? (
                    <div role="presentation" className="order-1 mt-6" data-preset-sort-surface="heading">
                      <SettingsSectionTitle>{t("settings.models.otherPresets")}</SettingsSectionTitle>
                    </div>
                  ) : null}
                  <div role="listitem" data-call-order-index={orderIndex} data-preset-sort-key={key}
                    style={{ order: (ordered ? orderIndex : rowIndex) * 2 }} className={cn(!primary && "mb-2")}>
                    <div data-preset-sort-surface={key}
                      className={cn("relative rounded-panel", isDragging && "z-10 shadow-md ring-1 ring-border/50")}>
                      <SettingsGroup>
                        <div
                          tabIndex={ordered ? 0 : -1}
                          onDragStart={(event) => event.preventDefault()}
                          aria-label={ordered ? `${name}. ${t("settings.models.dragToReorder")}` : name}
                          data-testid={`model-call-order-row-${name}`}
                          onPointerDown={(event) => {
                            setHideEditorReturnFocus(false);
                            presetDrag.start(event, key);
                          }}
                          onKeyDown={(event) => {
                            if (event.key !== "Escape") setHideEditorReturnFocus(false);
                            if (event.currentTarget !== event.target) return;
                            if (ordered && event.key === "ArrowUp") {
                              event.preventDefault();
                              moveCallOrderItem(orderIndex, -1);
                            } else if (ordered && event.key === "ArrowDown") {
                              event.preventDefault();
                              moveCallOrderItem(orderIndex, 1);
                            } else if ((event.key === "Enter" || event.key === " ") && preset) {
                              event.preventDefault();
                              selectPreset(preset, key);
                            }
                          }}
                          className={cn(
                            "settings-list-inset group relative select-none outline-none transition-[padding,background-color] [transition-duration:240ms] motion-reduce:transition-none",
                            primary ? "py-5 sm:py-6" : "py-4",
                            ordered && (callOrderBusy ? "cursor-wait" : "cursor-grab active:cursor-grabbing"),
                            !isDragging && "settings-hover",
                            isSelected && "bg-muted/45",
                            !hideEditorReturnFocus && "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                          )}
                        >
                          <div className="flex items-center gap-3">
                            <button
                              type="button"
                              aria-pressed={selectedPreset?.name === name}
                              aria-haspopup="dialog"
                              disabled={!preset}
                              onClick={() => preset && selectPreset(preset, key)}
                              className={cn("flex min-w-0 flex-1 items-center gap-3 rounded-control text-left outline-none",
                                !hideEditorReturnFocus && "focus-visible:ring-2 focus-visible:ring-ring")}
                            >
                              {presetConfigured ? (
                                <ProviderIcon provider={provider} showBrandLogos={showBrandLogos} />
                              ) : (
                                <span className="grid h-8 w-8 shrink-0 place-items-center">
                                  <ProviderPickerIcon provider={provider} showBrandLogos={showBrandLogos} unconfigured />
                                </span>
                              )}
                              <span className="min-w-0 flex-1">
                                <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                                  <span title={name} className={cn("truncate font-medium text-foreground transition-[font-size,line-height,letter-spacing] [transition-duration:240ms] motion-reduce:transition-none",
                                    primary ? "text-[22px] leading-snug tracking-tight sm:text-[26px]" : "text-[14px]")}>
                                    {name}
                                  </span>
                                  {primary ? (
                                    <StatusPill tone="success">{t("settings.models.primary")}</StatusPill>
                                  ) : !ordered ? (
                                    <span className="text-[11px] leading-5 text-muted-foreground">
                                      {t("settings.models.disabled")}
                                    </span>
                                  ) : null}
                                </span>
                                {!primary && preset ? (
                                  <span className="mt-1 block truncate text-[12px] text-muted-foreground" title={preset.model}>
                                    {preset.model}
                                  </span>
                                ) : null}
                              </span>
                              <span className="shrink-0 text-[13px] font-normal leading-5 text-muted-foreground">
                                <span className="sr-only sm:not-sr-only">{t("settings.configure")}</span>
                                <Pencil className="h-4 w-4 sm:hidden" aria-hidden />
                              </span>
                            </button>
                            {ordered ? (
                              <GripVertical
                                className="h-4 w-4 shrink-0 touch-none text-muted-foreground/40 transition-colors group-hover:text-muted-foreground"
                                aria-hidden
                              />
                            ) : (
                              <span className="h-4 w-4 shrink-0" aria-hidden />
                            )}
                            <ToggleButton
                              checked={ordered}
                              label={t(ordered ? "settings.models.removeFromOrder" : "settings.models.addToOrder")}
                              disabled={callOrderBusy || (ordered && callOrder.length <= 1)}
                              onChange={() => {
                                if (ordered) removeCallOrderItem(orderIndex);
                                else if (preset) onChangeCallOrder([...callOrder, preset.name]);
                              }}
                            />
                          </div>
                          {primary && preset ? (
                            <p className="ml-11 mt-1 truncate text-[13px] text-muted-foreground" title={preset.model}>
                              {preset.model}
                            </p>
                          ) : null}
                          {!presetConfigured ? (
                            <p className="ml-11 mt-1 text-[11px] font-medium text-amber-700 dark:text-amber-300">
                              {t("settings.models.providerSetupRequired")}
                            </p>
                          ) : null}
                          {preset ? (
                            <DisclosureContent open={primary} className="pt-6">
                              <dl className="grid grid-cols-3 gap-x-3 gap-y-4 border-t border-border/45 pt-5 sm:gap-x-4">
                                <div>
                                  <dt className="text-[12px] leading-5 text-muted-foreground">{t("settings.rows.contextWindow")}</dt>
                                  <dd className="mt-1 text-[20px] font-medium leading-7 tabular-nums text-foreground">
                                    {formatModelContextWindow(preset.context_window_tokens)}
                                  </dd>
                                </div>
                                <div>
                                  <dt className="text-[12px] leading-5 text-muted-foreground">{t("settings.models.maxTokens")}</dt>
                                  <dd className="mt-1 text-[20px] font-medium leading-7 tabular-nums text-foreground">
                                    {formatContextWindow(preset.max_tokens)}
                                  </dd>
                                </div>
                                <div className="min-w-0">
                                  <dt className="break-words text-[12px] leading-5 text-muted-foreground">{t("settings.models.reasoningEffort")}</dt>
                                  <dd className="mt-1 break-words text-[20px] font-medium leading-7 text-foreground">
                                    {preset.reasoning_effort || t("settings.values.default")}
                                  </dd>
                                </div>
                              </dl>
                            </DisclosureContent>
                          ) : null}
                        </div>
                      </SettingsGroup>
                    </div>
                  </div>
                </Fragment>
              );
            })}
          </div>
        ) : (
          <SettingsGroup>
            <div className="settings-list-inset py-8">
              <p className="text-[14px] font-medium text-foreground">{t("settings.models.noPresets")}</p>
              <p className="mt-2 text-[13px] leading-5 text-muted-foreground">{t("settings.models.newPresetHelp")}</p>
            </div>
          </SettingsGroup>
        )}
        <div className="settings-footer flex flex-wrap justify-end gap-2">
          {orderSaving ? (
            <span role="status" className="order-last w-full text-[12px] text-muted-foreground">
              <SettingsStatusMessage>
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  {t("settings.actions.saving")}
                </span>
              </SettingsStatusMessage>
            </span>
          ) : null}
          {!showMigration ? (
            <Button
              type="button"
              variant="link"
              size="sm"
              className={cn("mr-auto h-11 gap-2 text-[13px] font-normal text-muted-foreground hover:font-semibold hover:text-orange-700 hover:no-underline dark:hover:text-orange-400 sm:h-9",
                hideEditorReturnFocus && "focus-visible:ring-0 focus-visible:ring-offset-0")}
              onKeyDown={(event) => { if (event.key !== "Escape") setHideEditorReturnFocus(false); }}
              disabled={callOrderBusy}
              onClick={(event) => {
                editorTriggerRef.current = event.currentTarget;
                setHideEditorReturnFocus(false);
                setEditorRowKey(null);
                setEditorOpen(true);
                onBeginCreate();
              }}
            >
              {tx("settings.models.newPreset", "New preset")}
            </Button>
          ) : null}
          <Button type="button" variant="link" size="sm"
            className="h-11 shrink-0 text-[13px] font-normal text-muted-foreground hover:font-semibold hover:text-orange-700 hover:no-underline dark:hover:text-orange-400 sm:h-9"
            onClick={(event) => onManageProviders(event.currentTarget)}>
            {t("settings.providers.manageProviders")}
          </Button>
        </div>
      </section>
      <Dialog open={editorOpen && (creating || selectedPreset !== null)} onOpenChange={(open) => {
        setEditorOpen(open);
        if (!open && creating) onCancelCreate();
      }}>
        <DialogContent aria-describedby={undefined}
          onEscapeKeyDown={() => setHideEditorReturnFocus(true)}
          className="relative max-h-[85dvh] w-[min(calc(100vw-2rem),40rem)] max-w-none gap-0 overflow-y-auto p-0"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            editorTriggerRef.current?.focus();
          }}>
          <DialogTitle className="sr-only">
            {creating ? tx("settings.models.newPreset", "New model preset") : selectedPreset?.name}
          </DialogTitle>
          <div className="settings-grid !px-0 pt-8">{renderPresetEditor()}</div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ModelAdvancedFields({
  maxTokens,
  contextWindowTokens,
  temperature,
  onChange,
}: {
  maxTokens: number;
  contextWindowTokens: number;
  temperature: number;
  onChange: (
    value: Partial<
      Pick<
        AgentSettingsDraft,
        "maxTokens" | "contextWindowTokens" | "temperature"
      >
    >,
  ) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <>
      <ModelTokenBudgetRow
        label={tx("settings.models.maxTokens", "Max output tokens")}
        value={maxTokens}
        onChange={(value) => onChange({ maxTokens: value })}
      />
      <SettingsRow title={tx("settings.models.temperature", "Temperature")}>
        <Input
          aria-label={tx("settings.models.temperature", "Temperature")}
          type="number"
          min={0}
          max={2}
          step={0.1}
          value={temperature}
          onChange={(event) => {
            const value = Number(event.target.value);
            if (Number.isFinite(value)) onChange({ temperature: value });
          }}
          className="h-9 text-[13px]"
        />
      </SettingsRow>
      <ModelTokenBudgetRow
        label={tx("settings.rows.contextWindow", "Context window")}
        value={contextWindowTokens}
        onChange={(value) => onChange({ contextWindowTokens: value })}
      />
    </>
  );
}

function ModelTokenBudgetRow({ label, value, onChange }: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<{ text: string; tokens: number } | null>(null);
  const hintId = useId();
  const valid = Number.isSafeInteger(value) && value > 0;
  const hint = valid
    ? t("settings.models.contextWindowHint", { tokens: value.toLocaleString() })
    : t("settings.models.contextWindowError");
  return (
    <SettingsRow title={label} description={valid ? hint : undefined}>
      <div className="w-full">
        <Input
          aria-label={label}
          type="text"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={draft && Object.is(draft.tokens, value) ? draft.text : formatContextWindowInput(value)}
          onChange={(event) => {
            const text = event.target.value;
            const tokens = parseContextWindowTokens(text);
            setDraft({ text, tokens });
            onChange(tokens);
          }}
          aria-invalid={!valid}
          aria-describedby={hintId}
          className="h-9 text-[13px]"
        />
        <p id={hintId} className={valid ? "sr-only" : "mt-1.5 px-3 text-[12px] text-destructive"}>
          {hint}
        </p>
      </div>
    </SettingsRow>
  );
}

function uniqueProviders(
  providers: SettingsPayload["providers"],
): SettingsPayload["providers"] {
  const seen = new Set<string>();
  return providers.filter((provider) => {
    if (seen.has(provider.name)) return false;
    seen.add(provider.name);
    return true;
  });
}

function modelPresetProviderKey(
  preset: SettingsPayload["model_presets"][number],
  settings: SettingsPayload,
  options: { draftProvider?: string } = {},
): string {
  const provider = options.draftProvider ?? preset.provider;
  if (provider === "auto") {
    return (
      preset.resolved_provider ||
      settings.agent.resolved_provider ||
      settings.agent.provider ||
      preset.provider
    );
  }
  return provider;
}
