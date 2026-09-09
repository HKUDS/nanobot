import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import { SettingsGroup, SettingsRow, SettingsSectionTitle, RestartRequiredNotice, RestartSettingsFooter } from "@/components/settings/shared/SettingsControls";
import { ProviderPicker } from "@/components/settings/shared/ModelControls";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { RUNTIME_CONFIG_FIELDS, RUNTIME_CONFIG_GROUPS, type RuntimeConfigField, type RuntimeConfigPage } from "@/components/settings/system/runtime-config-fields";
import { updateRuntimeConfigSettings } from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { RuntimeConfigValue, SettingsPayload } from "@/lib/types";
import type { ApplySettingsPayload } from "@/components/settings/contracts";

type Draft = string | boolean;

function displayValue(value: RuntimeConfigValue | undefined): Draft {
  if (typeof value === "boolean") return value;
  if (Array.isArray(value)) return value.join("\n");
  return value == null ? "" : String(value);
}

export function useRuntimeConfigSettings(
  settings: SettingsPayload | null,
  client: NanobotClient,
  applyPayload: ApplySettingsPayload,
) {
  const { t } = useTranslation();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [invalidField, setInvalidField] = useState<string | null>(null);
  const delay = useRef(600);
  const saveLatest = useRef<(group: string) => Promise<void>>(async () => {});
  const pendingGroups = useRef<string[]>([]);
  const queuedSaves = useRef<string[]>([]);
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (invalidField && saving === null) document.getElementById(`runtime-${invalidField}`)?.focus();
  }, [invalidField, saving]);
  const value = (path: string): Draft => drafts[path] ?? displayValue(settings?.runtime_config?.[path]);
  const visible = (field: RuntimeConfigField) => !field.when || value(field.when.path) === field.when.value;
  const dirty = (field: RuntimeConfigField) =>
    drafts[field.path] !== undefined && drafts[field.path] !== displayValue(settings?.runtime_config?.[field.path]);
  const discard = (group: string) => {
    setDrafts((prev) => Object.fromEntries(Object.entries(prev).filter(([path]) =>
      !RUNTIME_CONFIG_FIELDS.some((field) => field.group === group && field.path === path),
    )));
    setErrors((prev) => ({ ...prev, [group]: "" }));
    setInvalidField(null);
  };
  const change = (field: RuntimeConfigField, next: Draft) => {
    delay.current = ["boolean", "toggle", "select", "preset"].includes(field.kind) ? 0 : 600;
    setDrafts((prev) => ({ ...prev, [field.path]: next }));
    setSaved((prev) => ({ ...prev, [field.group]: false }));
    setErrors((prev) => ({ ...prev, [field.group]: "" }));
    setInvalidField(null);
  };
  const save = async (group: string) => {
    if (!settings?.runtime_config) return;
    if (saving) {
      if (!queuedSaves.current.includes(group)) queuedSaves.current.push(group);
      return;
    }
    const changed = RUNTIME_CONFIG_FIELDS.filter((field) => field.group === group && visible(field) && dirty(field));
    if (!changed.length) return;
    const values: Record<string, RuntimeConfigValue> = {};
    for (const field of changed) {
      const raw = value(field.path);
      if (field.kind === "number") {
        const parsed = Number(raw);
        if (String(raw).trim() === "" || !Number.isFinite(parsed)
          || (field.path !== "api.timeout" && !Number.isInteger(parsed))
          || (field.min !== undefined && parsed < field.min)
          || (field.max !== undefined && parsed > field.max)) {
          setErrors((prev) => ({ ...prev, [group]: t("settings.runtimeConfig.numberError") }));
          setInvalidField(field.path);
          return;
        }
        values[field.path] = parsed;
      } else if (field.kind === "list") {
        values[field.path] = String(raw).split("\n").map((line) => line.trim()).filter(Boolean);
      } else if (field.kind === "nullable" || field.kind === "preset") {
        values[field.path] = String(raw).trim() || null;
      } else {
        values[field.path] = raw;
      }
    }
    setSaving(group);
    setErrors((prev) => ({ ...prev, [group]: "" }));
    try {
      const payload = await updateRuntimeConfigSettings(client, values);
      applyPayload(payload, { preserveAgentForm: true, preserveCapabilityForms: true });
      discard(group);
      setSaved((prev) => ({ ...prev, [group]: true }));
    } catch (error) {
      const message = (error as Error).message;
      setErrors((prev) => ({ ...prev, [group]: message }));
      setInvalidField(changed.find((field) => message.startsWith(field.path))?.path ?? null);
    } finally {
      setSaving(null);
    }
  };
  saveLatest.current = save;
  pendingGroups.current = [...new Set(RUNTIME_CONFIG_FIELDS.filter((field) =>
    visible(field) && dirty(field) && !errors[field.group]
      && !RUNTIME_CONFIG_FIELDS.some((other) => other.group === field.group && other.manual && dirty(other)),
  ).map((field) => field.group))];
  useEffect(() => {
    if (saving) return;
    const timer = window.setTimeout(() => {
      const group = queuedSaves.current.shift() ?? pendingGroups.current[0];
      if (group) void saveLatest.current(group);
    }, delay.current);
    return () => window.clearTimeout(timer);
  }, [drafts, saving]);
  return { value, visible, dirty, discard, change, save, saving, errors, invalidField, saved };
}

export type RuntimeConfigController = ReturnType<typeof useRuntimeConfigSettings>;

