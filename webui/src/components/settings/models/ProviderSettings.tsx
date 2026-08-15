import { useMemo, useState, type ReactNode } from "react";
import {
  ChevronDown,
  Clipboard,
  Eye,
  EyeOff,
  ExternalLink,
  Globe2,
  Hexagon,
  Loader2,
  Pencil,
  Plus,
  RotateCcw,
  Zap,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { PROVIDER_ICONS } from "@/components/settings/shared/ModelControls";
import {
  CapabilityInstallNotice,
  SettingsGroup,
  SettingsSectionTitle,
} from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { providerBrand } from "@/lib/provider-brand";
import { cn } from "@/lib/utils";
import type {
  NanobotFeaturesPayload,
  ProviderOAuthAuthorizationRequired,
  SettingsPayload,
} from "@/lib/types";

type ProviderApiType = "auto" | "chat_completions" | "responses";
type ProviderAdvancedField = NonNullable<
  SettingsPayload["providers"][number]["advanced_fields"]
>[number];
export type ProviderForm = {
  displayName: string;
  apiKey: string;
  apiBase: string;
  apiType: ProviderApiType;
  proxy: string;
  extraHeaders: string;
  extraBody: string;
  extraQuery: string;
  thinkingStyle: string;
  region: string;
  profile: string;
};
export type CustomProviderDraft = ProviderForm & { name: string };
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
  deepseek: [{
    kind: "hosted_tool",
    titleKey: "settings.providers.capabilityDeepSeekSearch",
    title: "DeepSeek web search",
    helpKey: "settings.providers.capabilityDeepSeekSearchHelp",
    help: "Let DeepSeek V4 Flash search the web through its Responses API. Search activity appears in chat.",
    toolType: "web_search",
    defaultEnabled: true,
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
export const CUSTOM_PROVIDER_CREATION_KEY = "__custom_provider__";
const CUSTOM_PROVIDER_ADVANCED_FIELDS: ProviderAdvancedField[] = [
  "extra_headers",
  "extra_body",
  "extra_query",
  "proxy",
  "thinking_style",
];

function providerJsonValue(value: Record<string, unknown> | null | undefined): string {
  return value && Object.keys(value).length > 0 ? JSON.stringify(value, null, 2) : "";
}

function parseProviderExtraBody(value: string): Record<string, unknown> | null {
  if (!value.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

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
  const extraBody = { ...(parseProviderExtraBody(form.extraBody) ?? {}) };
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
      ? { apiType: "responses" as const }
      : {}),
  };
}

export function providerFormFromRow(
  provider: SettingsPayload["providers"][number],
): ProviderForm {
  return {
    displayName: provider.is_custom ? provider.label : "",
    apiKey: "",
    apiBase: provider.api_base ?? provider.default_api_base ?? "",
    apiType: provider.api_type ?? "auto",
    proxy: provider.proxy ?? "",
    extraHeaders: providerJsonValue(provider.extra_headers),
    extraBody: providerJsonValue(provider.extra_body),
    extraQuery: providerJsonValue(provider.extra_query),
    thinkingStyle: provider.thinking_style ?? "",
    region: provider.region ?? "",
    profile: provider.profile ?? "",
  };
}

function emptyCustomProviderDraft(): CustomProviderDraft {
  return {
    name: "",
    displayName: "",
    apiKey: "",
    apiBase: "",
    apiType: "auto",
    proxy: "",
    extraHeaders: "",
    extraBody: "",
    extraQuery: "",
    thinkingStyle: "",
    region: "",
    profile: "",
  };
}

const OPENAI_API_TYPE_OPTIONS: Array<{ value: ProviderApiType; label: string }> = [
  { value: "auto", label: "Auto" },
  { value: "chat_completions", label: "Chat Completions" },
  { value: "responses", label: "Responses" },
];

const LOCAL_UNCONFIGURED_PROVIDER_ORDER = new Map(
  ["vllm", "ollama", "lm_studio", "atomic_chat", "ovms"].map((name, index) => [
    name,
    index,
  ]),
);

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
              {expectsCallbackUrl
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
              {expectsCallbackUrl && remoteBrowserAccess
                ? t("settings.oauth.pasteCallbackToContinue")
                : t("settings.oauth.waitingForCallback")}
            </span>
          </div>
          <div className="space-y-2">
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
          </div>
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
              {expectsCallbackUrl
                ? t("settings.oauth.openChatGPT")
                : t("settings.oauth.signIn")}
            </Button>
            <Button type="submit" disabled={!authorizationResponse.trim() || completing}>
              {completing ? t("settings.oauth.signingIn") : t("settings.oauth.finishSignIn")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ProviderRequestOptions({
  providerName,
  form,
  onChange,
}: {
  providerName: string;
  form: ProviderForm;
  onChange: (value: Partial<ProviderForm>) => void;
}) {
  const { t } = useTranslation();
  const options = PROVIDER_REQUEST_OPTIONS[providerName] ?? [];
  if (options.length === 0) return null;
  const extraBody = parseProviderExtraBody(form.extraBody) ?? {};

  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });

  return (
    <div className="overflow-hidden rounded-floating border border-border/45 bg-background/75">
      {options.map((option, index) => {
        const title = tx(option.titleKey, option.title);
        const Icon = option.kind === "priority" ? Zap : Globe2;
        const checked = providerRequestOptionEnabled(option, extraBody);
        return (
          <div
            key={option.titleKey}
            className={cn(
              "flex items-center justify-between gap-4 px-4 py-3",
              index > 0 && "border-t border-border/45",
            )}
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
  footer,
}: {
  fields: ProviderAdvancedField[];
  form: ProviderForm;
  onChange: (value: Partial<ProviderForm>) => void;
  footer?: ReactNode;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const enabled = new Set(fields);
  if (enabled.size === 0) return null;

  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const thinkingStyleOptions = [
    { value: "", label: tx("settings.values.default", "Default") },
    { value: "thinking_type", label: "thinking_type" },
    { value: "enable_thinking", label: "enable_thinking" },
    { value: "reasoning_split", label: "reasoning_split" },
  ];

  return (
    <div className="border-y border-border/45">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[48px] w-full items-center justify-between gap-4 px-1 py-2.5 text-left transition-colors hover:text-foreground"
      >
        <span className="text-[13px] font-medium text-foreground">
          {tx("settings.providers.advancedOptions", "Advanced options")}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>
      {open ? (
        <div className="border-t border-border/45 py-3">
          <div className="grid gap-3 md:grid-cols-2">
            {enabled.has("api_type") ? (
              <label className="block space-y-1.5">
                <span className="text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.apiType", "API type")}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 w-full justify-between rounded-full px-3 text-[13px]"
                    >
                      <span>
                        {OPENAI_API_TYPE_OPTIONS.find(
                          (option) => option.value === form.apiType,
                        )?.label ?? form.apiType}
                      </span>
                      <ChevronDown
                        className="h-3.5 w-3.5 text-muted-foreground"
                        aria-hidden
                      />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="min-w-[220px]">
                    {OPENAI_API_TYPE_OPTIONS.map((option) => (
                      <DropdownMenuItem
                        key={option.value}
                        onSelect={() => onChange({ apiType: option.value })}
                      >
                        {option.label}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </label>
            ) : null}
            {enabled.has("thinking_style") ? (
              <label className="block space-y-1.5">
                <span className="text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.thinkingStyle", "Thinking style")}
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
                <span className="text-[12px] font-medium text-muted-foreground">
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
                <span className="text-[12px] font-medium text-muted-foreground">
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
                <span className="text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.profile", "Profile")}
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
            {enabled.has("extra_headers") ? (
              <label className="block min-w-0 space-y-1.5">
                <span className="text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.extraHeaders", "Extra headers")}
                </span>
                <Textarea
                  value={form.extraHeaders}
                  onChange={(event) => onChange({ extraHeaders: event.target.value })}
                  placeholder={'{"X-Header":"value"}'}
                  spellCheck={false}
                  className="min-h-[88px] resize-y bg-background font-mono text-[12px]"
                />
              </label>
            ) : null}
            {enabled.has("extra_query") ? (
              <label className="block min-w-0 space-y-1.5">
                <span className="text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.extraQuery", "Extra query")}
                </span>
                <Textarea
                  value={form.extraQuery}
                  onChange={(event) => onChange({ extraQuery: event.target.value })}
                  placeholder={'{"api-version":"2024-02-01"}'}
                  spellCheck={false}
                  className="min-h-[88px] resize-y bg-background font-mono text-[12px]"
                />
              </label>
            ) : null}
            {enabled.has("extra_body") ? (
              <label className="block min-w-0 space-y-1.5 md:col-span-2">
                <span className="text-[12px] font-medium text-muted-foreground">
                  {tx("settings.providers.extraBody", "Extra body")}
                </span>
                <Textarea
                  value={form.extraBody}
                  onChange={(event) => onChange({ extraBody: event.target.value })}
                  placeholder={'{"service_tier":"priority"}'}
                  spellCheck={false}
                  className="min-h-[96px] resize-y bg-background font-mono text-[12px]"
                />
              </label>
            ) : null}
          </div>
        </div>
      ) : null}
      {footer ? (
        <div className="flex items-center justify-end gap-2 border-t border-border/45 py-3">
          {footer}
        </div>
      ) : null}
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
  onProviderOAuthLogin,
  onProviderOAuthLogout,
  imageProviderRestartPending,
  onRestart,
  isRestarting,
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
  onProviderOAuthLogin: (provider: string) => void;
  onProviderOAuthLogout: (provider: string) => void;
  imageProviderRestartPending: boolean;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [creatingCustomProvider, setCreatingCustomProvider] = useState(false);
  const [customProviderKeyVisible, setCustomProviderKeyVisible] = useState(false);
  const [customProviderDraft, setCustomProviderDraft] = useState<CustomProviderDraft>(
    emptyCustomProviderDraft,
  );
  const configuredProviders = settings.providers.filter((provider) => provider.configured);
  const unconfiguredProviders = useMemo(
    () =>
      orderUnconfiguredProviders(
        settings.providers.filter(
          (provider) => !provider.configured && provider.name !== "custom",
        ),
      ),
    [settings.providers],
  );
  const selectedUnconfiguredProvider =
    unconfiguredProviders.find((provider) => provider.name === expandedProvider) ?? null;
  const customProviderSaving = providerSaving === CUSTOM_PROVIDER_CREATION_KEY;
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
  };
  const saveCustomProvider = async () => {
    if (customProviderSaving) return;
    if (await onCreateCustomProvider(customProviderDraft)) {
      cancelCustomProviderCreation();
    }
  };
  const renderProviderRow = (provider: SettingsPayload["providers"][number]) => {
    const expanded = expandedProvider === provider.name;
    const form = providerForms[provider.name] ?? providerFormFromRow(provider);
    const saving = providerSaving === provider.name;
    const isOauthProvider = provider.auth_type === "oauth";
    const supportsOauthAdvancedSettings =
      isOauthProvider && OAUTH_PROXY_PROVIDERS.has(provider.name);
    const keyVisible = !!visibleProviderKeys[provider.name];
    const editingKey = !provider.configured || !!editingProviderKeys[provider.name];
    const apiKeyRequired = provider.api_key_required ?? true;
    const apiKey = form.apiKey.trim();
    const apiBase = form.apiBase.trim();
    const advancedFields = provider.advanced_fields ?? [];
    const oauthSettingsDirty = isOauthProvider && (
      form.proxy.trim() !== (provider.proxy ?? "").trim()
      || form.extraBody.trim() !== providerJsonValue(provider.extra_body).trim()
    );
    const oauthSettingsSaving = saving && oauthSettingsDirty;
    const oauthActionBusy = saving && !oauthSettingsSaving;
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
    const supportName = provider.name === "bedrock"
      ? "bedrock"
      : provider.name === "azure_openai"
        ? "azure"
        : null;
    const supportFeature = supportName
      ? (nanobotFeatures?.features ?? []).find((feature) => feature.name === supportName)
      : null;
    return (
      <div key={provider.name} className="divide-y divide-border/45">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => toggleProvider(provider.name)}
          className="flex min-h-[70px] w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-muted/35 sm:px-5"
        >
          <span className="flex min-w-0 items-center gap-3">
            <ProviderIcon
              provider={provider.name}
              showBrandLogos={showBrandLogos}
            />
            <span className="min-w-0">
              <span className="block truncate text-[15px] font-semibold leading-5 text-foreground">
                {provider.label}
              </span>
              {provider.api_base ? (
                <span className="block truncate text-[12px] text-muted-foreground">
                  {provider.api_base}
                </span>
              ) : null}
            </span>
          </span>
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
              expanded && "rotate-180",
            )}
            aria-hidden
          />
        </button>

        {expanded ? (
          <div className="space-y-3 bg-muted/18 px-4 py-4 sm:px-5">
            {supportFeature && !supportFeature.installed ? (
              <CapabilityInstallNotice
                title={tx("settings.capabilities.providerSupport", "Provider support")}
                description={tx(
                  "settings.capabilities.providerInstallOnSave",
                  "Required support will be installed automatically when you save this provider.",
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
                      {provider.configured
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
                    {provider.configured ? (
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
                        : provider.configured
                          ? tx("settings.oauth.signInAgain", "Sign in again")
                          : tx("settings.oauth.signIn", "Sign in")}
                    </Button>
                  </div>
                </div>
                <ProviderRequestOptions
                  providerName={provider.name}
                  form={form}
                  onChange={(value) => onChangeProviderForm(provider.name, value)}
                />
                {supportsOauthAdvancedSettings ? (
                  <ProviderAdvancedOptions
                    fields={advancedFields}
                    form={form}
                    onChange={(value) => onChangeProviderForm(provider.name, value)}
                    footer={
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => toggleProvider(provider.name)}
                          disabled={saving}
                          className="rounded-full"
                        >
                          {t("settings.actions.cancel")}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => onSaveProvider(provider.name)}
                          disabled={saving || !oauthSettingsDirty}
                          className="rounded-full"
                        >
                          {oauthSettingsSaving ? (
                            <Loader2
                              className="mr-1.5 h-3.5 w-3.5 animate-spin"
                              aria-hidden
                            />
                          ) : null}
                          {oauthSettingsSaving
                            ? t("settings.actions.saving")
                            : tx("settings.providers.saveProvider", "Save provider")}
                        </Button>
                      </>
                    }
                  />
                ) : null}
              </>
            ) : (
              <>
                {provider.is_custom ? (
                  <label className="block space-y-1.5">
                    <span className="text-[12px] font-medium text-muted-foreground">
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
                <ProviderRequestOptions
                  providerName={provider.name}
                  form={form}
                  onChange={(value) => onChangeProviderForm(provider.name, value)}
                />
                <ProviderAdvancedOptions
                  fields={advancedFields}
                  form={form}
                  onChange={(value) => onChangeProviderForm(provider.name, value)}
                />
                <div className="flex items-center justify-end gap-2">
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
          </div>
        ) : null}
      </div>
    );
  };
  const customProviderForm = creatingCustomProvider ? (
    <div className="divide-y divide-border/45">
      <button
        type="button"
        aria-expanded
        onClick={cancelCustomProviderCreation}
        className="flex min-h-[70px] w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-muted/35 sm:px-5"
      >
        <span className="flex min-w-0 items-center gap-3">
          <ProviderIcon provider="custom" showBrandLogos={showBrandLogos} />
          <span className="truncate text-[15px] font-semibold text-foreground">
            {tx("settings.providers.customProvider", "Custom provider")}
          </span>
        </span>
        <ChevronDown
          className="h-4 w-4 shrink-0 rotate-180 text-muted-foreground"
          aria-hidden
        />
      </button>
      <div className="space-y-3 bg-muted/18 px-4 py-4 sm:px-5">
        <label className="block space-y-1.5">
          <span className="text-[12px] font-medium text-muted-foreground">
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
          <span className="text-[12px] font-medium text-muted-foreground">
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
          <span className="text-[12px] font-medium text-muted-foreground">
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
              className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
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
        />
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
    </div>
  ) : null;
  return (
    <div className="space-y-6">
      {imageProviderRestartPending && onRestart ? (
        <div className="flex min-h-[48px] items-center justify-between gap-3 border-y border-border/55 py-3">
          <p className="text-[13px] leading-5 text-muted-foreground">
            {tx("settings.status.imageProviderRestart", "Provider support changed. Restart when ready.")}
          </p>
          <div className="shrink-0">
            <Button
              size="sm"
              variant="ghost"
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
          </div>
        </div>
      ) : null}
      <section>
        <SettingsSectionTitle>
          {tx("settings.providers.title", "Model providers")}
        </SettingsSectionTitle>
        <SettingsGroup>
          {configuredProviders.map(renderProviderRow)}
          {selectedUnconfiguredProvider
            ? renderProviderRow(selectedUnconfiguredProvider)
            : null}
          {customProviderForm}
          {!expandedProvider && !creatingCustomProvider ? (
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="group flex min-h-[70px] w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-muted/35 sm:px-5"
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-control bg-muted text-muted-foreground">
                      <Plus className="h-5 w-5" aria-hidden />
                    </span>
                    <span className="truncate text-[15px] font-semibold text-foreground">
                      {tx(
                        "settings.providers.addOwnProvider",
                        "Add your own model provider",
                      )}
                    </span>
                  </span>
                  <ChevronDown
                    className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
                    aria-hidden
                  />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                sideOffset={8}
                className="max-h-[24rem] w-[380px] max-w-[calc(100vw-2rem)] overflow-y-auto scrollbar-thin scrollbar-track-transparent"
              >
                <DropdownMenuItem
                  onSelect={beginCustomProviderCreation}
                  className="flex min-h-[54px] cursor-default items-center gap-3 px-2.5 py-2 focus:bg-muted/85 focus:text-foreground"
                >
                  <ProviderIcon provider="custom" showBrandLogos={showBrandLogos} />
                  <span className="truncate text-[13px] font-medium">
                    {tx("settings.providers.customProvider", "Custom provider")}
                  </span>
                </DropdownMenuItem>
                {unconfiguredProviders.length > 0 ? <DropdownMenuSeparator /> : null}
                {unconfiguredProviders.map((provider) => (
                  <DropdownMenuItem
                    key={provider.name}
                    onSelect={() => {
                      setCreatingCustomProvider(false);
                      if (expandedProvider !== provider.name) {
                        onToggleProvider(provider.name);
                      }
                    }}
                    className="flex min-h-[54px] cursor-default items-center gap-3 px-2.5 py-2 focus:bg-muted/85 focus:text-foreground"
                  >
                    <ProviderIcon
                      provider={provider.name}
                      showBrandLogos={showBrandLogos}
                    />
                    <span className="truncate text-[13px] font-medium">
                      {provider.label}
                    </span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </SettingsGroup>
      </section>
    </div>
  );
}

function orderUnconfiguredProviders(
  providers: SettingsPayload["providers"],
): SettingsPayload["providers"] {
  return providers
    .map((provider, index) => ({ provider, index }))
    .sort((left, right) => {
      const rank = providerVisibilityRank(left.provider) - providerVisibilityRank(right.provider);
      return rank || left.index - right.index;
    })
    .map(({ provider }) => provider);
}

function providerVisibilityRank(provider: SettingsPayload["providers"][number]): number {
  const localRank = LOCAL_UNCONFIGURED_PROVIDER_ORDER.get(provider.name);
  if (localRank !== undefined) return localRank;
  if ((provider.api_key_required ?? true) === false) return 100;
  return 200;
}

function ProviderIcon({
  provider,
  showBrandLogos,
}: {
  provider: string;
  showBrandLogos: boolean;
}) {
  const brand = providerBrand(provider);
  const Icon = PROVIDER_ICONS[provider] ?? Hexagon;
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);

  if (showBrandLogos && logoUrl) {
    return (
      <span
        data-testid={`provider-logo-${provider}`}
        className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-control border border-border/45 bg-background"
      >
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-6 w-6 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      </span>
    );
  }
  if (showBrandLogos && brand) {
    return (
      <span
        data-testid={`provider-logo-fallback-${provider}`}
        className="grid h-10 w-10 shrink-0 place-items-center rounded-control text-[11px] font-semibold text-white"
        style={{ backgroundColor: brand.color }}
        aria-hidden
      >
        {brand.initials}
      </span>
    );
  }
  return (
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-muted text-foreground/82 dark:bg-muted/70">
      <Icon className="h-5 w-5" strokeWidth={2} aria-hidden />
    </span>
  );
}
