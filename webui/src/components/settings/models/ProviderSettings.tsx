import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { DisclosureContent } from "@/components/ui/disclosure";
import {
  ChevronDown,
  ChevronLeft,
  Clipboard,
  Eye,
  EyeOff,
  ExternalLink,
  Globe2,
  Loader2,
  Pencil,
  Zap,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { SettingsAddButton } from "@/components/settings/shared/SettingsAddButton";
import type { ProviderOperation } from "@/components/settings/models/useModelSettingsState";
import { RemoveActionButton } from "@/components/settings/shared/RemoveActionButton";
import { ProviderIcon } from "@/components/settings/shared/ProviderIcon";
import { ProviderSearchList } from "@/components/settings/models/ProviderSearchList";
export { ProviderIcon } from "@/components/settings/shared/ProviderIcon";
import {
  CapabilityInstallNotice,
  SettingsGroup,
  SettingsSectionTitle,
} from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { ModelAPIControl } from "@/components/settings/models/ModelAPIControl";
import { ProviderAPIControl } from "@/components/settings/models/ProviderAPIControl";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { SheetContent } from "@/components/ui/sheet";
import { FloatingPortalContext } from "@/components/ui/floating-portal";
import { Textarea } from "@/components/ui/textarea";
import { ProviderParameterFields } from "@/components/settings/models/ProviderParameterFields";
import {
  CUSTOM_PROVIDER_CREATION_KEY,
  emptyCustomProviderDraft,
  parseProviderObject,
  providerFormFromRow,
  providerJsonValue,
  type CustomProviderDraft,
  type ProviderAdvancedField,
  type ProviderForm,
} from "@/components/settings/models/providerForm";
export { CUSTOM_PROVIDER_CREATION_KEY, providerFormFromRow } from "@/components/settings/models/providerForm";
export type { CustomProviderDraft, ProviderForm } from "@/components/settings/models/providerForm";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";
import { copyTextToClipboard } from "@/lib/clipboard";
import type {
  NanobotFeaturesPayload,
  ModelAPIConfig,
  ProviderOAuthAuthorizationRequired,
  SettingsPayload,
} from "@/lib/types";

const OAUTH_PROXY_PROVIDERS = new Set(["openai_codex", "xai_grok"]);
type ProviderRequestOption = {
  kind: "priority" | "hosted_tool";
  titleKey: string;
  title: string;
  helpKey: string;
  help: string;
  toolType?: "web_search" | "x_search";
  defaultEnabled?: boolean;
  forceResponses?: boolean;
};
const PROVIDER_REQUEST_OPTIONS: Partial<Record<string, ProviderRequestOption[]>> = {
  openai_codex: [{
    kind: "priority",
    titleKey: "settings.providers.capabilityFastMode",
    title: "Fast mode",
    helpKey: "settings.providers.capabilityFastModeHelp",
    help: "Use OpenAI's priority service tier for faster responses. This consumes credits faster.",
  }],
  openai: [{
    kind: "hosted_tool",
    titleKey: "settings.providers.capabilityOpenAISearch",
    title: "OpenAI web search",
    helpKey: "settings.providers.capabilityOpenAISearchHelp",
    help: "Allow compatible Responses API models to search the web. Search activity appears in chat.",
    toolType: "web_search",
    forceResponses: true,
  }],
  xai_grok: [{
    kind: "hosted_tool",
    titleKey: "settings.providers.capabilityXSearch",
    title: "X Search",
    helpKey: "settings.providers.capabilityXSearchHelp",
    help: "Allow supported Grok models to use xAI-hosted X Search. Search activity appears in chat.",
    toolType: "x_search",
    defaultEnabled: true,
  }],
};
const CUSTOM_PROVIDER_ADVANCED_FIELDS: ProviderAdvancedField[] = [
  "extra_headers",
  "extra_body",
  "extra_query",
  "proxy",
  "thinking_style",
];

function isHostedSearchTool(tool: unknown, toolType: "web_search" | "x_search"): boolean {
  if (!tool || typeof tool !== "object" || Array.isArray(tool)) return false;
  const configuredType = (tool as Record<string, unknown>).type;
  if (typeof configuredType !== "string") return false;
  return configuredType === toolType
    || (toolType === "web_search" && configuredType.startsWith("web_search_"));
}

function hasHostedSearchTool(value: unknown, toolType: "web_search" | "x_search"): boolean {
  return Array.isArray(value) && value.some((tool) => isHostedSearchTool(tool, toolType));
}

function providerRequestOptionEnabled(
  option: ProviderRequestOption,
  extraBody: Record<string, unknown>,
): boolean {
  if (option.kind === "priority") return extraBody.service_tier === "priority";
  if (Object.prototype.hasOwnProperty.call(extraBody, "tools")) {
    return hasHostedSearchTool(extraBody.tools, option.toolType!);
  }
  return option.defaultEnabled === true;
}

function updateProviderRequestOption(
  option: ProviderRequestOption,
  enabled: boolean,
  form: ProviderForm,
): Partial<ProviderForm> {
  const extraBody = { ...(parseProviderObject(form.extraBody) ?? {}) };
  if (option.kind === "priority") {
    if (enabled) extraBody.service_tier = "priority";
    else if (extraBody.service_tier === "priority") delete extraBody.service_tier;
  } else {
    const toolType = option.toolType!;
    const tools = Array.isArray(extraBody.tools)
      ? extraBody.tools.filter((tool) => !isHostedSearchTool(tool, toolType))
      : [];
    if (enabled) tools.push({ type: toolType });
    if (tools.length || option.defaultEnabled) {
      extraBody.tools = tools;
    } else {
      delete extraBody.tools;
    }
  }
  return {
    extraBody: providerJsonValue(extraBody),
    ...(option.forceResponses && enabled
      ? { api: { supported_apis: ["responses"], preferred_api: "responses" } satisfies ModelAPIConfig }
      : {}),
  };
}

export function ProviderOAuthLoginDialog({
  flow,
  providerLabel,
  authorizationResponse,
  completing,
  error,
  remoteBrowserAccess,
  onAuthorizationResponseChange,
  onOpenAuthorization,
  onComplete,
  onClose,
}: {
  flow: ProviderOAuthAuthorizationRequired | null;
  providerLabel: string;
  authorizationResponse: string;
  completing: boolean;
  error: string | null;
  remoteBrowserAccess: boolean;
  onAuthorizationResponseChange: (value: string) => void;
  onOpenAuthorization: () => void;
  onComplete: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const expectsCallbackUrl = flow?.completion_input === "callback_url";
  const isDeviceCode = flow?.completion_input === "device_code";
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const inputId = expectsCallbackUrl ? "provider-oauth-callback" : "provider-oauth-code";
  const inputLabel = expectsCallbackUrl
    ? t("settings.oauth.callbackUrl")
    : t("settings.oauth.authorizationCode");

  return (
    <Dialog
      open={Boolean(flow)}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="w-[min(calc(100vw-2rem),28rem)]">
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            onComplete();
          }}
        >
          <DialogHeader>
            <DialogTitle>{providerLabel}</DialogTitle>
            <DialogDescription>
              {isDeviceCode
                ? t("settings.oauth.deviceCodeHelp")
                : expectsCallbackUrl
                ? remoteBrowserAccess
                  ? t("settings.oauth.remoteCallbackHelp")
                  : t("settings.oauth.localCallbackHelp")
                : remoteBrowserAccess
                  ? t("settings.oauth.remoteCodeHelp")
                  : t("settings.oauth.localCodeHelp")}
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 rounded-control border border-border/45 bg-muted/35 px-3 py-2.5 text-[12px] text-muted-foreground">
            {expectsCallbackUrl && remoteBrowserAccess ? (
              <Clipboard className="h-3.5 w-3.5 shrink-0" aria-hidden />
            ) : (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
            )}
            <span>
              {isDeviceCode
                ? t("settings.oauth.waitingForDeviceApproval")
                : expectsCallbackUrl && remoteBrowserAccess
                ? t("settings.oauth.pasteCallbackToContinue")
                : t("settings.oauth.waitingForCallback")}
            </span>
          </div>
          {isDeviceCode ? (
            <div className="space-y-2">
              <label htmlFor="provider-device-code" className="block text-xs font-medium text-foreground">
                {t("settings.oauth.deviceCode")}
              </label>
              <div className="flex items-center gap-2">
                <Input
                  id="provider-device-code"
                  value={flow?.user_code ?? ""}
                  readOnly
                  onFocus={(event) => event.target.select()}
                  className="h-12 text-center font-mono text-xl tracking-widest"
                />
                <Button type="button" variant="outline" onClick={async () => {
                  if (flow?.user_code && await copyTextToClipboard(flow.user_code)) {
                    setCopiedCode(flow.flow_id);
                  }
                }}>
                  <Clipboard className="mr-2 h-4 w-4" aria-hidden />
                  {copiedCode === flow?.flow_id ? t("code.copied") : t("code.copy")}
                </Button>
              </div>
            </div>
          ) : <div className="space-y-2">
            <label
              htmlFor={inputId}
              className="block text-xs font-medium text-foreground"
            >
              {inputLabel}
            </label>
            {expectsCallbackUrl ? (
              <Textarea
                id={inputId}
                value={authorizationResponse}
                onChange={(event) => onAuthorizationResponseChange(event.target.value)}
                placeholder={t("settings.oauth.callbackUrlPlaceholder")}
                aria-label={inputLabel}
                autoComplete="off"
                spellCheck={false}
                className="min-h-[88px] resize-none break-all font-mono text-[12px] leading-5"
              />
            ) : (
              <Input
                id={inputId}
                value={authorizationResponse}
                onChange={(event) => onAuthorizationResponseChange(event.target.value)}
                placeholder={inputLabel}
                aria-label={inputLabel}
                autoComplete="off"
                spellCheck={false}
              />
            )}
          </div>}
          {error ? (
            <p
              role="alert"
              className="rounded-control border border-destructive/20 bg-destructive/5 px-3 py-2.5 text-[12px] text-destructive"
            >
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onOpenAuthorization}>
              <ExternalLink className="mr-2 h-4 w-4" aria-hidden />
              {isDeviceCode
                ? t("settings.oauth.openGitHub")
                : expectsCallbackUrl
                ? t("settings.oauth.openChatGPT")
                : t("settings.oauth.signIn")}
            </Button>
            {!isDeviceCode ? <Button type="submit" disabled={!authorizationResponse.trim() || completing}>
              {completing ? t("settings.oauth.signingIn") : t("settings.oauth.finishSignIn")}
            </Button> : null}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ProviderRequestOptions({
  providerName,
  form,
  apiConfigurable,
  onChange,
}: {
  providerName: string;
  form: ProviderForm;
  apiConfigurable: boolean;
  onChange: (value: Partial<ProviderForm>) => void;
}) {
  const { t } = useTranslation();
  const options = (PROVIDER_REQUEST_OPTIONS[providerName] ?? [])
    .filter((option) => !option.forceResponses || apiConfigurable);
  if (options.length === 0) return null;
  const extraBody = parseProviderObject(form.extraBody) ?? {};

  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });

  return (
    <div className="overflow-hidden rounded-floating border border-border/45 bg-background/75">
      {options.map((option) => {
        const title = tx(option.titleKey, option.title);
        const Icon = option.kind === "priority" ? Zap : Globe2;
        const checked = providerRequestOptionEnabled(option, extraBody);
        return (
          <div
            key={option.titleKey}
            className="flex items-center justify-between gap-4 rounded-control px-4 py-3 transition-colors settings-hover focus-within:bg-sidebar-accent/60"
          >
            <div className="flex min-w-0 items-start gap-3">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted/70 text-muted-foreground">
                <Icon className="h-4 w-4" aria-hidden />
              </span>
              <div className="min-w-0">
                <p className="text-[13px] font-semibold text-foreground">{title}</p>
                <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
                  {tx(option.helpKey, option.help)}
                </p>
              </div>
            </div>
            <ToggleButton
              checked={checked}
              onChange={(enabled) => onChange(
                updateProviderRequestOption(option, enabled, form),
              )}
              ariaLabel={title}
              label={checked ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </div>
        );
      })}
    </div>
  );
}

function ProviderAdvancedOptions({
  fields,
  form,
  onChange,
  children,
}: {
  fields: ProviderAdvancedField[];
  form: ProviderForm;
  onChange: (value: Partial<ProviderForm>) => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const enabled = new Set(fields);
  const contentId = useId();
  if (enabled.size === 0 && !children) return null;

  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const thinkingStyleOptions = [
    { value: "", label: tx("settings.values.default", "Default") },
    { value: "thinking_type", label: "thinking_type" },
    { value: "enable_thinking", label: "enable_thinking" },
    { value: "reasoning_split", label: "reasoning_split" },
  ];

  return (
    <div className="space-y-1">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[48px] w-full items-center justify-between gap-4 px-3 py-2.5 text-left transition-colors hover:text-foreground"
      >
        <span className="text-[13px] font-medium text-foreground">
          {tx("settings.providers.advancedOptions", "Advanced options")}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>
      <DisclosureContent id={contentId} open={open}>
        <div className="space-y-3 py-3">
          {children}
          <div className="grid gap-3 md:grid-cols-2">
            {enabled.has("thinking_style") ? (
              <label className="block space-y-1.5">
                <span className="block px-3 text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.thinkingStyle", "Reasoning parameter format")}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 w-full justify-between rounded-full px-3 text-[13px]"
                    >
                      <span className="font-mono text-[12px]">
                        {thinkingStyleOptions.find(
                          (option) => option.value === form.thinkingStyle,
                        )?.label ?? form.thinkingStyle}
                      </span>
                      <ChevronDown
                        className="h-3.5 w-3.5 text-muted-foreground"
                        aria-hidden
                      />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="min-w-[220px]">
                    {thinkingStyleOptions.map((option) => (
                      <DropdownMenuItem
                        key={option.value || "default"}
                        onSelect={() => onChange({ thinkingStyle: option.value })}
                        className="font-mono text-[12px]"
                      >
                        {option.label}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </label>
            ) : null}
            {enabled.has("proxy") ? (
              <label className="block space-y-1.5 md:col-span-2">
                <span className="block px-3 text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.proxy", "Network proxy")}
                </span>
                <Input
                  value={form.proxy}
                  onChange={(event) => onChange({ proxy: event.target.value })}
                  placeholder="http://127.0.0.1:7890"
                  autoCapitalize="none"
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck={false}
                  className="h-9 rounded-full font-mono text-[12px]"
                />
              </label>
            ) : null}
            {enabled.has("region") ? (
              <label className="block space-y-1.5">
                <span className="block px-3 text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.region", "Region")}
                </span>
                <Input
                  value={form.region}
                  onChange={(event) => onChange({ region: event.target.value })}
                  placeholder="us-east-1"
                  autoCapitalize="none"
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck={false}
                  className="h-9 rounded-full font-mono text-[12px]"
                />
              </label>
            ) : null}
            {enabled.has("profile") ? (
              <label className="block space-y-1.5">
                <span className="block px-3 text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.profile", "AWS profile")}
                </span>
                <Input
                  value={form.profile}
                  onChange={(event) => onChange({ profile: event.target.value })}
                  placeholder="default"
                  autoCapitalize="none"
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck={false}
                  className="h-9 rounded-full font-mono text-[12px]"
                />
              </label>
            ) : null}
            <ProviderParameterFields fields={fields} form={form} onChange={onChange} />
          </div>
        </div>
      </DisclosureContent>

    </div>
  );
}