export function RuntimeConfigSettings({
  page, settings, state, onRestart, isRestarting, remoteBrowserAccess, children,
}: {
  page: RuntimeConfigPage;
  settings: SettingsPayload;
  state: RuntimeConfigController;
  onRestart?: () => void;
  isRestarting: boolean;
  remoteBrowserAccess: boolean;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const tr = (key: string) => t(`settings.runtimeConfig.${key}`);
  if (!settings.runtime_config) return <div className="settings-stack">
    <p className="settings-editor text-[13px] leading-5 text-muted-foreground">{tr("unavailable")}</p>
    {children}
  </div>;
  const groups = RUNTIME_CONFIG_GROUPS.filter((group) => group.page === page);
  const restartPending = settings.restart_required_sections?.includes("runtime")
    || (settings.requires_restart && Object.values(state.saved).some(Boolean));
  return (
    <div className="settings-stack">
      {restartPending ? <RestartRequiredNotice message={t("settings.status.savedRestartApply")}
        onRestart={onRestart} isRestarting={isRestarting} /> : null}
      {groups.map((group) => {
        if (group.enabledBy && state.value(group.enabledBy) === false) return null;
        if (group.id === "chat") return <div key={group.id}>{children}</div>;
        const fields = RUNTIME_CONFIG_FIELDS.filter((field) => field.group === group.id);
        const dirty = fields.filter(state.visible).some(state.dirty);
        const title = tr(`groups.${group.id}.title`);
        const errorId = `runtime-error-${group.id}`;
        const section = (
          <section key={group.id} aria-label={title}>
            <SettingsSectionTitle>{title}</SettingsSectionTitle>
            <form noValidate onSubmit={(event) => { event.preventDefault(); void state.save(group.id); }}>
              <fieldset disabled={state.saving === group.id || isRestarting} className="min-w-0">
                <legend className="sr-only">{title}</legend>
                <button type="submit" hidden />
                <SettingsGroup>
                  {fields.filter(state.visible).map((field) => {
                    const id = `runtime-${field.path}`;
                    const key = field.path.replaceAll(".", "_");
                    const text = tr(`fields.${key}.label`);
                    const help = tr(`fields.${key}.help`);
                    const current = state.value(field.path);
                    const disabled = (field.path === "agents.defaults.timezone" && state.value("agents.defaults.timezone_mode") === "auto")
                      || (field.path === "tools.webui_allow_remote_package_install" && remoteBrowserAccess);
                    const common = {
                      id, disabled, "aria-label": text, "aria-describedby": `${id}-help${state.invalidField === field.path ? ` ${errorId}` : ""}`,
                      "aria-invalid": state.invalidField === field.path || undefined,
                    };
                    const options = field.kind === "preset"
                      ? ["", ...new Set(["default", ...settings.model_presets.map((preset) => preset.name)])]
                      : [...field.options ?? []];
                    // Keep a configured preset visible if it is no longer available.
                    if (field.kind === "preset" && current && !options.includes(String(current))) options.push(String(current));
                    return (
                      <SettingsRow key={field.path} title={text} description={help}>
                        <span id={`${id}-help`} className="sr-only">{help}</span>
                        {field.kind === "boolean" || field.kind === "toggle" ? (
                          <ToggleButton {...common} checked={field.kind === "toggle" ? current === field.options?.[1] : current === true} label={text}
                            onChange={(next) => state.change(field, field.kind === "toggle" ? field.options![next ? 1 : 0] : next)} />
                        ) : (
                          <div className={field.kind === "number" ? "w-24" : "w-full"}>
                            {field.kind === "list" ? (
                              <Textarea {...common} value={String(current)} rows={3} spellCheck={false}
                                onChange={(event) => state.change(field, event.target.value)}
                                className="resize-y rounded-xl text-[13px]" />
                            ) : field.kind === "select" || field.kind === "preset" ? (
                              <ProviderPicker triggerProps={{ ...common, disabled: disabled || state.saving === group.id || isRestarting }}
                                value={String(current)} emptyLabel={tr("none")}
                                providers={options.map((option) => ({ name: option, label:
                                  !option ? tr(field.kind === "preset" ? "activeModel" : "none")
                                    : ["auto", "manual", "standard", "persistent"].includes(option) ? tr(option) : option,
                                }))}
                                onChange={(next) => state.change(field, next)} />
                            ) : (
                              <Input {...common} type={field.kind === "number" ? "number" : "text"}
                                min={field.min} max={field.max} step={field.path === "api.timeout" ? "any" : 1}
                                value={String(current)} className="h-8 rounded-full text-[13px]" autoComplete="off"
                                onChange={(event) => state.change(field, event.target.value)} />
                            )}
                          </div>
                        )}
                      </SettingsRow>
                    );
                  })}
                  <RestartSettingsFooter autoSave={!fields.some((field) => field.manual && state.dirty(field))} dirty={dirty} saving={state.saving === group.id}
                    error={Boolean(state.errors[group.id])}
                    disabled={state.saving === group.id || isRestarting}
                    pendingRestart={false}
                    message={state.saved[group.id] && !dirty ? tr("saved") : undefined}
                    onSave={() => void state.save(group.id)} onReset={() => state.discard(group.id)}
                    onRestart={onRestart} isRestarting={isRestarting} />
                </SettingsGroup>
              </fieldset>
              {state.errors[group.id] ? <p id={errorId} role="alert" className="mt-2 break-words px-1 text-[12px] text-destructive">{state.errors[group.id]}</p> : null}
            </form>
          </section>
        );
        return section;
      })}
    </div>
  );
}
