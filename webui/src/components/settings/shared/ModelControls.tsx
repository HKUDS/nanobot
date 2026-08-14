import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Brain,
  Check,
  ChevronDown,
  CircleAlert,
  Cloud,
  Cpu,
  Database,
  Gem,
  Grid3X3,
  Hexagon,
  Layers,
  Loader2,
  Moon,
  Orbit,
  Pencil,
  Search,
  Sparkles,
  Triangle,
  Waves,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ComboboxOption, useComboboxNavigation } from "@/components/ui/combobox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { fetchProviderModels } from "@/lib/api";
import { providerBrand } from "@/lib/provider-brand";
import type { ProviderModelsPayload, SettingsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

const DEFERRED_MODEL_LIST_PROVIDERS = new Set([
  "aihubmix",
  "atomic_chat",
  "byteplus",
  "byteplus_coding_plan",
  "huggingface",
  "lm_studio",
  "modelscope",
  "novita",
  "ollama",
  "openrouter",
  "ovms",
  "siliconflow",
  "vllm",
  "volcengine",
  "volcengine_coding_plan",
]);
const DEFERRED_MODEL_LIST_QUERY_MIN_LENGTH = 2;

export function normalizeContextWindowTokens(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 200_000;
}

function settingsProviderRow(
  payload: SettingsPayload,
  provider: string | null | undefined,
): SettingsPayload["providers"][number] | null {
  if (!provider) return null;
  return payload.providers.find((row) => row.name === provider) ?? null;
}

export function settingsProviderConfigured(
  payload: SettingsPayload,
  provider: string | null | undefined,
  resolvedProvider?: string | null,
): boolean {
  const row = settingsProviderRow(payload, provider);
  if (row) return row.configured;
  if (provider === "auto") {
    const resolvedRow = settingsProviderRow(
      payload,
      resolvedProvider ?? payload.agent.resolved_provider ?? payload.agent.provider,
    );
    if (resolvedRow) return resolvedRow.configured;
  }
  return payload.agent.has_api_key;
}

export function ProviderPicker({
  providers,
  value,
  emptyLabel,
  showProviderLogos = false,
  onChange,
}: {
  providers: Array<{ name: string; label: string }>;
  value: string;
  emptyLabel: string;
  showProviderLogos?: boolean;
  onChange: (provider: string) => void;
}) {
  const selectedProvider = providers.find((provider) => provider.name === value) ?? null;
  const disabled = providers.length === 0;

  return (
    <DropdownMenu modal={false}>
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
          <span className="flex min-w-0 items-center gap-2">
            {selectedProvider && showProviderLogos ? (
              <ProviderPickerIcon
                provider={selectedProvider.name}
                showBrandLogos={showProviderLogos}
              />
            ) : null}
            <span className="truncate">{selectedProvider?.label ?? emptyLabel}</span>
          </span>
          <ChevronDown className="ml-2 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="max-h-[18rem] w-[240px] overflow-y-auto scrollbar-thin scrollbar-track-transparent"
      >
        {providers.map((provider) => {
          const selected = provider.name === value;
          return (
            <DropdownMenuItem
              key={provider.name}
              onSelect={() => onChange(provider.name)}
              className={cn(
                "flex cursor-default items-center justify-between gap-2 text-[13px]",
                selected && "bg-muted/80 text-foreground focus:bg-muted",
              )}
            >
              <span className="flex min-w-0 items-center gap-2">
                {showProviderLogos ? (
                  <ProviderPickerIcon
                    provider={provider.name}
                    showBrandLogos={showProviderLogos}
                  />
                ) : null}
                <span className="truncate">{provider.label}</span>
              </span>
              {selected ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden /> : null}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ModelIdPicker({
  token,
  settings,
  provider,
  models,
  value,
  showProviderLogos,
  emptyLabel,
  searchPlaceholder,
  emptyMessage,
  onChange,
}: {
  token: string;
  settings: SettingsPayload;
  provider: string;
  models?: string[];
  value: string;
  showProviderLogos: boolean;
  emptyLabel?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  onChange: (model: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [payload, setPayload] = useState<ProviderModelsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const effectiveProvider =
    provider === "auto" ? settings.agent.resolved_provider ?? provider : provider;
  const hasConcreteProvider = Boolean(effectiveProvider && effectiveProvider !== "auto");
  const hasStaticModels = models !== undefined;
  const providerRow = settingsProviderRow(settings, effectiveProvider);
  const providerConfigured = settingsProviderConfigured(settings, effectiveProvider);
  const providerRequiresConfiguration =
    !hasStaticModels && hasConcreteProvider && !providerConfigured;
  const providerHasBuiltinModels = providerRow?.model_catalog === "builtin";
  const providerUsesManualModelIds =
    !hasStaticModels &&
    hasConcreteProvider &&
    providerConfigured &&
    providerRow?.auth_type === "oauth" &&
    !providerHasBuiltinModels;
  const canFetchModels =
    !hasStaticModels &&
    hasConcreteProvider && providerConfigured && !providerUsesManualModelIds;
  const normalizedQuery = query.trim().toLowerCase();
  const providerModels: ProviderModelsPayload["models"] = useMemo(
    () => hasStaticModels
      ? (models?.map((id) => ({ id })) ?? [])
      : (payload?.models ?? []),
    [hasStaticModels, models, payload?.models],
  );
  const visibleModels = useMemo(
    () => providerModels
      .filter((model) => {
        if (!normalizedQuery) return true;
        return [model.id, model.label ?? "", model.description ?? "", model.owned_by ?? ""]
          .some((field) => field.toLowerCase().includes(normalizedQuery));
      })
      .slice(0, 80),
    [normalizedQuery, providerModels],
  );
  const isCatalog = payload?.catalog_kind === "catalog";
  const defersModelList = DEFERRED_MODEL_LIST_PROVIDERS.has(effectiveProvider);
  const hasDeferredSearchQuery =
    normalizedQuery.length >= DEFERRED_MODEL_LIST_QUERY_MIN_LENGTH;
  const shouldFetchModels =
    canFetchModels && (!defersModelList || hasDeferredSearchQuery);
  const waitingForModelSearch =
    open && canFetchModels && defersModelList && !hasDeferredSearchQuery;
  const hasModelList = hasStaticModels || payload?.status === "available";
  const showModels = Boolean(
    hasModelList && (hasStaticModels || (payload && (!isCatalog || normalizedQuery))),
  );
  const customCandidate = query.trim();
  const allowCustomModel = !providerRequiresConfiguration;
  const exactQueryMatch = providerModels.some((model) => model.id === customCandidate);
  const showCustomModel = Boolean(
    allowCustomModel && customCandidate && !exactQueryMatch && customCandidate !== value,
  );
  const providerModelCount = payload?.model_count ?? providerModels.length;
  const modelUnconfigured = !value.trim() || !providerConfigured;

  useEffect(() => {
    if (!open) return;
    setQuery(providerUsesManualModelIds || !hasConcreteProvider ? value : "");
  }, [open, effectiveProvider, hasConcreteProvider, providerUsesManualModelIds, value]);

  useEffect(() => {
    if (!open || !shouldFetchModels) {
      setPayload(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setPayload(null);
    setError(null);
    setLoading(true);
    fetchProviderModels(tokenRef.current, effectiveProvider)
      .then((nextPayload) => {
        if (!cancelled) setPayload(nextPayload);
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
  }, [effectiveProvider, open, shouldFetchModels]);

  const selectModel = (model: string) => {
    onChange(model);
    setOpen(false);
  };
  const navigationValues = useMemo(
    () => [
      ...(showModels ? visibleModels.map((model) => model.id) : []),
      ...(showCustomModel ? [customCandidate] : []),
    ],
    [customCandidate, showCustomModel, showModels, visibleModels],
  );
  const navigation = useComboboxNavigation({
    open,
    values: navigationValues,
    selectedValue: value,
    onSelect: selectModel,
    onClose: () => setOpen(false),
  });

  const renderModelRow = (
    model: ProviderModelsPayload["models"][number],
    options: { selected?: boolean } = {},
  ) => (
    <ComboboxOption
      key={model.id}
      {...navigation.getOptionProps(model.id)}
      className={cn(
        "flex cursor-default items-center justify-between gap-2 rounded-[12px] px-2 py-1.5 text-[12px]",
        options.selected && "text-foreground",
      )}
    >
      <span className="flex min-w-0 items-center gap-2">
        <ProviderPickerIcon
          provider={effectiveProvider}
          showBrandLogos={showProviderLogos}
          unconfigured={!providerConfigured}
        />
        <span className="min-w-0">
          <span className="block truncate font-medium text-foreground">
            {model.label ?? model.id}
          </span>
          {model.description || (model.label && model.label !== model.id) ? (
            <span className="mt-0.5 block truncate text-[10.5px] text-muted-foreground">
              {[model.label && model.label !== model.id ? model.id : null, model.description]
                .filter(Boolean)
                .join(" · ")}
            </span>
          ) : null}
        </span>
      </span>
      <span className="ml-2 flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground">
        {model.context_window ? <span>{formatContextWindow(model.context_window)}</span> : null}
        {options.selected ? <Check className="h-3.5 w-3.5 text-foreground" aria-hidden /> : null}
      </span>
    </ComboboxOption>
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className={cn(
            "h-9 w-[min(360px,70vw)] justify-between rounded-full border-input bg-background px-3 text-[12px] font-normal shadow-none",
            "hover:bg-accent/55 focus-visible:ring-2 focus-visible:ring-ring",
          )}
        >
          <span className="flex min-w-0 items-center gap-2">
            <ProviderPickerIcon
              provider={effectiveProvider}
              showBrandLogos={showProviderLogos}
              unconfigured={modelUnconfigured}
            />
            <span
              className={cn(
                "min-w-0 truncate font-medium",
                value ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {value || emptyLabel || tx("settings.models.selectModel", "Select model")}
            </span>
          </span>
          <ChevronDown className="ml-2 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[360px] max-w-[calc(100vw-2rem)] p-1.5"
      >
        <div className="p-1 pb-1.5">
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              {...navigation.inputProps}
              placeholder={
                searchPlaceholder || tx("settings.models.searchModels", "Search or type model ID")
              }
              aria-label={
                searchPlaceholder || tx("settings.models.searchModels", "Search or type model ID")
              }
              className="h-8 rounded-full pl-8 pr-3 text-[12px]"
            />
          </div>
        </div>

        {providerRequiresConfiguration ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {tx("settings.models.providerNotConfigured", "Configure this provider before loading models.")}
          </div>
        ) : hasStaticModels && !providerModels.length ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {emptyMessage || tx("settings.models.unsupportedModelList", "Type a model ID manually.")}
          </div>
        ) : providerUsesManualModelIds ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {tx("settings.models.unsupportedModelList", "Type a model ID manually.")}
          </div>
        ) : !canFetchModels ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {tx("settings.models.autoProviderCustomOnly", "Auto provider mode uses custom model IDs.")}
          </div>
        ) : waitingForModelSearch ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {tx("settings.models.searchCatalog", "Search provider catalog to choose a model.")}
          </div>
        ) : loading ? (
          <div className="flex items-center gap-2 px-2 py-1.5 text-[11px] text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            {tx("settings.models.loadingModels", "Loading models...")}
          </div>
        ) : error || payload?.status === "error" ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {payload?.message || error || tx("settings.models.loadFailed", "Model list unavailable.")}
          </div>
        ) : payload?.status === "not_configured" ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {tx("settings.models.providerNotConfigured", "Configure this provider before loading models.")}
          </div>
        ) : payload?.status === "unsupported" || payload?.status === "missing_api_base" ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {payload.message || tx("settings.models.unsupportedModelList", "Type a model ID manually.")}
          </div>
        ) : isCatalog && !normalizedQuery ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {tx("settings.models.searchCatalog", "Search provider catalog to choose a model.")}
            {providerModelCount ? ` ${providerModelCount} ${tx("settings.models.modelsAvailable", "available")}.` : ""}
          </div>
        ) : null}

        {navigationValues.length ? (
          <div
            {...navigation.listProps}
            aria-label={searchPlaceholder || tx("settings.models.selectModel", "Select model")}
            className="max-h-[16rem] overflow-y-auto pr-0.5 scrollbar-thin scrollbar-track-transparent"
          >
            {showModels
              ? visibleModels.map((model) =>
                renderModelRow(model, { selected: model.id === value }),
              )
              : null}
            {showCustomModel ? (
              <>
                {showModels && visibleModels.length ? (
                  <div role="separator" className="-mx-1.5 my-1.5 h-px bg-border/50" />
                ) : null}
                <ComboboxOption
                  {...navigation.getOptionProps(customCandidate)}
                  className="flex cursor-default items-center gap-2 rounded-[12px] px-2 py-1.5 text-[12px]"
                >
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-muted/80 text-muted-foreground">
                    <Pencil className="h-3 w-3" aria-hidden />
                  </span>
                  <span className="min-w-0 truncate">
                    {tx("settings.models.useCustomModel", "Use")}{" "}
                    <span className="font-medium text-foreground">“{customCandidate}”</span>
                  </span>
                </ComboboxOption>
              </>
            ) : null}
          </div>
        ) : showModels ? (
          <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
            {tx("settings.models.noModelResults", "No matching models.")}
          </div>
        ) : null}

      </PopoverContent>
    </Popover>
  );
}

export function formatContextWindow(tokens: number): string {
  if (tokens >= 1_000_000) {
    const value = tokens / 1_000_000;
    return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}M`;
  }
  if (tokens >= 1_000) {
    const value = tokens / 1_000;
    return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}K`;
  }
  return String(tokens);
}

export function formatModelContextWindow(tokens: number): string {
  if (tokens === 65_536) return "64K";
  if (tokens === 262_144) return "256K";
  if (tokens === 1_048_576) return "1M";
  return formatContextWindow(tokens);
}

export function ProviderPickerIcon({
  provider,
  showBrandLogos,
  unconfigured = false,
}: {
  provider: string;
  showBrandLogos: boolean;
  unconfigured?: boolean;
}) {
  const brand = providerBrand(provider);
  const Icon = PROVIDER_ICONS[provider] ?? Hexagon;
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);

  if (unconfigured) {
    return (
      <span
        data-testid="provider-picker-unconfigured-icon"
        className="grid h-5 w-5 shrink-0 place-items-center text-amber-700 dark:text-amber-200"
        aria-hidden
      >
        <CircleAlert className="h-4 w-4" strokeWidth={1.8} />
      </span>
    );
  }

  if (showBrandLogos && logoUrl) {
    return (
      <span
        data-testid={`provider-picker-logo-${provider}`}
        className="grid h-5 w-5 shrink-0 place-items-center overflow-hidden rounded-md border border-border/35 bg-background"
        aria-hidden
      >
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-3.5 w-3.5 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      </span>
    );
  }

  if (showBrandLogos && brand) {
    return (
      <span
        data-testid={`provider-picker-logo-fallback-${provider}`}
        className="grid h-5 w-5 shrink-0 place-items-center rounded-md text-[7.5px] font-semibold text-white"
        style={{ backgroundColor: brand.color }}
        aria-hidden
      >
        {brand.initials}
      </span>
    );
  }

  return (
    <span
      className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground"
      aria-hidden
    >
      <Icon className="h-3 w-3" strokeWidth={2} />
    </span>
  );
}

export function optionRowsWithCurrent(
  options: Array<{ name: string; label: string }>,
  value: string,
): Array<{ name: string; label: string }> {
  if (!value || options.some((option) => option.name === value)) return options;
  return [{ name: value, label: value }, ...options];
}

export const PROVIDER_ICONS: Record<string, LucideIcon> = {
  custom: Hexagon,
  openrouter: Sparkles,
  skywork: Sparkles,
  aihubmix: Triangle,
  anthropic: Brain,
  openai: Bot,
  deepseek: Waves,
  zhipu: Grid3X3,
  dashscope: Cloud,
  modelscope: Layers,
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
  ant_ling: Sparkles,
  azure_openai: Cloud,
  bedrock: Database,
  bocha: Search,
  brave: Search,
  duckduckgo: Search,
  exa: Search,
  jina: Search,
  kagi: Search,
  olostep: Search,
  searxng: Search,
  tavily: Search,
  vllm: Cpu,
  ollama: Cpu,
  lm_studio: Cpu,
  atomic_chat: Cpu,
  ovms: Cpu,
  nvidia: Zap,
};