export function ProvidersSettings({
  settings,
  nanobotFeatures,
  featureAction,
  capabilityError,
  expandedProvider,
  providerForms,
  visibleProviderKeys,
  editingProviderKeys,
  providerSaving,
  showBrandLogos,
  remoteBrowserAccess,
  onToggleProvider,
  onToggleProviderKey,
  onToggleProviderKeyEditing,
  onChangeProviderForm,
  onSaveProvider,
  onCreateCustomProvider,
  onRemoveProvider,
  providerOperation,
  onProviderOAuthLogin,
  onProviderOAuthLogout,
}: {
  settings: SettingsPayload;
  nanobotFeatures: NanobotFeaturesPayload | null;
  featureAction: string | null;
  capabilityError: string | null;
  expandedProvider: string | null;
  providerForms: Record<string, ProviderForm>;
  visibleProviderKeys: Record<string, boolean>;
  editingProviderKeys: Record<string, boolean>;
  providerSaving: string | null;
  showBrandLogos: boolean;
  remoteBrowserAccess: boolean;
  onToggleProvider: (provider: string) => void;
  onToggleProviderKey: (provider: string) => void;
  onToggleProviderKeyEditing: (provider: string) => void;
  onChangeProviderForm: (provider: string, value: Partial<ProviderForm>) => void;
  onSaveProvider: (provider: string) => void;
  onCreateCustomProvider: (draft: CustomProviderDraft) => Promise<boolean>;
  onRemoveProvider: (provider: string) => void;
  providerOperation?: ProviderOperation | null;
  onProviderOAuthLogin: (provider: string) => void;
  onProviderOAuthLogout: (provider: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [creatingCustomProvider, setCreatingCustomProvider] = useState(false);
  const [addingProvider, setAddingProvider] = useState(false);
  const [providerToAdd, setProviderToAdd] = useState<string | null>(null);
  const [providerSearch, setProviderSearch] = useState("");
  const [customProviderKeyVisible, setCustomProviderKeyVisible] = useState(false);
  const [customProviderDraft, setCustomProviderDraft] = useState<CustomProviderDraft>(
    emptyCustomProviderDraft,
  );
  const configuredProviders = settings.providers.filter((provider) => provider.configured);
  const unconfiguredProviders = useMemo(
    () =>
      settings.providers.filter(
        (provider) => !provider.configured && provider.name !== "custom",
      ),
    [settings.providers],
  );
  const selectedUnconfiguredProvider =
    unconfiguredProviders.find((provider) => provider.name === expandedProvider) ?? null;
  const customProviderSaving = providerSaving === CUSTOM_PROVIDER_CREATION_KEY;
  const selectedProviderToAdd = settings.providers.find((provider) => provider.name === providerToAdd);
  useEffect(() => {
    // Existing save/cancel actions own expandedProvider; close the add flow when they finish.
    if (addingProvider && providerToAdd && expandedProvider !== providerToAdd) {
      setAddingProvider(false);
      setProviderToAdd(null);
    }
  }, [addingProvider, providerToAdd, expandedProvider]);
  const closeAddProvider = () => {
    setAddingProvider(false);
    setProviderToAdd(null);
    setCreatingCustomProvider(false);
    setCustomProviderDraft(emptyCustomProviderDraft());
    setCustomProviderKeyVisible(false);
    if (providerToAdd && expandedProvider === providerToAdd) onToggleProvider(providerToAdd);
  };
  const backToProviderPicker = () => {
    setProviderToAdd(null);
    setCreatingCustomProvider(false);
    if (providerToAdd && expandedProvider === providerToAdd) onToggleProvider(providerToAdd);
  };
  const toggleProvider = (providerName: string) => {
    setCreatingCustomProvider(false);
    onToggleProvider(providerName);
  };
  const beginCustomProviderCreation = () => {
    if (expandedProvider) onToggleProvider(expandedProvider);
    setCustomProviderDraft(emptyCustomProviderDraft());
    setCustomProviderKeyVisible(false);
    setCreatingCustomProvider(true);
  };
  const cancelCustomProviderCreation = () => {
    setCreatingCustomProvider(false);
    setCustomProviderDraft(emptyCustomProviderDraft());
    setCustomProviderKeyVisible(false);
    setAddingProvider(false);
  };
  const saveCustomProvider = async () => {
    if (customProviderSaving) return;
    if (await onCreateCustomProvider(customProviderDraft)) {
      cancelCustomProviderCreation();
    }
  };
  const renderProviderRow = (provider: SettingsPayload["providers"][number], contentOnly = false) => {
    const expanded = expandedProvider === provider.name && !addingProvider;
    const form = providerForms[provider.name] ?? providerFormFromRow(provider);
    const saving = providerSaving === provider.name;
    const isOauthProvider = provider.auth_type === "oauth";
    const oauthAuthenticated = provider.oauth_authenticated === true;
    const supportsOauthAdvancedSettings =
      isOauthProvider && OAUTH_PROXY_PROVIDERS.has(provider.name);
    const keyVisible = !!visibleProviderKeys[provider.name];
    const editingKey = !provider.configured || !!editingProviderKeys[provider.name];
    const apiKeyRequired = provider.api_key_required ?? true;
    const apiKey = form.apiKey.trim();
    const apiBase = form.apiBase.trim();
    const advancedFields = provider.advanced_fields ?? [];
    const oauthSettingsDirty = isOauthProvider && (
      (provider.enabled === false && oauthAuthenticated)
      || form.proxy.trim() !== (provider.proxy ?? "").trim()
      || form.extraBody.trim() !== providerJsonValue(provider.extra_body).trim()
    );
    const oauthSettingsSaving = saving && providerOperation?.action === "save";
    const oauthActionBusy = saving && (providerOperation?.action === "login" || providerOperation?.action === "logout");
    const missingRequiredApiKey = !isOauthProvider && apiKeyRequired && !provider.configured && !apiKey;
    const hasOptionalProviderSetting = Boolean(
      apiKey
      || apiBase
      || form.proxy.trim()
      || form.extraHeaders.trim()
      || form.extraBody.trim()
      || form.extraQuery.trim()
      || form.thinkingStyle.trim()
      || form.region.trim()
      || form.profile.trim(),
    );
    const missingOptionalCredential =
      !isOauthProvider
      && !apiKeyRequired
      && !provider.configured
      && !hasOptionalProviderSetting;
    const removeAction = provider.configured ? (
      <RemoveActionButton className="mr-auto" disabled={saving}
        onClick={() => onRemoveProvider(provider.name)}>
        {tx("settings.providers.removeProvider", "Remove")}
      </RemoveActionButton>
    ) : null;
    const supportName = provider.name === "bedrock"
      ? "bedrock"
      : provider.name === "azure_openai"
        ? "azure"
        : null;
    const supportFeature = supportName
      ? (nanobotFeatures?.features ?? []).find((feature) => feature.name === supportName)
      : null;
    const content = (
      <>
            {supportFeature && !supportFeature.installed ? (
              <CapabilityInstallNotice
                title={tx("settings.capabilities.providerSupport", "Provider dependencies")}
                description={tx(
                  "settings.capabilities.providerInstallOnSave",
                  "Required packages will be installed automatically when you save this provider.",
                )}
                installing={featureAction === `enable:${supportName}`}
              />
            ) : null}
            {supportName && capabilityError ? (
              <p className="text-[12px] text-destructive">{capabilityError}</p>
            ) : null}
            {isOauthProvider ? (
              <>
                <div className="flex flex-col gap-3 rounded-floating border border-border/45 bg-background/75 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-[13px] font-semibold text-foreground">
                      {tx("settings.oauth.authentication", "OAuth authentication")}
                    </p>
                    <p className="mt-1 text-[12px] text-muted-foreground">
                      {oauthAuthenticated
                        ? t("settings.oauth.signedInAs", {
                            account: provider.oauth_account || provider.label,
                            defaultValue: "Signed in as {{account}}",
                          })
                        : provider.name === "openai_codex" && remoteBrowserAccess
                          ? tx(
                              "settings.oauth.codexRemoteSignInHelp",
                              "Sign in through this browser, then paste the full localhost callback URL back into nanobot.",
                            )
                          : provider.name === "xai_grok" && remoteBrowserAccess
                          ? tx(
                              "settings.oauth.remoteSignInHelp",
                              "Select Sign in to open xAI on your computer, then paste the authorization code shown after login.",
                            )
                          : tx("settings.oauth.signInHelp", "Sign in from this device; no API key is stored in config.")}
                    </p>
                  </div>
                  <div className="flex shrink-0 justify-end gap-2">
                    {oauthAuthenticated ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => onProviderOAuthLogout(provider.name)}
                        disabled={saving}
                        className="rounded-full"
                      >
                        {tx("settings.oauth.signOut", "Sign out")}
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onProviderOAuthLogin(provider.name)}
                      disabled={saving || oauthSettingsDirty || !provider.oauth_login_supported}
                      title={
                        oauthSettingsDirty
                          ? tx(
                              "settings.providers.saveAdvancedBeforeSignIn",
                              "Save advanced changes before signing in.",
                            )
                          : undefined
                      }
                      className="rounded-full"
                    >
                      {oauthActionBusy ? (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                      ) : null}
                      {oauthActionBusy
                        ? tx("settings.oauth.signingIn", "Signing in...")
                        : oauthAuthenticated
                          ? tx("settings.oauth.signInAgain", "Sign in again")
                          : tx("settings.oauth.signIn", "Sign in")}
                    </Button>
                  </div>
                </div>
                <ProviderRequestOptions
                  providerName={provider.name}
                  apiConfigurable={provider.provider_api_configurable === true}
                  form={form}
                  onChange={(value) => onChangeProviderForm(provider.name, value)}
                />
                {supportsOauthAdvancedSettings ? (
                  <ProviderAdvancedOptions
                    fields={advancedFields}
                    form={form}
                    onChange={(value) => onChangeProviderForm(provider.name, value)}
                  />
                ) : null}
                <div className="flex flex-wrap items-center justify-end gap-2 py-3">
                  {removeAction}
                  <Button size="sm" variant="ghost" onClick={() => toggleProvider(provider.name)}
                    disabled={saving} className="rounded-full">
                    {t("settings.actions.cancel")}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => onSaveProvider(provider.name)}
                    disabled={saving || !oauthSettingsDirty} className="rounded-full">
                    {oauthSettingsSaving ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
                    {oauthSettingsSaving
                      ? t("settings.actions.saving")
                      : !provider.configured && oauthAuthenticated
                        ? tx("settings.providers.addProvider", "Add provider")
                        : tx("settings.providers.saveProvider", "Save provider")}
                  </Button>
                </div>
              </>
            ) : (
              <>
                {provider.is_custom ? (
                  <label className="block space-y-1.5">
                    <span className="block px-3 text-[12px] font-medium text-muted-foreground">
                      {tx("settings.providers.customProviderName", "Provider name")}
                    </span>
                    <Input
                      value={form.displayName}
                      onChange={(event) =>
                        onChangeProviderForm(provider.name, { displayName: event.target.value })
                      }
                      className="h-9 rounded-full text-[13px]"
                    />
                  </label>
                ) : null}
                <label className="block space-y-1.5">
                  <span className="block px-3 text-[12px] font-medium text-muted-foreground">
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
                          className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground hover:text-foreground"
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
                          className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground hover:text-foreground"
                        >
                          <Pencil className="h-3.5 w-3.5" aria-hidden />
                        </Button>
                      </>
                    )}
                  </div>
                </label>
                <label className="block space-y-1.5">
                  <span className="block px-3 text-[12px] font-medium text-muted-foreground">
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
                <ProviderRequestOptions
                  providerName={provider.name}
                  apiConfigurable={provider.provider_api_configurable === true}
                  form={form}
                  onChange={(value) => onChangeProviderForm(provider.name, value)}
                />
                <ProviderAdvancedOptions
                  fields={advancedFields}
                  form={form}
                  onChange={(value) => onChangeProviderForm(provider.name, value)}
                >
                  {provider.provider_api_configurable && (provider.name === "openai" ? (
                    <ModelAPIControl
                      provider={provider}
                      title={t("settings.providers.defaultAPI")}
                      description={t("settings.providers.openaiDefaultAPIDescription")}
                      value={form.api}
                      onChange={(api) => onChangeProviderForm(provider.name, { api })}
                    />
                  ) : (
                    <ProviderAPIControl
                      value={form.api}
                      onChange={(api) => onChangeProviderForm(provider.name, { api })}
                    />
                  ))}
                </ProviderAdvancedOptions>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {removeAction}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => toggleProvider(provider.name)}
                    className="rounded-full"
                  >
                    {t("settings.actions.cancel")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onSaveProvider(provider.name)}
                    disabled={
                      saving
                      || missingRequiredApiKey
                      || missingOptionalCredential
                      || (provider.is_custom && !form.displayName.trim())
                    }
                    className="rounded-full"
                  >
                    {saving
                      ? t("settings.actions.saving")
                      : tx("settings.providers.saveProvider", "Save provider")}
                  </Button>
                </div>
              </>
            )}
      </>
    );
    if (contentOnly) return content;
    return (
      <Dialog key={provider.name} open={expanded} onOpenChange={(open) => {
        if (open !== expanded) toggleProvider(provider.name);
      }}>
        <DialogTrigger asChild>
          <button type="button" aria-label={provider.label}
            className="settings-list-row flex w-full items-center justify-between gap-4 py-2.5 text-left transition-colors settings-hover">
            <span className="flex min-w-0 items-center gap-3">
              <ProviderIcon provider={provider.name} showBrandLogos={showBrandLogos} />
              <span className="truncate text-[14px] font-medium leading-5 text-foreground">{provider.label}</span>
            </span>
            <span className="shrink-0 px-2 py-1 text-[13px] font-normal leading-5 text-muted-foreground">{t("settings.configure")}</span>
          </button>
        </DialogTrigger>
        {expanded ? <DialogContent aria-describedby={undefined} className="max-h-[85dvh] w-[min(calc(100vw-2rem),40rem)] max-w-none overflow-y-auto">
          <DialogHeader><DialogTitle>{provider.label}</DialogTitle></DialogHeader>
          {content}
        </DialogContent> : null}
      </Dialog>
    );
  };
  const customProviderForm = creatingCustomProvider ? (
      <div className="space-y-3">
        <label className="block space-y-1.5">
          <span className="block px-3 text-[12px] font-medium text-muted-foreground">
            {tx("settings.providers.customProviderName", "Provider name")}
          </span>
          <Input
            autoFocus
            value={customProviderDraft.name}
            onChange={(event) =>
              setCustomProviderDraft((current) => ({
                ...current,
                name: event.target.value,
              }))
            }
            placeholder={tx(
              "settings.providers.customProviderNamePlaceholder",
              "My model provider",
            )}
            className="h-9 rounded-full text-[13px]"
          />
        </label>
        <label className="block space-y-1.5">
          <span className="block px-3 text-[12px] font-medium text-muted-foreground">
            {t("settings.byok.apiBase")}
          </span>
          <Input
            value={customProviderDraft.apiBase}
            onChange={(event) =>
              setCustomProviderDraft((current) => ({
                ...current,
                apiBase: event.target.value,
              }))
            }
            placeholder="https://api.example.com/v1"
            autoCapitalize="none"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            className="h-9 rounded-full text-[13px]"
          />
        </label>
        <label className="block space-y-1.5">
          <span className="block px-3 text-[12px] font-medium text-muted-foreground">
            {t("settings.byok.apiKey")}
          </span>
          <div className="relative">
            <Input
              type={customProviderKeyVisible ? "text" : "password"}
              value={customProviderDraft.apiKey}
              onChange={(event) =>
                setCustomProviderDraft((current) => ({
                  ...current,
                  apiKey: event.target.value,
                }))
              }
              placeholder={t("settings.byok.apiKeyPlaceholder")}
              autoCapitalize="none"
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
              className="h-9 rounded-full pr-11 text-[13px]"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setCustomProviderKeyVisible((visible) => !visible)}
              aria-label={
                customProviderKeyVisible
                  ? t("settings.byok.hideApiKey")
                  : t("settings.byok.showApiKey")
              }
              className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground hover:text-foreground"
            >
              {customProviderKeyVisible ? (
                <EyeOff className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <Eye className="h-3.5 w-3.5" aria-hidden />
              )}
            </Button>
          </div>
        </label>
        <ProviderAdvancedOptions
          fields={CUSTOM_PROVIDER_ADVANCED_FIELDS}
          form={customProviderDraft}
          onChange={(value) =>
            setCustomProviderDraft((current) => ({ ...current, ...value }))
          }
        >
          {settings.provider_api_configuration_supported && (
            <ProviderAPIControl
              value={customProviderDraft.api}
              onChange={(api) => setCustomProviderDraft((current) => ({ ...current, api }))}
            />
          )}
        </ProviderAdvancedOptions>
        <div className="flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={cancelCustomProviderCreation}
            disabled={customProviderSaving}
            className="rounded-full"
          >
            {t("settings.actions.cancel")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={saveCustomProvider}
            disabled={
              customProviderSaving ||
              !customProviderDraft.name.trim() ||
              !customProviderDraft.apiBase.trim()
            }
            className="rounded-full"
          >
            {customProviderSaving
              ? t("settings.actions.saving")
              : tx("settings.providers.saveProvider", "Save provider")}
          </Button>
        </div>
      </div>
  ) : null;
  return (
    <div className="space-y-6">
      <section>
        <SettingsSectionTitle>
          {tx("settings.providers.title", "Model providers")}
        </SettingsSectionTitle>
        <SettingsGroup>
          {configuredProviders.map((provider) => renderProviderRow(provider))}
          {selectedUnconfiguredProvider && !addingProvider
            ? renderProviderRow(selectedUnconfiguredProvider)
            : null}
          <ProviderSetupPanel
            open={addingProvider}
            onOpenChange={(open) => {
              if (open) {
                setProviderToAdd(null);
                setProviderSearch("");
                setAddingProvider(true);
              } else closeAddProvider();
            }}
            title={creatingCustomProvider
              ? tx("settings.providers.customProvider", "Custom provider")
              : selectedProviderToAdd?.label ?? tx("settings.providers.addProvider", "Add provider")}
            onBack={creatingCustomProvider || selectedProviderToAdd ? backToProviderPicker : undefined}
            trigger={
              <SettingsAddButton>
                {tx("settings.providers.addProvider", "Add provider")}
              </SettingsAddButton>
            }
          >
            {creatingCustomProvider || selectedProviderToAdd ? (
              <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-5 pb-5">
                {creatingCustomProvider ? customProviderForm : renderProviderRow(selectedProviderToAdd!, true)}
              </div>
            ) : (
              <ProviderSearchList providers={unconfiguredProviders} showBrandLogos={showBrandLogos}
                query={providerSearch} onQueryChange={setProviderSearch}
                onSelect={(name) => {
                  setProviderToAdd(name);
                  onToggleProvider(name);
                }}
                onCustom={beginCustomProviderCreation} onClose={closeAddProvider} />
            )}
          </ProviderSetupPanel>
        </SettingsGroup>
      </section>
    </div>
  );
}

