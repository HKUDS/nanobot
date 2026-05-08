import { useCallback, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import {
  Bot,
  Brain,
  ChevronLeft,
  ChevronDown,
  Check,
  Cloud,
  Cpu,
  Database,
  Eye,
  EyeOff,
  Pencil,
  Gem,
  Grid3X3,
  Hexagon,
  Loader2,
  LogOut,
  KeyRound,
  Layers,
  Moon,
  Orbit,
  RotateCcw,
  Settings,
  Sparkles,
  Triangle,
  Waves,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { fetchSettings, updateProviderSettings, updateSettings } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";
import type { SettingsPayload } from "@/lib/types";

type SettingsSectionKey = "general" | "byok";

interface SettingsViewProps {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onBackToChat: () => void;
  onModelNameChange: (modelName: string | null) => void;
  onLogout?: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}

export function SettingsView({
  theme,
  onToggleTheme,
  onBackToChat,
  onModelNameChange,
  onLogout,
  onRestart,
  isRestarting = false,
}: SettingsViewProps) {
  const { t } = useTranslation();
  const { token } = useClient();
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [providerSaving, setProviderSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SettingsSectionKey>("general");
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const [providerForms, setProviderForms] = useState<Record<string, { apiKey: string; apiBase: string }>>({});
  const [visibleProviderKeys, setVisibleProviderKeys] = useState<Record<string, boolean>>({});
  const [editingProviderKeys, setEditingProviderKeys] = useState<Record<string, boolean>>({});
  const [form, setForm] = useState({
    model: "",
    provider: "",
  });

  const applyPayload = useCallback((payload: SettingsPayload) => {
    setSettings(payload);
    setForm({
      model: payload.agent.model,
      provider: payload.agent.provider,
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSettings(token)
      .then((payload) => {
        if (!cancelled) {
          applyPayload(payload);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applyPayload, token]);

  useEffect(() => {
    if (!settings) return;
    setProviderForms((prev) => {
      const next = { ...prev };
      for (const provider of settings.providers) {
        next[provider.name] = {
          apiKey: next[provider.name]?.apiKey ?? "",
          apiBase: next[provider.name]?.apiBase ?? provider.api_base ?? provider.default_api_base ?? "",
        };
      }
      return next;
    });
  }, [settings]);

  const dirty = useMemo(() => {
    if (!settings) return false;
    return (
      form.model !== settings.agent.model ||
      form.provider !== settings.agent.provider
    );
  }, [form, settings]);

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      const payload = await updateSettings(token, {
        model: form.model,
        ...(form.provider ? { provider: form.provider } : {}),
      });
      applyPayload(payload);
      onModelNameChange(payload.agent.model || null);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saveProvider = async (providerName: string) => {
    if (providerSaving) return;
    const provider = settings?.providers.find((item) => item.name === providerName);
    if (!provider) return;
    const providerForm = providerForms[providerName] ?? { apiKey: "", apiBase: "" };
    const apiKey = providerForm.apiKey.trim();
    if (!provider.configured && !apiKey) {
      setError(t("settings.byok.apiKeyRequired"));
      return;
    }
    setProviderSaving(providerName);
    try {
      const payload = await updateProviderSettings(token, {
        provider: providerName,
        apiKey: apiKey || undefined,
        apiBase: providerForm.apiBase.trim(),
      });
      applyPayload(payload);
      setProviderForms((prev) => ({
        ...prev,
        [providerName]: {
          apiKey: "",
          apiBase: providerForm.apiBase.trim(),
        },
      }));
      setVisibleProviderKeys((prev) => ({ ...prev, [providerName]: false }));
      setEditingProviderKeys((prev) => ({ ...prev, [providerName]: false }));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProviderSaving(null);
    }
  };

  const toggleProviderKeyVisibility = (providerName: string) => {
    const isVisible = visibleProviderKeys[providerName];
    setVisibleProviderKeys((prev) => ({ ...prev, [providerName]: !isVisible }));
  };

  const toggleProviderKeyEditing = (providerName: string) => {
    setEditingProviderKeys((prev) => {
      const nextEditing = !prev[providerName];
      if (!nextEditing) {
        setProviderForms((forms) => ({
          ...forms,
          [providerName]: {
            apiKey: "",
            apiBase: forms[providerName]?.apiBase ?? "",
          },
        }));
        setVisibleProviderKeys((visible) => ({ ...visible, [providerName]: false }));
      }
      return { ...prev, [providerName]: nextEditing };
    });
  };

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden bg-[radial-gradient(circle_at_50%_0%,hsl(var(--muted))_0%,hsl(var(--background))_42%)]">
      <SettingsSidebar
        activeSection={activeSection}
        onSelectSection={setActiveSection}
        onBackToChat={onBackToChat}
        onLogout={onLogout}
      />

      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[840px] px-6 py-10 sm:px-10 lg:py-14">
          <div className="mb-8">
            <p className="mb-2 text-[13px] font-medium text-muted-foreground">
              {t("settings.sidebar.title")}
            </p>
            <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.035em] text-foreground sm:text-[34px]">
              {t(`settings.nav.${activeSection}`)}
            </h1>
          </div>

          {loading ? (
            <div className="flex h-48 items-center justify-center rounded-[24px] border border-border/50 bg-card/75 text-sm text-muted-foreground shadow-[0_20px_70px_rgba(15,23,42,0.07)]">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {t("settings.status.loading")}
            </div>
          ) : error && !settings ? (
            <SettingsGroup>
              <SettingsRow title={t("settings.status.loadError")}>
                <span className="max-w-[520px] text-sm text-muted-foreground">{error}</span>
              </SettingsRow>
            </SettingsGroup>
          ) : settings ? (
            <div className="space-y-5">
              {error ? (
                <div className="rounded-[18px] border border-destructive/20 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">
                  {error}
                </div>
              ) : null}
              {activeSection === "general" ? (
                <GeneralSettings
                  theme={theme}
                  onToggleTheme={onToggleTheme}
                  form={form}
                  setForm={setForm}
                  settings={settings}
                  dirty={dirty}
                  saving={saving}
                  onSave={save}
                  onRestart={onRestart}
                isRestarting={isRestarting}
                  onOpenByok={() => setActiveSection("byok")}
                />
              ) : (
                <ByokSettings
                  settings={settings}
                  expandedProvider={expandedProvider}
                  providerForms={providerForms}
                  visibleProviderKeys={visibleProviderKeys}
                  editingProviderKeys={editingProviderKeys}
                  providerSaving={providerSaving}
                  onToggleProvider={(provider) =>
                    setExpandedProvider((current) => (current === provider ? null : provider))
                  }
                  onToggleProviderKey={toggleProviderKeyVisibility}
                  onToggleProviderKeyEditing={toggleProviderKeyEditing}
                  onChangeProviderForm={(provider, value) =>
                    setProviderForms((prev) => ({
                      ...prev,
                      [provider]: {
                        apiKey: prev[provider]?.apiKey ?? "",
                        apiBase: prev[provider]?.apiBase ?? "",
                        ...value,
                      },
                    }))
                  }
                  onSaveProvider={saveProvider}
                />
              )}
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}

const SETTINGS_NAV_ITEMS = [
  { key: "general", icon: Settings },
  { key: "byok", icon: KeyRound },
] as const;

function SettingsSidebar({
  activeSection,
  onSelectSection,
  onBackToChat,
  onLogout,
}: {
  activeSection: SettingsSectionKey;
  onSelectSection: (section: SettingsSectionKey) => void;
  onBackToChat: () => void;
  onLogout?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <aside className="flex w-[17rem] shrink-0 flex-col border-r border-border/55 bg-card/62 px-3 py-4 shadow-[inset_-1px_0_0_rgba(255,255,255,0.55)] backdrop-blur-xl dark:bg-card/45 dark:shadow-none">
      <button
        type="button"
        onClick={onBackToChat}
        className="mb-3 inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
        {t("settings.backToChat")}
      </button>
      <div className="mb-5 px-2">
        <h2 className="text-[21px] font-semibold tracking-[-0.035em] text-foreground">
          {t("settings.sidebar.title")}
        </h2>
      </div>

      <nav aria-label={t("settings.sidebar.ariaLabel")} className="space-y-1">
        {SETTINGS_NAV_ITEMS.map(({ key, icon: Icon }) => {
          const active = key === activeSection;
          return (
            <button
              key={key}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onSelectSection(key)}
              className={cn(
                "flex h-9 w-full items-center gap-2 rounded-[10px] px-2.5 text-left text-[13px] font-medium transition-colors",
                active
                  ? "bg-muted/90 text-foreground shadow-[inset_0_0_0_1px_rgba(0,0,0,0.025)]"
                  : "text-muted-foreground/78 hover:bg-muted/45 hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
              <span className="truncate">{t(`settings.nav.${key}`)}</span>
            </button>
          );
        })}
      </nav>

      <div className="mt-auto pt-4">
        {onLogout ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onLogout}
            className="h-9 w-full justify-start gap-2 rounded-[10px] px-2.5 text-[13px] font-medium text-muted-foreground hover:bg-destructive/8 hover:text-destructive"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            {t("app.account.logout")}
          </Button>
        ) : null}
      </div>
    </aside>
  );
}

function GeneralSettings({
  theme,
  onToggleTheme,
  form,
  setForm,
  settings,
  dirty,
  saving,
  onSave,
  onRestart,
  isRestarting,
  onOpenByok,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  form: {
    model: string;
    provider: string;
  };
  setForm: Dispatch<SetStateAction<{
    model: string;
    provider: string;
  }>>;
  settings: SettingsPayload;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
  onOpenByok: () => void;
}) {
  const { t } = useTranslation();
  const configuredProviders = settings.providers.filter((provider) => provider.configured);
  const providerValue = configuredProviders.some((provider) => provider.name === form.provider)
    ? form.provider
    : "";
  return (
    <div className="space-y-8">
      <section>
        <SettingsSectionTitle>{t("settings.sections.interface")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={t("settings.rows.theme")}
            description={t("settings.help.theme")}
          >
            <button
              type="button"
              onClick={onToggleTheme}
              className="inline-flex h-8 items-center rounded-full bg-muted p-0.5 text-[12px] font-medium text-muted-foreground"
            >
              <span
                className={cn(
                  "rounded-full px-3 py-1 transition-colors",
                  theme === "light" && "bg-background text-foreground shadow-sm",
                )}
              >
                {t("settings.values.light")}
              </span>
              <span
                className={cn(
                  "rounded-full px-3 py-1 transition-colors",
                  theme === "dark" && "bg-background text-foreground shadow-sm",
                )}
              >
                {t("settings.values.dark")}
              </span>
            </button>
          </SettingsRow>

          <SettingsRow
            title={t("settings.rows.language")}
            description={t("settings.help.language")}
          >
            <LanguageSwitcher />
          </SettingsRow>
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{t("settings.sections.ai")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={t("settings.rows.provider")}
            description={t("settings.help.provider")}
          >
            <ProviderPicker
              providers={configuredProviders}
              value={providerValue}
              emptyLabel={t("settings.byok.noConfiguredProviders")}
              onChange={(provider) => setForm((prev) => ({ ...prev, provider }))}
            />
          </SettingsRow>

          <SettingsRow
            title={t("settings.rows.model")}
            description={t("settings.help.model")}
          >
            <Input
              value={form.model}
              onChange={(event) => setForm((prev) => ({ ...prev, model: event.target.value }))}
              className="h-8 w-[280px] rounded-full text-[13px]"
            />
          </SettingsRow>

          {(dirty || saving || settings.requires_restart) ? (
            <SettingsFooter
              dirty={dirty}
              saving={saving}
              saved={settings.requires_restart && !dirty}
              onSave={onSave}
            />
          ) : null}
          {configuredProviders.length === 0 ? (
            <SettingsRow title={t("settings.byok.configureFirst")}>
              <Button size="sm" variant="outline" onClick={onOpenByok} className="rounded-full">
                {t("settings.byok.openByok")}
              </Button>
            </SettingsRow>
          ) : null}
        </SettingsGroup>
      </section>

      {onRestart && (
        <section>
          <SettingsSectionTitle>{t("settings.sections.system")}</SettingsSectionTitle>
          <SettingsGroup>
            <SettingsRow
              title={t("settings.rows.restart")}
              description={t("app.system.restartHint")}
            >
              <Button
                size="sm"
                variant="outline"
                onClick={onRestart}
                disabled={isRestarting}
                className="rounded-full"
              >
                {isRestarting ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                )}
                {isRestarting ? t("app.system.restarting") : t("app.system.restart")}
              </Button>
            </SettingsRow>
            <SettingsRow
              title={t("settings.rows.configPath")}
              description={t("settings.help.configPath")}
            >
              <span className="max-w-[260px] truncate text-right text-[13px] text-muted-foreground">
                {settings.runtime.config_path || t("settings.values.notAvailable")}
              </span>
            </SettingsRow>
          </SettingsGroup>
        </section>
      )}
    </div>
  );
}

function ProviderPicker({
  providers,
  value,
  emptyLabel,
  onChange,
}: {
  providers: SettingsPayload["providers"];
  value: string;
  emptyLabel: string;
  onChange: (provider: string) => void;
}) {
  const selectedProvider = providers.find((provider) => provider.name === value) ?? null;
  const disabled = providers.length === 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          className={cn(
            "h-8 w-[210px] justify-between rounded-full border-input bg-background px-3 text-[13px] font-normal shadow-none",
            "hover:bg-accent/55 focus-visible:ring-2 focus-visible:ring-ring",
            disabled && "text-muted-foreground",
          )}
        >
          <span className="truncate">{selectedProvider?.label ?? emptyLabel}</span>
          <ChevronDown className="ml-2 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="max-h-[18rem] w-[240px] overflow-y-auto rounded-[18px] border-border/65 bg-popover p-1.5 text-popover-foreground shadow-[0_18px_55px_rgba(15,23,42,0.18)] dark:border-white/10 dark:shadow-[0_22px_55px_rgba(0,0,0,0.45)]"
      >
        {providers.map((provider) => {
          const selected = provider.name === value;
          return (
            <DropdownMenuItem
              key={provider.name}
              onSelect={() => onChange(provider.name)}
              className={cn(
                "flex cursor-default items-center justify-between gap-2 rounded-[12px] px-3 py-2 text-[13px]",
                "focus:bg-muted focus:text-foreground",
                selected && "bg-primary/10 text-primary focus:bg-primary/12 focus:text-primary",
              )}
            >
              <span className="truncate">{provider.label}</span>
              {selected ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden /> : null}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ByokSettings({
  settings,
  expandedProvider,
  providerForms,
  visibleProviderKeys,
  editingProviderKeys,
  providerSaving,
  onToggleProvider,
  onToggleProviderKey,
  onToggleProviderKeyEditing,
  onChangeProviderForm,
  onSaveProvider,
}: {
  settings: SettingsPayload;
  expandedProvider: string | null;
  providerForms: Record<string, { apiKey: string; apiBase: string }>;
  visibleProviderKeys: Record<string, boolean>;
  editingProviderKeys: Record<string, boolean>;
  providerSaving: string | null;
  onToggleProvider: (provider: string) => void;
  onToggleProviderKey: (provider: string) => void;
  onToggleProviderKeyEditing: (provider: string) => void;
  onChangeProviderForm: (provider: string, value: Partial<{ apiKey: string; apiBase: string }>) => void;
  onSaveProvider: (provider: string) => void;
}) {
  const { t } = useTranslation();
  const [showAllUnconfigured, setShowAllUnconfigured] = useState(false);
  const configuredProviders = settings.providers.filter((provider) => provider.configured);
  const unconfiguredProviders = settings.providers.filter((provider) => !provider.configured);
  const initialUnconfiguredCount = 6;
  const visibleUnconfiguredProviders = showAllUnconfigured
    ? unconfiguredProviders
    : unconfiguredProviders.slice(0, initialUnconfiguredCount);
  const hiddenUnconfiguredCount = Math.max(
    0,
    unconfiguredProviders.length - visibleUnconfiguredProviders.length,
  );
  const renderProviderRow = (provider: SettingsPayload["providers"][number]) => {
    const expanded = expandedProvider === provider.name;
    const form = providerForms[provider.name] ?? {
      apiKey: "",
      apiBase: provider.api_base ?? provider.default_api_base ?? "",
    };
    const saving = providerSaving === provider.name;
    const keyVisible = !!visibleProviderKeys[provider.name];
    const editingKey = !provider.configured || !!editingProviderKeys[provider.name];
    return (
      <div
        key={provider.name}
        className="divide-y divide-border/45"
      >
        <button
          type="button"
          onClick={() => onToggleProvider(provider.name)}
          className="flex min-h-[70px] w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-muted/35 sm:px-5"
        >
          <span className="flex min-w-0 items-center gap-3">
            <ProviderIcon provider={provider.name} />
            <span className="min-w-0">
              <span className="block truncate text-[15px] font-semibold leading-5 text-foreground">
                {provider.label}
              </span>
            </span>
          </span>
          <span
            className={cn(
              "rounded-full px-2.5 py-1 text-[12px] font-medium",
              provider.configured
                ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                : "bg-muted text-muted-foreground",
            )}
          >
            {provider.configured
              ? t("settings.byok.configured")
              : t("settings.byok.notConfigured")}
          </span>
        </button>

        {expanded ? (
          <div className="space-y-3 bg-muted/18 px-4 py-4 sm:px-5">
            <label className="block space-y-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">
                {t("settings.byok.apiKey")}
              </span>
              <div className="relative">
                {editingKey ? (
                  <>
                    <Input
                      type={keyVisible ? "text" : "password"}
                      value={form.apiKey}
                      onChange={(event) =>
                        onChangeProviderForm(provider.name, { apiKey: event.target.value })
                      }
                      placeholder={
                        provider.configured
                          ? t("settings.byok.apiKeyConfiguredPlaceholder")
                          : t("settings.byok.apiKeyPlaceholder")
                      }
                      className="h-9 rounded-full pr-11 text-[13px]"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => onToggleProviderKey(provider.name)}
                      aria-label={
                        keyVisible
                          ? t("settings.byok.hideApiKey")
                          : t("settings.byok.showApiKey")
                      }
                      className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {keyVisible ? (
                        <EyeOff className="h-3.5 w-3.5" aria-hidden />
                      ) : (
                        <Eye className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </Button>
                  </>
                ) : (
                  <>
                    <div className="flex h-9 items-center rounded-full border border-input bg-background px-3 pr-11 text-[13px] text-muted-foreground">
                      {provider.api_key_hint ?? t("settings.byok.configuredKeyHint")}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => onToggleProviderKeyEditing(provider.name)}
                      aria-label={t("settings.actions.edit")}
                      className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  </>
                )}
              </div>
            </label>
            <label className="block space-y-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">
                {t("settings.byok.apiBase")}
              </span>
              <Input
                value={form.apiBase}
                onChange={(event) =>
                  onChangeProviderForm(provider.name, { apiBase: event.target.value })
                }
                placeholder={provider.default_api_base ?? t("settings.byok.apiBasePlaceholder")}
                className="h-9 rounded-full text-[13px]"
              />
            </label>
            <div className="flex items-center justify-end">
              <Button
                size="sm"
                variant="outline"
                onClick={() => onSaveProvider(provider.name)}
                disabled={saving || (!provider.configured && !form.apiKey.trim())}
                className="rounded-full"
              >
                {saving ? t("settings.actions.saving") : t("settings.actions.save")}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    );
  };
  return (
    <div className="space-y-6">
      <p className="max-w-[42rem] text-[13px] leading-6 text-muted-foreground">
        {t("settings.byok.description")}
      </p>
      <div className="space-y-8">
        <section className="space-y-3">
          <ByokSectionHeader
            title={t("settings.byok.configuredSection")}
            count={configuredProviders.length}
          />
          <div className="overflow-hidden rounded-[22px] border border-border/45 bg-card/86 shadow-[0_18px_65px_rgba(15,23,42,0.07)] backdrop-blur-xl dark:border-white/10 dark:shadow-[0_18px_65px_rgba(0,0,0,0.22)]">
            {configuredProviders.length > 0 ? (
              <div className="divide-y divide-border/45">
                {configuredProviders.map(renderProviderRow)}
              </div>
            ) : (
              <ByokEmptyState>{t("settings.byok.noConfiguredProviders")}</ByokEmptyState>
            )}
          </div>
        </section>

        <section className="space-y-3">
          <ByokSectionHeader
            title={t("settings.byok.notConfiguredSection")}
            count={unconfiguredProviders.length}
          />
          <div className="overflow-hidden rounded-[22px] border border-border/45 bg-card/86 shadow-[0_18px_65px_rgba(15,23,42,0.07)] backdrop-blur-xl dark:border-white/10 dark:shadow-[0_18px_65px_rgba(0,0,0,0.22)]">
            <div className="divide-y divide-border/45">
              {visibleUnconfiguredProviders.map(renderProviderRow)}
            </div>
          </div>
          {hiddenUnconfiguredCount > 0 ? (
            <Button
              type="button"
              variant="ghost"
              onClick={() => setShowAllUnconfigured(true)}
              className="h-9 rounded-full px-3 text-[13px] text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            >
              {t("settings.byok.showMore", { count: hiddenUnconfiguredCount })}
            </Button>
          ) : showAllUnconfigured && unconfiguredProviders.length > initialUnconfiguredCount ? (
            <Button
              type="button"
              variant="ghost"
              onClick={() => setShowAllUnconfigured(false)}
              className="h-9 rounded-full px-3 text-[13px] text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            >
              {t("settings.byok.showLess")}
            </Button>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function ByokSectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-center justify-between px-1">
      <h2 className="text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
        {title}
      </h2>
      <span className="rounded-full bg-muted px-2 py-0.5 text-[11.5px] font-medium text-muted-foreground">
        {count}
      </span>
    </div>
  );
}

function ByokEmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[18px] border border-dashed border-border/65 bg-card/45 px-4 py-5 text-[13px] text-muted-foreground">
      {children}
    </div>
  );
}

const PROVIDER_ICONS: Record<string, LucideIcon> = {
  custom: Hexagon,
  openrouter: Sparkles,
  aihubmix: Triangle,
  anthropic: Brain,
  openai: Bot,
  deepseek: Waves,
  zhipu: Grid3X3,
  dashscope: Cloud,
  moonshot: Moon,
  minimax: Zap,
  minimax_anthropic: Brain,
  groq: Cpu,
  huggingface: Layers,
  gemini: Gem,
  mistral: Orbit,
  siliconflow: Layers,
  volcengine: Cloud,
  volcengine_coding_plan: Cloud,
  byteplus: Cloud,
  byteplus_coding_plan: Cloud,
  qianfan: Database,
  azure_openai: Cloud,
  bedrock: Database,
};

function ProviderIcon({ provider }: { provider: string }) {
  const Icon = PROVIDER_ICONS[provider] ?? Hexagon;
  return (
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-muted text-foreground/82 shadow-[inset_0_0_0_1px_rgba(0,0,0,0.025)] dark:bg-muted/70">
      <Icon className="h-5 w-5" strokeWidth={2} aria-hidden />
    </span>
  );
}

function SettingsSectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-2 px-1 text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
      {children}
    </h2>
  );
}

function SettingsGroup({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[22px] border border-border/45 bg-card/86 shadow-[0_18px_65px_rgba(15,23,42,0.075)] backdrop-blur-xl dark:border-white/10 dark:shadow-[0_18px_65px_rgba(0,0,0,0.24)]">
      <div className="divide-y divide-border/45">{children}</div>
    </div>
  );
}

function SettingsRow({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex min-h-[62px] flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0">
        <div className="text-[14px] font-medium leading-5 text-foreground">{title}</div>
        {description ? (
          <div className="mt-0.5 max-w-[28rem] text-[12px] leading-5 text-muted-foreground">
            {description}
          </div>
        ) : null}
      </div>
      {children ? <div className="shrink-0 sm:ml-6">{children}</div> : null}
    </div>
  );
}

function SettingsFooter({
  dirty,
  saving,
  saved,
  onSave,
}: {
  dirty: boolean;
  saving: boolean;
  saved: boolean;
  onSave: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-[58px] items-center justify-between gap-4 px-4 py-3 sm:px-5">
      <div className="text-[13px] text-muted-foreground">
        {saved ? t("settings.status.savedRestart") : t("settings.status.unsaved")}
      </div>
      <Button size="sm" variant="outline" onClick={onSave} disabled={!dirty || saving} className="rounded-full">
        {saving ? t("settings.actions.saving") : t("settings.actions.save")}
      </Button>
    </div>
  );
}
