import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import {
  ChevronDown,
  ChevronRight,
  GripVertical,
  ListOrdered,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ModelIdPicker,
  ProviderPicker,
  ProviderPickerIcon,
  formatContextWindow,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { cn } from "@/lib/utils";
import type { SettingsPayload } from "@/lib/types";

export interface AgentSettingsDraft {
  model: string;
  provider: string;
  modelPreset: string;
  presetLabel: string;
  maxTokens: number;
  contextWindowTokens: number;
  temperature: number;
  reasoningEffort: string;
  timezone: string;
  toolHintMaxLength: number;
}

const CONTEXT_WINDOW_TOKEN_OPTIONS = [65_536, 200_000, 262_144, 500_000, 1_048_576] as const;

function modelPresetValue(payload: SettingsPayload): string {
  return (
    payload.model_call_order?.[0] ??
    payload.model_presets.find((preset) => !preset.is_default)?.name ??
    ""
  );
}

export const DEFAULT_AGENT_SETTINGS_DRAFT: AgentSettingsDraft = {
  model: "",
  provider: "",
  modelPreset: "",
  presetLabel: "",
  maxTokens: 8192,
  contextWindowTokens: 200_000,
  temperature: 0.1,
  reasoningEffort: "",
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
    presetLabel: activePreset?.label ?? activePresetName,
    maxTokens: activePreset?.max_tokens ?? payload.agent.max_tokens,
    contextWindowTokens: normalizeContextWindowTokens(
      activePreset?.context_window_tokens ?? payload.agent.context_window_tokens,
    ),
    temperature: activePreset?.temperature ?? payload.agent.temperature,
    reasoningEffort: activePreset?.reasoning_effort ?? "",
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
      <DialogContent className="max-w-[440px] rounded-[24px]">
        <DialogHeader className="text-left">
          <DialogTitle>
            {tx("settings.models.deletePresetTitle", "Delete model preset?")}
          </DialogTitle>
          <DialogDescription className="leading-5">
            {tx(
              "settings.models.deletePresetHelp",
              "This removes the preset “{{name}}”. Provider credentials are not affected.",
              { name: preset?.label ?? "" },
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:space-x-0">
          <Button
            type="button"
            variant="ghost"
            className="rounded-full"
            disabled={deleting}
            onClick={() => onOpenChange(false)}
          >
            {tx("settings.actions.cancel", "Cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            className="rounded-full"
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
  onSave,
  onMigrate,
  onBeginCreate,
  onCancelCreate,
  onSelectConfiguration,
  onDeleteConfiguration,
}: {
  token: string;
  form: AgentSettingsDraft;
  setForm: Dispatch<SetStateAction<AgentSettingsDraft>>;
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
  onSave: () => void;
  onMigrate: () => void;
  onBeginCreate: () => void;
  onCancelCreate: () => void;
  onSelectConfiguration: () => void;
  onDeleteConfiguration: (preset: SettingsPayload["model_presets"][number]) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorRowKey, setEditorRowKey] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [draggedCallOrderIndex, setDraggedCallOrderIndex] = useState<number | null>(null);
  const [dragOverCallOrderIndex, setDragOverCallOrderIndex] = useState<number | null>(null);
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
  const selectedPreset = namedPresetsByName.get(form.modelPreset) ?? null;
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
    !form.presetLabel.trim() ||
    form.maxTokens <= 0 ||
    form.temperature < 0 ||
    form.temperature > 2;
  const selectedPresetReferenced = Boolean(
    selectedPreset && callOrder.includes(selectedPreset.name),
  );
  const callOrderBusy = orderSaving || saving;
  const selectPreset = (
    preset: SettingsPayload["model_presets"][number],
    rowKey: string,
  ) => {
    const toggleCurrentPreset =
      !creating && selectedPreset?.name === preset.name && activeEditorRowKey === rowKey;
    onSelectConfiguration();
    if (toggleCurrentPreset) {
      setEditorOpen((open) => !open);
      return;
    }
    setForm((prev) => ({
      ...prev,
      modelPreset: preset.name,
      model: preset.model,
      provider: preset.provider,
      presetLabel: preset.label,
      maxTokens: preset.max_tokens,
      contextWindowTokens: normalizeContextWindowTokens(preset.context_window_tokens),
      temperature: preset.temperature,
      reasoningEffort: preset.reasoning_effort ?? "",
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

  const dropCallOrderItem = (targetIndex: number) => {
    if (
      callOrderBusy ||
      draggedCallOrderIndex === null ||
      draggedCallOrderIndex === targetIndex
    ) {
      setDraggedCallOrderIndex(null);
      setDragOverCallOrderIndex(null);
      return;
    }
    const next = [...callOrder];
    const moved = next.splice(draggedCallOrderIndex, 1)[0];
    if (!moved) {
      setDraggedCallOrderIndex(null);
      setDragOverCallOrderIndex(null);
      return;
    }
    next.splice(targetIndex, 0, moved);
    setDraggedCallOrderIndex(null);
    setDragOverCallOrderIndex(null);
    onChangeCallOrder(next);
  };

  const renderPresetEditor = () => (
    <div
      id="model-preset-editor"
      data-testid="model-preset-editor"
      className="mx-3 mb-3 divide-y divide-border/45 overflow-hidden rounded-[18px] border border-border/45 bg-background/80 shadow-sm motion-reduce:animate-none animate-in fade-in-0 slide-in-from-top-1 duration-200 sm:mx-5 lg:mx-auto lg:w-[calc(100%-2.5rem)] lg:max-w-6xl"
    >
      {creating ? (
        <div className="flex min-h-[52px] items-center px-4 py-3 sm:px-5">
          <span className="text-[13px] font-semibold text-foreground/85">
            {tx("settings.models.newPreset", "New model preset")}
          </span>
        </div>
      ) : null}
      <SettingsRow title={tx("settings.models.presetName", "Preset name")}>
        <Input
          autoFocus={creating}
          value={form.presetLabel}
          placeholder={tx("settings.models.presetNamePlaceholder", "Fast writing")}
          onChange={(event) =>
            setForm((prev) => ({ ...prev, presetLabel: event.target.value }))
          }
          className="h-8 w-[min(280px,70vw)] rounded-full text-[13px]"
        />
      </SettingsRow>
      <SettingsRow title={t("settings.rows.provider")}>
        <ProviderPicker
          providers={providerOptions}
          value={providerValue}
          emptyLabel={t("settings.byok.noConfiguredProviders")}
          showProviderLogos={showBrandLogos}
          onChange={(provider) =>
            setForm((prev) => ({
              ...prev,
              provider,
              model: provider === prev.provider ? prev.model : "",
            }))
          }
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
          onChange={(model) => setForm((prev) => ({ ...prev, model }))}
        />
      </SettingsRow>
      <button
        type="button"
        aria-expanded={advancedOpen}
        onClick={() => setAdvancedOpen((value) => !value)}
        className="flex min-h-[62px] w-full items-center justify-between gap-4 px-4 py-3.5 text-left transition-colors hover:bg-muted/30 sm:px-5"
      >
        <span>
          <span className="block text-[14px] font-medium text-foreground">
            {tx("settings.models.advancedOptions", "Advanced options")}
          </span>
          <span className="mt-0.5 block text-[12px] text-muted-foreground">
            {tx(
              "settings.models.advancedSummary",
              "Context {{context}} · Max {{max}} tokens",
              {
                context: formatModelContextWindow(form.contextWindowTokens),
                max: formatContextWindow(form.maxTokens),
              },
            )}
          </span>
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            advancedOpen && "rotate-180",
          )}
          aria-hidden
        />
      </button>
      {advancedOpen ? (
        <div className="bg-muted/12 px-4 py-4 sm:px-5">
          <ModelAdvancedFields
            maxTokens={form.maxTokens}
            contextWindowTokens={form.contextWindowTokens}
            temperature={form.temperature}
            reasoningEffort={form.reasoningEffort}
            onChange={(value) => setForm((prev) => ({ ...prev, ...value }))}
          />
        </div>
      ) : null}
      <div className="flex min-h-[58px] flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
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
            <Button
              size="sm"
              variant="ghost"
              className="rounded-full text-muted-foreground hover:text-destructive"
              disabled={selectedPresetReferenced || saving || orderSaving}
              aria-describedby={
                selectedPresetReferenced ? "model-preset-delete-hint" : undefined
              }
              onClick={() => onDeleteConfiguration(selectedPreset)}
            >
              <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
              {tx("settings.actions.delete", "Delete")}
            </Button>
            {selectedPresetReferenced ? (
              <span
                id="model-preset-delete-hint"
                className="text-[11px] leading-4 text-muted-foreground"
              >
                {tx(
                  "settings.models.removeBeforeDelete",
                  "Remove this preset from the call order before deleting it.",
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
              : tx("settings.actions.savePreset", "Save preset")}
          </Button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>
          {tx("settings.models.presets", "Model presets")}
        </SettingsSectionTitle>
        <SettingsGroup>
          {!settings.model_call_order_editable ? (
            <div className="flex flex-col gap-4 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
              <div className="flex min-w-0 items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[12px] bg-muted text-muted-foreground">
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
          ) : (
            <>
              <div role="list" className="divide-y divide-border/45">
                {presetRows.map(({ key, name, orderIndex, preset }) => {
                  const ordered = orderIndex >= 0;
                  const provider = preset
                    ? modelPresetProviderKey(preset, settings)
                    : settings.agent.resolved_provider ?? settings.agent.provider;
                  const presetConfigured = preset
                    ? settingsProviderConfigured(
                        settings,
                        preset.provider,
                        preset.resolved_provider,
                      )
                    : true;
                  const isDropTarget =
                    ordered &&
                    dragOverCallOrderIndex === orderIndex &&
                    draggedCallOrderIndex !== orderIndex;
                  const dropAfterTarget =
                    isDropTarget &&
                    draggedCallOrderIndex !== null &&
                    draggedCallOrderIndex < orderIndex;
                  const isSelected =
                    editorOpen &&
                    !creating &&
                    activeEditorRowKey === key &&
                    selectedPreset?.name === name;
                  const presetRow = (
                    <div
                      tabIndex={ordered ? 0 : -1}
                      draggable={ordered && !callOrderBusy}
                      aria-label={
                        ordered
                          ? `${preset?.label ?? name}. ${tx(
                              "settings.models.dragToReorder",
                              "Drag to reorder",
                            )}`
                          : preset?.label ?? name
                      }
                      data-testid={`model-call-order-row-${name}`}
                      onDragStart={(event) => {
                        if (!ordered || callOrderBusy) {
                          event.preventDefault();
                          return;
                        }
                        event.dataTransfer.effectAllowed = "move";
                        event.dataTransfer.setData("text/plain", name);
                        setDraggedCallOrderIndex(orderIndex);
                        setDragOverCallOrderIndex(orderIndex);
                      }}
                      onDragEnd={() => {
                        setDraggedCallOrderIndex(null);
                        setDragOverCallOrderIndex(null);
                      }}
                      onDragEnter={(event) => {
                        if (ordered && draggedCallOrderIndex !== null) {
                          event.preventDefault();
                          setDragOverCallOrderIndex(orderIndex);
                        }
                      }}
                      onDragOver={(event) => {
                        if (!ordered || draggedCallOrderIndex === null) return;
                        event.preventDefault();
                        event.dataTransfer.dropEffect = "move";
                      }}
                      onDrop={(event) => {
                        if (!ordered) return;
                        event.preventDefault();
                        dropCallOrderItem(orderIndex);
                      }}
                      onKeyDown={(event) => {
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
                        "group relative flex min-h-[76px] select-none items-center gap-3 px-4 py-3 outline-none transition-[background-color,opacity] duration-150 sm:px-5",
                        ordered &&
                          (callOrderBusy
                            ? "cursor-wait"
                            : "cursor-grab active:cursor-grabbing"),
                        "hover:bg-muted/25",
                        isDropTarget &&
                          !dropAfterTarget &&
                          "before:absolute before:inset-x-4 before:top-0 before:z-10 before:h-0.5 before:rounded-full before:bg-foreground sm:before:inset-x-5",
                        isDropTarget &&
                          dropAfterTarget &&
                          "after:absolute after:inset-x-4 after:bottom-0 after:z-10 after:h-0.5 after:rounded-full after:bg-foreground sm:after:inset-x-5",
                        ordered && draggedCallOrderIndex === orderIndex && "opacity-35",
                        isSelected && "bg-muted/45 hover:bg-muted/45",
                        "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                      )}
                    >
                      {ordered ? (
                        <GripVertical
                          className="pointer-events-none h-4 w-4 shrink-0 text-muted-foreground/40 transition-colors group-hover:text-muted-foreground"
                          aria-hidden
                        />
                      ) : (
                        <span className="h-4 w-4 shrink-0" aria-hidden />
                      )}
                      <button
                        type="button"
                        aria-pressed={selectedPreset?.name === name}
                        aria-expanded={isSelected}
                        aria-controls={isSelected ? "model-preset-editor" : undefined}
                        disabled={!preset}
                        onClick={() => preset && selectPreset(preset, key)}
                        className="flex min-w-0 flex-1 items-center gap-3 rounded-[12px] text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {ordered ? (
                          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-muted font-mono text-[11px] font-semibold tabular-nums text-muted-foreground">
                            {orderIndex + 1}
                          </span>
                        ) : (
                          <span className="h-7 w-7 shrink-0" aria-hidden />
                        )}
                        <ProviderPickerIcon
                          provider={provider}
                          showBrandLogos={showBrandLogos}
                          unconfigured={!presetConfigured}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="flex min-w-0 flex-wrap items-center gap-2">
                            <span className="truncate text-[14px] font-medium text-foreground">
                              {preset?.label ?? name}
                            </span>
                            {orderIndex === 0 ? (
                              <StatusPill tone="success">
                                {tx("settings.models.primary", "Primary")}
                              </StatusPill>
                            ) : !ordered ? (
                              <StatusPill tone="neutral">
                                {tx("settings.models.disabled", "Disabled")}
                              </StatusPill>
                            ) : null}
                            {!presetConfigured ? (
                              <span className="text-[11px] font-medium text-amber-700 dark:text-amber-300">
                                {tx(
                                  "settings.models.providerSetupRequired",
                                  "Provider setup required",
                                )}
                              </span>
                            ) : null}
                          </span>
                          <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">
                            {preset?.model ?? name}
                          </span>
                        </span>
                        <ChevronRight
                          className={cn(
                            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                            isSelected && "rotate-90",
                          )}
                          aria-hidden
                        />
                      </button>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={ordered}
                        aria-label={
                          ordered
                            ? tx("settings.models.removeFromOrder", "Disable preset")
                            : tx("settings.models.addToOrder", "Enable preset")
                        }
                        disabled={callOrderBusy || (ordered && callOrder.length <= 1)}
                        onClick={() => {
                          if (ordered) {
                            removeCallOrderItem(orderIndex);
                          } else if (preset) {
                            onChangeCallOrder([...callOrder, preset.name]);
                          }
                        }}
                        className={cn(
                          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40",
                          ordered ? "bg-foreground" : "bg-muted-foreground/25",
                        )}
                      >
                        <span
                          className={cn(
                            "h-4 w-4 rounded-full bg-background shadow-sm transition-transform",
                            ordered ? "translate-x-[18px]" : "translate-x-0.5",
                          )}
                          aria-hidden
                        />
                      </button>
                    </div>
                  );
                  return (
                    <div key={key} role="listitem">
                      {presetRow}
                      {isSelected ? renderPresetEditor() : null}
                    </div>
                  );
                })}
              </div>
              <div className="flex min-h-[58px] flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                {!creating ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="rounded-full"
                    disabled={callOrderBusy}
                    onClick={() => {
                      setEditorRowKey(null);
                      setEditorOpen(true);
                      onBeginCreate();
                    }}
                  >
                    <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                    {tx("settings.models.newPreset", "New model preset")}
                  </Button>
                ) : (
                  <span />
                )}
                {orderSaving ? (
                  <SettingsStatusMessage>
                    <span className="inline-flex items-center gap-1.5">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                      {tx("settings.actions.saving", "Saving...")}
                    </span>
                  </SettingsStatusMessage>
                ) : null}
              </div>
              {creating && editorOpen ? renderPresetEditor() : null}
            </>
          )}
        </SettingsGroup>
      </section>
    </div>
  );
}

function ModelAdvancedFields({
  maxTokens,
  contextWindowTokens,
  temperature,
  reasoningEffort,
  onChange,
}: {
  maxTokens: number;
  contextWindowTokens: number;
  temperature: number;
  reasoningEffort: string;
  onChange: (
    value: Partial<
      Pick<
        AgentSettingsDraft,
        "maxTokens" | "contextWindowTokens" | "temperature" | "reasoningEffort"
      >
    >,
  ) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const contextWindowOptions = Array.from(
    new Set([...CONTEXT_WINDOW_TOKEN_OPTIONS, contextWindowTokens]),
  ).sort((left, right) => left - right);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
            {tx("settings.models.maxTokens", "Max output tokens")}
          </span>
          <Input
            type="number"
            min={1}
            step={1}
            value={maxTokens}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isFinite(value)) onChange({ maxTokens: value });
            }}
            className="h-9 rounded-[12px] text-[13px]"
          />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
            {tx("settings.models.temperature", "Temperature")}
          </span>
          <Input
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isFinite(value)) onChange({ temperature: value });
            }}
            className="h-9 rounded-[12px] text-[13px]"
          />
        </label>
      </div>
      <div>
        <span className="mb-2 block text-[12px] font-medium text-muted-foreground">
          {tx("settings.rows.contextWindow", "Context window")}
        </span>
        <SegmentedControl
          value={String(contextWindowTokens)}
          options={contextWindowOptions.map((tokens) => ({
            value: String(tokens),
            label: formatModelContextWindow(tokens),
          }))}
          onChange={(value) =>
            onChange({ contextWindowTokens: normalizeContextWindowTokens(Number(value)) })
          }
        />
      </div>
      <label className="block">
        <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
          {tx("settings.models.reasoningEffort", "Reasoning effort")}
        </span>
        <Input
          value={reasoningEffort}
          onChange={(event) => onChange({ reasoningEffort: event.target.value })}
          placeholder={tx("settings.values.default", "Default")}
          autoCapitalize="none"
          spellCheck={false}
          className="h-9 rounded-[12px] text-[13px]"
        />
      </label>
    </div>
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