function ProviderSetupPanel({ open, onOpenChange, title, trigger, onBack, children }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  trigger: ReactNode;
  onBack?: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const mobile = useMediaQuery("(max-width: 639px)");
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const configuring = Boolean(onBack);
  useEffect(() => {
    if (configuring) container?.focus({ preventScroll: true });
  }, [configuring, container]);
  const content = <>
    <div className="flex h-16 shrink-0 items-center gap-2 px-5 pr-12">
      {onBack ? <Button type="button" variant="ghost" size="icon" onClick={onBack}
        aria-label={t("settings.providers.backToProviders", { defaultValue: "Back to providers" })}
        className="-ml-2 h-9 w-9 shrink-0 rounded-full">
        <ChevronLeft className="h-4 w-4" aria-hidden />
      </Button> : null}
      <DialogTitle className="truncate text-base font-semibold">{title}</DialogTitle>
    </div>
    {children}
  </>;
  const focusOnOpen = (event: Event) => {
    event.preventDefault();
    const target = !mobile ? container?.querySelector<HTMLInputElement>("input") : null;
    (target ?? container)?.focus({ preventScroll: true });
  };
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogTrigger asChild>{trigger}</DialogTrigger>
    {mobile ? <SheetContent side="bottom" ref={setContainer} aria-describedby={undefined}
      onOpenAutoFocus={focusOnOpen}
      className={cn("mx-auto max-h-[85dvh] max-w-md gap-0 overflow-hidden rounded-t-3xl pb-[env(safe-area-inset-bottom)] outline-none", !configuring && "h-[min(36rem,85dvh)]")}
      closeButtonClassName="grid h-9 w-9 place-items-center right-3 top-3 rounded-full">
      <FloatingPortalContext.Provider value={container}>{content}</FloatingPortalContext.Provider>
    </SheetContent> : <DialogContent ref={setContainer} aria-describedby={undefined}
      onOpenAutoFocus={focusOnOpen}
      className={cn("flex max-h-[85dvh] w-[min(28rem,calc(100vw-2rem))] max-w-none flex-col gap-0 overflow-hidden p-0 outline-none", !configuring && "h-[min(32rem,85dvh)]")}>
      {content}
    </DialogContent>}
  </Dialog>;
}

