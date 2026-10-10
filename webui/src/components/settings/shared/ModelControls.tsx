import { useEffect, useId, useMemo, useRef, useState, type ComponentProps } from "react";
import {
  Check,
  CircleAlert,
  Hexagon,
  Pencil,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { SkeletonStatus } from "@/components/settings/shared/SkeletonStatus";
import { Button } from "@/components/ui/button";
import { ControlChevron } from "@/components/ui/control-chevron";
import { ComboboxOption, useComboboxNavigation } from "@/components/ui/combobox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SearchInput } from "@/components/ui/input";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { useProviderModelCatalog } from "@/hooks/useProviderModelCatalog";
import { providerBrand } from "@/lib/provider-brand";
import { PROVIDER_ICONS } from "@/lib/provider-icons";
export { PROVIDER_ICONS } from "@/lib/provider-icons";
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
  "orcarouter",
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

export function parseContextWindowTokens(value: string): number {
  const match = /^(\d+(?:\.\d+)?)\s*([km]?)$/i.exec(value.trim());
  if (!match) return NaN;
  const exponent = { k: 3, m: 6 }[match[2].toLowerCase()] ?? 0;
  const tokens = Number(`${match[1]}e${exponent}`);
  return Number.isSafeInteger(tokens) && tokens > 0 ? tokens : NaN;
}

export function formatContextWindowInput(tokens: number): string {
  if (!Number.isFinite(tokens)) return "";
  if (tokens % 1_000_000 === 0) return `${tokens / 1_000_000}m`;
  if (tokens % 1_000 === 0) return `${tokens / 1_000}k`;
  return String(tokens);
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
  triggerProps,
  emptyLabel,
  showProviderLogos = false,
  onChange,
}: {
  providers: Array<{ name: string; label: string }>;
  value: string;
  triggerProps?: Pick<ComponentProps<typeof Button>, "id" | "aria-label" | "aria-describedby" | "aria-invalid" | "disabled">;
  emptyLabel: string;
  showProviderLogos?: boolean;
  onChange: (provider: string) => void;
}) {
  const selectedProvider = providers.find((provider) => provider.name === value) ?? null;
  const disabled = !!triggerProps?.disabled || providers.length === 0;

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger
          {...triggerProps}
          aria-label={triggerProps?.["aria-label"] ?? selectedProvider?.label ?? emptyLabel}
          type="button"
          disabled={disabled}
          className={cn(
            "w-full justify-between rounded-full border-input bg-background text-[13px] font-normal shadow-none",
            "settings-hover focus-visible:ring-2 focus-visible:ring-ring",
            disabled && "text-muted-foreground",
          )}
        >
          <SelectValue placeholder={emptyLabel}><span className="flex min-w-0 items-center gap-2">
            {selectedProvider && showProviderLogos ? (
              <ProviderPickerIcon
                provider={selectedProvider.name}
                showBrandLogos={showProviderLogos}
              />
            ) : null}
            <span className="truncate">{selectedProvider?.label ?? emptyLabel}</span>
          </span></SelectValue>
        </SelectTrigger>
      <SelectContent>
        {providers.map((provider) => {
          return (
            <SelectItem
              key={provider.name}
              value={provider.name}
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
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
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
  onProviderOAuthLogin,
  providerSigningIn = false,
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
  onProviderOAuthLogin?: (provider: string) => void;
  providerSigningIn?: boolean;
  onChange: (model: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const catalogNoticeId = useId();
  const catalogSignInRef = useRef<HTMLButtonElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const restoreInputOnClose = useRef(false);
  const effectiveProvider =
    provider === "auto" ? settings.agent.resolved_provider ?? provider : provider;
  const hasConcreteProvider = Boolean(effectiveProvider && effectiveProvider !== "auto");
  const hasStaticModels = models !== undefined;
  const providerRow = settingsProviderRow(settings, effectiveProvider);
  const providerConfigured = settingsProviderConfigured(settings, effectiveProvider);
  const providerRequiresConfiguration =
    !hasStaticModels && hasConcreteProvider && !providerConfigured;
  const providerHasManagedModels = ["builtin", "hybrid"].includes(
    providerRow?.model_catalog ?? "",
  );
  const providerUsesManualModelIds =
    !hasStaticModels &&
    hasConcreteProvider &&
    providerConfigured &&
    providerRow?.auth_type === "oauth" &&
    !providerHasManagedModels;
  const canFetchModels =
    !hasStaticModels &&
    hasConcreteProvider && providerConfigured && !providerUsesManualModelIds;
  const normalizedQuery = query.trim().toLowerCase();
  const defersModelList = DEFERRED_MODEL_LIST_PROVIDERS.has(effectiveProvider);
  const hasDeferredSearchQuery =
    normalizedQuery.length >= DEFERRED_MODEL_LIST_QUERY_MIN_LENGTH;
  const shouldFetchModels =
    canFetchModels && (!defersModelList || hasDeferredSearchQuery);
  const { payload, loading, refreshing, failed, needsSignIn, retry } = useProviderModelCatalog({
    revision: providerRow ?? settings,
    token,
    provider: effectiveProvider,
    enabled: open && shouldFetchModels,
  });
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
  const waitingForModelSearch =
    open && canFetchModels && defersModelList && !hasDeferredSearchQuery;
  const hasModelList = hasStaticModels || payload?.status === "available";
  const catalogNeedsSignIn = !hasStaticModels && needsSignIn;
  const showModels = Boolean(
    !catalogNeedsSignIn && hasModelList
      && (hasStaticModels || (payload && (!isCatalog || normalizedQuery))),
  );
  const customCandidate = query.trim();
  const allowCustomModel = !providerRequiresConfiguration && !catalogNeedsSignIn;
  const exactQueryMatch = providerModels.some((model) => model.id === customCandidate);
  const showCustomModel = Boolean(
    allowCustomModel && customCandidate && !exactQueryMatch && customCandidate !== value,
  );
  const providerModelCount = payload?.model_count ?? providerModels.length;
  const modelUnconfigured = !value.trim() || !providerConfigured;
  const showCatalogNotice = !hasStaticModels && (catalogNeedsSignIn
    || (open && shouldFetchModels && !refreshing && failed));

  useEffect(() => {
    if (!open || loading) return;
    if (catalogNeedsSignIn) catalogSignInRef.current?.focus();
    else searchInputRef.current?.focus();
  }, [open, catalogNeedsSignIn, loading]);

  useEffect(() => {
    setQuery(providerUsesManualModelIds || !hasConcreteProvider ? value : "");
  }, [effectiveProvider, hasConcreteProvider, providerUsesManualModelIds, value]);

  const openPicker = (nextQuery?: string) => {
    if (nextQuery !== undefined || !open) {
      setQuery(nextQuery ?? (providerUsesManualModelIds || !hasConcreteProvider ? value : ""));
    }
    restoreInputOnClose.current = false;
    setOpen(true);
  };

  const closePicker = (restoreFocus = false) => {
    restoreInputOnClose.current = restoreFocus;
    setOpen(false);
  };
  const selectModel = (model: string) => {
    onChange(model);
    closePicker(true);
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
    onClose: () => closePicker(true),
  });

  const renderModelRow = (
    model: ProviderModelsPayload["models"][number],
    options: { selected?: boolean } = {},
  ) => (
    <ComboboxOption
      key={model.id}
      {...navigation.getOptionProps(model.id)}
      className={cn(
        "flex cursor-default items-center justify-between gap-2 rounded-control px-2 py-1.5 text-[12px]",
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
            <span className="mt-0.5 flex min-w-0 flex-wrap gap-x-2 text-[10.5px] text-muted-foreground">
              {model.label && model.label !== model.id ? <span className="truncate font-mono">{model.id}</span> : null}{" "}
              {model.description ? <span className="truncate">{model.description}</span> : null}
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
      <PopoverAnchor asChild>
        <div className="relative w-full">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2">
            <ProviderPickerIcon
              provider={effectiveProvider}
              showBrandLogos={showProviderLogos}
              unconfigured={modelUnconfigured}
            />
          </span>
          <SearchInput
            ref={searchInputRef}
            value={open && !catalogNeedsSignIn ? query : value}
            readOnly={catalogNeedsSignIn}
            onClick={() => openPicker()}
            onChange={(event) => openPicker(event.target.value)}
            {...navigation.inputProps}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (!open && ["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) {
                event.preventDefault();
                openPicker();
                return;
              }
              navigation.inputProps.onKeyDown(event);
            }}
            placeholder={open
              ? searchPlaceholder || tx("settings.models.searchModels", "Search or type model ID")
              : emptyLabel || tx("settings.models.selectModel", "Select model")}
            aria-label={emptyLabel || tx("settings.models.selectModel", "Select model")}
            aria-expanded={open}
            aria-describedby={showCatalogNotice ? catalogNoticeId : undefined}
            className="h-9 pl-9 pr-9 text-[13px] font-medium"
          />
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
            <ControlChevron />
          </span>
        </div>
      </PopoverAnchor>
      <PopoverContent
        align="end"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (restoreInputOnClose.current) {
            restoreInputOnClose.current = false;
            searchInputRef.current?.focus({ preventScroll: true });
          }
        }}
        onEscapeKeyDown={() => { restoreInputOnClose.current = true; }}
        onInteractOutside={(event) => {
          if (event.target === searchInputRef.current) event.preventDefault();
          else restoreInputOnClose.current = false;
        }}
        className="w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-2rem)] p-1.5"
      >

        {showCatalogNotice ? (
          <div className="mx-1 mb-1.5 flex items-start gap-2 rounded-control bg-muted/60 px-2.5 py-2 text-[11px] leading-4">
            {catalogNeedsSignIn ? <ProviderPickerIcon
              provider={effectiveProvider}
              showBrandLogos={showProviderLogos}
            /> : null}
            <div className="min-w-0 flex-1">
              <div id={catalogNoticeId} role="status">
                <p className="font-medium text-foreground">
                  {catalogNeedsSignIn
                    ? tx("settings.models.catalogAuthRequired", "Authorization expired. Please sign in again.")
                    : <button
                        type="button"
                        className="rounded-sm text-left underline decoration-foreground/30 underline-offset-2 hover:decoration-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => {
                          void retry();
                          searchInputRef.current?.focus();
                        }}
                      >
                        {tx("settings.models.catalogUnavailable", "Refresh failed. Click to retry")}
                      </button>}
                </p>
                {!catalogNeedsSignIn && payload?.status === "available" ? <p className="mt-1 text-muted-foreground">
                  {payload.source !== "fallback"
                    ? tx("settings.models.catalogStale", "Cached list may be out of date.")
                    : tx("settings.models.catalogFallback", "Built-in list may be out of date.")}
                </p> : null}
              </div>
              {catalogNeedsSignIn && onProviderOAuthLogin && providerRow?.oauth_login_supported ? (
                <Button
                  ref={catalogSignInRef}
                  type="button"
                  size="sm"
                  variant="outline"
                  className="mt-2 h-7 rounded-full px-2.5 text-[11px]"
                  disabled={providerSigningIn}
                  aria-describedby={catalogNoticeId}
                  onClick={() => {
                    closePicker();
                    onProviderOAuthLogin(effectiveProvider);
                  }}
                >
                  {providerSigningIn
                    ? tx("settings.oauth.signingIn", "Signing in...")
                    : tx("settings.oauth.signInAgain", "Sign in again")}
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}

        {catalogNeedsSignIn ? null : providerRequiresConfiguration ? (
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
            {tx("settings.models.autoProviderCustomOnly", "Enter a model ID manually when using automatic provider selection.")}
          </div>
        ) : waitingForModelSearch ? (
          <div className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
            {tx("settings.models.searchCatalog", "Search this provider’s model catalog.")}
          </div>
        ) : loading ? (
          <SkeletonStatus
            label={tx("settings.models.loadingModels", "Loading models...")}
            className="space-y-0.5 py-1"
          >
            {["w-3/5", "w-4/5", "w-1/2"].map((width) => (
              <div key={width} className="flex items-center gap-2 px-2 py-1.5">
                <div className="h-3.5 w-3.5 shrink-0 rounded-full bg-muted-foreground/20" />
                <div className="min-w-0 flex-1">
                  <div className={cn("h-3 rounded bg-muted-foreground/20", width)} />
                  <div className="mt-1.5 h-2.5 w-2/5 rounded bg-muted-foreground/10" />
                </div>
              </div>
            ))}
          </SkeletonStatus>
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
            {tx("settings.models.searchCatalog", "Search this provider’s model catalog.")}
            {providerModelCount ? <> {t("settings.models.availableCount", {
              defaultValue: "Models available: {{count}}",
              count: providerModelCount,
            })}</> : null}
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
                  className="flex cursor-default items-center gap-2 rounded-control px-2 py-1.5 text-[12px]"
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
  const { logoUrl, logoLoaded, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);
  const isLogoTile = brand?.logoLayout === "tile" && logoUrl === brand.logoUrl;

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
        className={cn(
          "grid h-5 w-5 shrink-0 place-items-center overflow-hidden rounded-md",
          logoLoaded ? (isLogoTile ? "bg-transparent" : "bg-white") : "bg-muted",
        )}
        aria-hidden
      >
        <span
          className={cn(
            "col-start-1 row-start-1 grid h-full w-full place-items-center rounded-md text-[7.5px] font-semibold text-white",
            logoLoaded ? "opacity-0" : "opacity-100",
          )}
          style={{ backgroundColor: brand?.color }}
        >
          {brand?.initials}
        </span>
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          referrerPolicy="no-referrer"
          draggable={false}
          className={cn(
            "col-start-1 row-start-1 object-contain",
            isLogoTile ? "h-5 w-5" : "h-3.5 w-3.5",
            logoLoaded ? "opacity-100" : "opacity-0",
          )}
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

