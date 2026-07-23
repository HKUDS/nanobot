import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Eye, EyeOff, Loader2, Plus, RefreshCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  channelTranslator,
  type ChannelTranslator,
} from "@/channel-plugins/i18n";
import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import { ToggleButton } from "@/components/settings/ToggleButton";
import {
  ChannelLogo,
  ChannelRuntimeError,
  ChannelStatusBadge,
  channelDescription,
  channelRequirements,
  channelSetup,
  channelStatusLabel,
  channelToggleChecked,
  localizedChannelDisplayName,
} from "@/components/settings/channels/ChannelIdentity";
import {
  ChannelGuideLink,
  ChannelOfficialLink,
} from "@/components/settings/channels/ChannelSetupParts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { configureChannel, validateChannel } from "@/lib/api";
import type {
  ChannelValidationPayload,
  NanobotChannelInstanceInfo,
  NanobotFeatureInfo,
  NanobotFeaturesPayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";

import { TelegramInstancesPanel } from "./TelegramInstancesPanel";

const NAME_KEY = "channels.telegram.name";
const TOKEN_KEY = "channels.telegram.token";
const PROXY_KEY = "channels.telegram.proxy";
const GROUP_POLICY_KEY = "channels.telegram.groupPolicy";
export const TELEGRAM_PROXY_CLEAR_VALUE = "__nanobot_clear_telegram_proxy__";

export function TelegramBotsPanel({
  token,
  feature,
  actionKey,
  chatAppsDocsUrl,
  showBrandLogos,
  onAction,
  onFeaturesUpdate,
}: ChannelPluginPanelProps) {
  const { t, i18n } = useTranslation();
  const tx = channelTranslator(t, "telegram");
  const allInstances = feature.instances?.length
    ? feature.instances
    : [defaultTelegramInstance(feature)];
  const instances = allInstances.filter(isVisibleTelegramInstance);
  const configuredCount = instances.filter((instance) => instance.configured).length;
  const panelFeature = useMemo(() => withoutGenericProxyField(feature), [feature]);
  const setup = useMemo(
    () => channelSetup(feature, i18n.resolvedLanguage ?? i18n.language),
    [feature.name, feature.setup, i18n.language, i18n.resolvedLanguage],
  );
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null);
  const [addingBot, setAddingBot] = useState(false);
  const [configurationRevisions, setConfigurationRevisions] = useState<Record<string, number>>({});
  const markInstanceChanged = (instanceId: string) => {
    setConfigurationRevisions((current) => ({
      ...current,
      [instanceId]: (current[instanceId] ?? 0) + 1,
    }));
  };
  const publishInstanceUpdate = (
    instanceId: string,
    payload: NanobotFeaturesPayload,
  ) => {
    markInstanceChanged(instanceId);
    onFeaturesUpdate(payload);
  };

  if (!feature.installed && feature.install_supported) {
    return (
      <TelegramInstallGate
        feature={feature}
        actionKey={actionKey}
        showBrandLogos={showBrandLogos}
        onAction={onAction}
      />
    );
  }

  return (
    <TelegramInstancesPanel
      token={token}
      feature={panelFeature}
      showBrandLogos={showBrandLogos}
      chatAppsDocsUrl={chatAppsDocsUrl}
      instances={instances}
      selectedInstanceId={selectedInstanceId}
      onSelectedInstanceChange={(instanceId) => {
        setSelectedInstanceId(instanceId);
        if (instanceId) setAddingBot(false);
      }}
      onInstanceMutation={markInstanceChanged}
      onFeaturesUpdate={onFeaturesUpdate}
      customization={{
        countLabel: (runningCount) => tx(
          "panel.count",
          "Configured: {{count}} · Running: {{running}}",
          { count: configuredCount, running: runningCount },
        ),
        toggleAriaLabel: (instance) => tx("panel.toggleBot", "{{name}} bot", {
          name: instanceDisplayName(instance),
        }),
        configuredLabel: tx("panel.running", "Running"),
        needsSetupLabel: tx("panel.needsToken", "Needs token"),
        renderInstanceAction: (instance) => instance.configured ? (
          <TelegramConnectionCheck
            key={instance.id}
            token={token}
            instance={instance}
            configurationRevision={configurationRevisions[instance.id] ?? 0}
          />
        ) : (
          <TelegramCredentialsForm
            key={instance.id}
            token={token}
            instanceId={instance.id}
            initialName={instance.config_values?.[NAME_KEY] ?? instanceDisplayName(instance)}
            proxyConfigured={hasConfiguredProxy(instance)}
            instanceEnabled={instance.enabled}
            submitLabel={tx("panel.finishSetup", "Check and finish setup")}
            tx={tx}
            onFeaturesUpdate={(payload) => publishInstanceUpdate(instance.id, payload)}
          />
        ),
        showSetupSteps: () => false,
        showInstanceFields: (instance) => instance.configured,
        renderInstanceAdvanced: (instance) => instance.configured ? (
          <TelegramProxySettings
            key={instance.id}
            token={token}
            instance={instance}
            onFeaturesUpdate={(payload) => publishInstanceUpdate(instance.id, payload)}
          />
        ) : null,
        footer: (
          <TelegramBotCreator
            token={token}
            feature={feature}
            instances={allInstances}
            visibleInstances={instances}
            setup={setup}
            chatAppsDocsUrl={chatAppsDocsUrl}
            tx={tx}
            open={addingBot}
            onOpenChange={(open) => {
              setAddingBot(open);
              if (open) setSelectedInstanceId(null);
            }}
            onInstanceMutation={markInstanceChanged}
            onFeaturesUpdate={onFeaturesUpdate}
          />
        ),
      }}
    />
  );
}

function TelegramInstallGate({
  feature,
  actionKey,
  showBrandLogos,
  onAction,
}: Pick<
  ChannelPluginPanelProps,
  "feature" | "actionKey" | "showBrandLogos" | "onAction"
>) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const displayName = localizedChannelDisplayName(feature, t);
  const enableBusy = actionKey === `enable:${feature.name}`;
  const disableBusy = actionKey === `disable:${feature.name}`;
  const channelBusy = enableBusy || disableBusy;
  const channelChecked = channelToggleChecked(feature);
  const toggleAriaLabel = t("settings.channels.toggleChannel", {
    name: displayName,
    defaultValue: "{{name}} channel",
  });

  return (
    <aside className="min-h-full rounded-[20px] border border-border/80 bg-background p-5 shadow-none">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[18px] font-semibold leading-6 text-foreground">
              {displayName}
            </h3>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
              {channelDescription(feature, t)}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-1">
          <ChannelStatusBadge status={feature.runtime_status}>
            {channelStatusLabel(feature, tx)}
          </ChannelStatusBadge>
          {channelBusy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden />
          ) : null}
          <ToggleButton
            checked={channelChecked}
            disabled={channelBusy || !feature.install_supported}
            ariaLabel={toggleAriaLabel}
            label={channelChecked ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            onChange={(checked) => onAction(checked ? "enable" : "disable", feature.name)}
          />
        </div>
      </div>

      <ChannelRuntimeError message={feature.runtime_error} className="mt-4" />

      <div className="mt-5 rounded-[16px] border border-border/65 bg-muted/20 px-4 py-4">
        <p className="text-[13px] leading-5 text-muted-foreground">
          {channelRequirements(feature, t)}
        </p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-3 h-8 rounded-full px-3 text-[12px] font-semibold"
          disabled={enableBusy}
          onClick={() => onAction("enable", feature.name)}
        >
          {enableBusy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {tx("settings.nanobotFeatures.installSupport", "Install support")}
        </Button>
      </div>
    </aside>
  );
}

function TelegramBotCreator({
  token,
  feature,
  instances,
  visibleInstances,
  setup,
  chatAppsDocsUrl,
  tx,
  open,
  onOpenChange,
  onInstanceMutation,
  onFeaturesUpdate,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  instances: NanobotChannelInstanceInfo[];
  visibleInstances: NanobotChannelInstanceInfo[];
  setup: ReturnType<typeof channelSetup>;
  chatAppsDocsUrl?: string;
  tx: ChannelTranslator;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInstanceMutation: (instanceId: string) => void;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const firstBot = visibleInstances.length === 0;
  const instanceId = nextTelegramInstanceId(instances);

  if (!firstBot && !open) {
    return (
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="mt-4 h-9 w-full rounded-[14px] border-border/70 bg-background text-[12px] font-semibold"
        onClick={() => onOpenChange(true)}
      >
        <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden />
        {tx("panel.addBot", "Add bot")}
      </Button>
    );
  }

  return (
    <section className="mt-4 overflow-hidden rounded-[16px] border border-border/70 bg-background px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[13px] font-semibold text-foreground">
          {firstBot
            ? tx("panel.connectFirst", "Connect your first bot")
            : tx("panel.addBot", "Add bot")}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <ChannelOfficialLink feature={feature} setup={setup} />
          <ChannelGuideLink
            feature={feature}
            setup={setup}
            chatAppsDocsUrl={chatAppsDocsUrl}
            compact
          />
        </div>
      </div>

      <div className="mt-4 border-t border-border/55 pt-4">
        <TelegramCredentialsForm
          token={token}
          instanceId={instanceId}
          submitLabel={firstBot
            ? tx("panel.connectBot", "Check and connect")
            : tx("panel.addBot", "Add bot")}
          tx={tx}
          onFeaturesUpdate={(payload) => {
            onInstanceMutation(instanceId);
            onFeaturesUpdate(payload);
          }}
          onComplete={() => onOpenChange(false)}
          onCancel={!firstBot ? () => onOpenChange(false) : undefined}
        />
      </div>
    </section>
  );
}

export function TelegramCredentialsForm({
  token,
  instanceId,
  initialName = "",
  proxyConfigured = false,
  instanceEnabled = false,
  submitLabel,
  tx,
  onFeaturesUpdate,
  onComplete,
  onCancel,
}: {
  token: string;
  instanceId: string;
  initialName?: string;
  proxyConfigured?: boolean;
  instanceEnabled?: boolean;
  submitLabel: string;
  tx: ChannelTranslator;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  onComplete?: () => void;
  onCancel?: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [botToken, setBotToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [proxy, setProxy] = useState("");
  const [showProxy, setShowProxy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setName(initialName);
    setBotToken("");
    setShowToken(false);
    setProxy("");
    setShowProxy(false);
    setError(null);
    setMessage(null);
  }, [initialName, instanceId]);

  const submit = async () => {
    const nextToken = botToken.trim();
    const nextProxy = proxy.trim();
    if (!nextToken) {
      setError(tx("panel.tokenRequired", "Enter the BotFather token first."));
      return;
    }

    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const values = {
        [TOKEN_KEY]: nextToken,
        ...(nextProxy ? { [PROXY_KEY]: nextProxy } : {}),
      };
      const validation = await validateChannel(
        token,
        "telegram",
        values,
        { instanceId },
      );
      if (!validation.can_enable || validation.status !== "connected") {
        setError(validation.status === "configured"
          ? proxyConnectionFailed(validation)
            ? tx(
              "panel.proxyUnavailable",
              "Telegram could not be reached through this proxy. Check the address and credentials.",
            )
            : tx(
              "panel.verificationUnavailable",
              "Telegram could not be reached. Check your network, or add a proxy under Advanced options, then try again.",
            )
          : validationMessage(validation, tx));
        return;
      }

      const resolvedName = name.trim()
        || normalizedBotHandle(validation.identity?.name)
        || defaultBotName(instanceId, tx);
      const configured = await configureChannel(
        token,
        "telegram",
        {
          [NAME_KEY]: resolvedName,
          [TOKEN_KEY]: nextToken,
          ...(nextProxy ? { [PROXY_KEY]: nextProxy } : {}),
        },
        { enable: true, instanceId },
      );
      if (configured.nanobot_features) {
        onFeaturesUpdate(configured.nanobot_features);
      }
      setBotToken("");
      onComplete?.();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const removeProxy = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const configured = await configureChannel(
        token,
        "telegram",
        { [PROXY_KEY]: TELEGRAM_PROXY_CLEAR_VALUE },
        { enable: instanceEnabled, instanceId },
      );
      if (configured.nanobot_features) {
        onFeaturesUpdate(configured.nanobot_features);
      }
      setProxy("");
      setShowProxy(false);
      setMessage(tx("panel.proxyRemoved", "Saved proxy removed."));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <label className="block">
        <span className="text-[11px] font-medium text-foreground/85">
          {tx("panel.botToken", "Bot token")}
          <span className="ml-0.5 text-destructive" aria-hidden>*</span>
        </span>
        <span className="relative mt-1 block">
          <Input
            aria-label={tx("panel.botToken", "Bot token")}
            type={showToken ? "text" : "password"}
            autoComplete="off"
            required
            value={botToken}
            onChange={(event) => setBotToken(event.target.value)}
            placeholder="123456:ABC..."
            className="h-9 rounded-[10px] border-border/60 bg-muted/35 pr-9 font-mono text-[12px]"
          />
          <button
            type="button"
            aria-label={showToken
              ? tx("panel.hideToken", "Hide token")
              : tx("panel.showToken", "Show token")}
            onClick={() => setShowToken((current) => !current)}
            className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-background hover:text-foreground"
          >
            {showToken ? (
              <EyeOff className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <Eye className="h-3.5 w-3.5" aria-hidden />
            )}
          </button>
        </span>
      </label>

      <details className="group rounded-[12px] border border-border/60 bg-muted/20 px-3 py-2.5">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[12px] font-medium text-foreground [&::-webkit-details-marker]:hidden">
          <span className="inline-flex items-center gap-1.5">
            {tx("panel.advancedOptions", "Advanced options")}
            <ChevronDown
              className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-180"
              aria-hidden
            />
          </span>
          {proxyConfigured ? (
            <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-200">
              {tx("panel.proxyConfigured", "Configured")}
            </span>
          ) : null}
        </summary>
        <div className="mt-3 space-y-3 border-t border-border/50 pt-3">
          <label className="block">
            <span className="text-[11px] font-medium text-foreground/85">
              {tx("panel.botName", "Bot name")}
            </span>
            <Input
              aria-label={tx("panel.botName", "Bot name")}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={tx("panel.botNamePlaceholder", "Support bot")}
              className="mt-1 h-9 rounded-[10px] border-border/60 bg-background text-[13px]"
            />
          </label>

          <div className="block">
            <span className="text-[11px] font-medium text-foreground/85">
              {tx("panel.networkProxy", "Network proxy (optional)")}
            </span>
            <TelegramProxyInput
              className="mt-1"
              value={proxy}
              visible={showProxy}
              configured={proxyConfigured}
              tx={tx}
              onChange={setProxy}
              onVisibleChange={setShowProxy}
            />
            {proxyConfigured && !proxy ? (
              <button
                type="button"
                className="mt-1.5 text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                onClick={() => void removeProxy()}
                disabled={busy}
              >
                {tx("panel.removeProxy", "Remove saved proxy")}
              </button>
            ) : null}
            {message ? (
              <span
                role="status"
                className="mt-1 block text-[11px] text-emerald-700 dark:text-emerald-200"
              >
                {message}
              </span>
            ) : null}
          </div>
        </div>
      </details>

      <div className="flex justify-end">
        <div className="flex items-center gap-2">
          {onCancel ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-8 rounded-full px-3 text-[12px] font-semibold"
              onClick={onCancel}
              disabled={busy}
            >
              {tx("panel.cancel", "Cancel")}
            </Button>
          ) : null}
          <Button
            type="submit"
            size="sm"
            variant="outline"
            className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold"
            disabled={busy || !botToken.trim()}
          >
            {busy ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {submitLabel}
          </Button>
        </div>
      </div>

      {error ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-[12px] border border-destructive/20 bg-destructive/5 px-3 py-2 text-[12px] leading-5 text-destructive"
        >
          <X className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      ) : null}
    </form>
  );
}

function TelegramProxyInput({
  className,
  value,
  visible,
  configured,
  tx,
  onChange,
  onVisibleChange,
}: {
  className?: string;
  value: string;
  visible: boolean;
  configured: boolean;
  tx: ChannelTranslator;
  onChange: (value: string) => void;
  onVisibleChange: (visible: boolean) => void;
}) {
  return (
    <span className={cn("relative block", className)}>
      <Input
        aria-label={tx("panel.networkProxy", "Network proxy (optional)")}
        type={visible ? "text" : "password"}
        autoComplete="off"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={configured
          ? tx("panel.savedProxyPlaceholder", "A proxy is already saved")
          : "http://127.0.0.1:7890"}
        className="h-9 rounded-[10px] border-border/60 bg-background pr-9 font-mono text-[12px]"
      />
      <button
        type="button"
        aria-label={visible
          ? tx("panel.hideProxy", "Hide proxy")
          : tx("panel.showProxy", "Show proxy")}
        onClick={() => onVisibleChange(!visible)}
        className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        {visible ? (
          <EyeOff className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <Eye className="h-3.5 w-3.5" aria-hidden />
        )}
      </button>
    </span>
  );
}

export function TelegramProxySettings({
  token,
  instance,
  onFeaturesUpdate,
}: {
  token: string;
  instance: NanobotChannelInstanceInfo;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "telegram");
  const configured = hasConfiguredProxy(instance);
  const [proxy, setProxy] = useState("");
  const [showProxy, setShowProxy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setProxy("");
    setShowProxy(false);
    setBusy(false);
    setError(null);
    setMessage(null);
  }, [configured, instance.id]);

  const applyProxy = async () => {
    const nextProxy = proxy.trim();
    if (!nextProxy) {
      setError(tx("panel.proxyRequired", "Enter a proxy URL first."));
      return;
    }

    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const validation = await validateChannel(
        token,
        "telegram",
        { [PROXY_KEY]: nextProxy },
        { instanceId: instance.id },
      );
      if (!validation.can_enable || validation.status !== "connected") {
        setError(validation.status === "configured" && proxyConnectionFailed(validation)
          ? tx(
            "panel.proxyUnavailable",
            "Telegram could not be reached through this proxy. Check the address and credentials.",
          )
          : validationMessage(validation, tx));
        return;
      }

      const configuredPayload = await configureChannel(
        token,
        "telegram",
        { [PROXY_KEY]: nextProxy },
        { enable: instance.enabled, instanceId: instance.id },
      );
      if (configuredPayload.nanobot_features) {
        onFeaturesUpdate(configuredPayload.nanobot_features);
      }
      setProxy("");
      setShowProxy(false);
      setMessage(tx("panel.proxySaved", "Proxy saved and connection verified."));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const removeProxy = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const configuredPayload = await configureChannel(
        token,
        "telegram",
        { [PROXY_KEY]: TELEGRAM_PROXY_CLEAR_VALUE },
        { enable: instance.enabled, instanceId: instance.id },
      );
      if (configuredPayload.nanobot_features) {
        onFeaturesUpdate(configuredPayload.nanobot_features);
      }
      setProxy("");
      setShowProxy(false);
      setMessage(tx("panel.proxyRemoved", "Saved proxy removed."));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label={tx("panel.networkProxy", "Network proxy (optional)")}>
      <div className="flex items-center justify-between gap-3 text-[12px] font-medium text-foreground">
        <span>{tx("panel.networkProxy", "Network proxy (optional)")}</span>
        {configured ? (
          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-200">
            {tx("panel.proxyConfigured", "Configured")}
          </span>
        ) : null}
      </div>
      <div className="mt-2">
        <div className="flex flex-col gap-2 sm:flex-row">
          <TelegramProxyInput
            className="min-w-0 flex-1"
            value={proxy}
            visible={showProxy}
            configured={configured}
            tx={tx}
            onChange={setProxy}
            onVisibleChange={setShowProxy}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-9 shrink-0 rounded-[10px] px-3 text-[12px] font-semibold"
            onClick={() => void applyProxy()}
            disabled={busy || !proxy.trim()}
          >
            {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
            {tx("panel.saveProxy", "Check and save")}
          </Button>
        </div>
        {configured ? (
          <button
            type="button"
            className="mt-2 text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            onClick={() => void removeProxy()}
            disabled={busy}
          >
            {tx("panel.removeProxy", "Remove saved proxy")}
          </button>
        ) : null}
        {error ? (
          <p role="alert" className="mt-2 text-[11.5px] leading-5 text-destructive">
            {error}
          </p>
        ) : message ? (
          <p role="status" className="mt-2 text-[11.5px] leading-5 text-emerald-700 dark:text-emerald-200">
            {message}
          </p>
        ) : null}
      </div>
    </section>
  );
}

export function TelegramConnectionCheck({
  token,
  instance,
  configurationRevision = 0,
}: {
  token: string;
  instance: NanobotChannelInstanceInfo;
  configurationRevision?: number;
}) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "telegram");
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState<ChannelValidationPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const checkRevision = useRef(0);

  useEffect(() => {
    checkRevision.current += 1;
    setBusy(false);
    setValidation(null);
    setError(null);
  }, [configurationRevision, instance.id]);

  const checkConnection = async () => {
    const revision = checkRevision.current + 1;
    checkRevision.current = revision;
    setBusy(true);
    setError(null);
    try {
      const result = await validateChannel(
        token,
        "telegram",
        {},
        { instanceId: instance.id },
      );
      if (revision === checkRevision.current) setValidation(result);
    } catch (err) {
      if (revision === checkRevision.current) setError((err as Error).message);
    } finally {
      if (revision === checkRevision.current) setBusy(false);
    }
  };

  const status = validation
    ? proxyConnectionFailed(validation)
      ? tx(
        "panel.proxyUnavailable",
        "Telegram could not be reached through this proxy. Check the address and credentials.",
      )
      : validationMessage(validation, tx)
    : null;
  const feedback = error ?? status;
  return (
    <div className={cn(
      "flex min-w-0 flex-wrap items-center gap-3",
      feedback
        ? "w-full basis-full flex-col items-stretch gap-2"
        : "ml-auto shrink-0 justify-end",
    )}>
      {feedback ? (
        <div
          role="status"
          className={cn(
            "w-full min-w-0 text-[12px] leading-5",
            validation?.status === "connected"
              ? "text-emerald-700 dark:text-emerald-200"
              : validation?.status === "invalid" || error
                ? "text-destructive"
                : "text-muted-foreground",
          )}
        >
          {feedback}
        </div>
      ) : null}
      <Button
        type="button"
        size="sm"
        variant="outline"
        className={cn(
          "h-8 shrink-0 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold",
          feedback && "self-end",
        )}
        onClick={() => void checkConnection()}
        disabled={busy}
      >
        {busy ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
        )}
        {tx("panel.checkConnection", "Check connection")}
      </Button>
    </div>
  );
}

function validationMessage(
  validation: ChannelValidationPayload,
  tx: ChannelTranslator,
): string {
  if (validation.checks.some((check) => check.id === "proxy_env" && check.status === "fail")) {
    return tx(
      "panel.proxyEnvMissing",
      "The saved proxy uses an environment variable that is not set.",
    );
  }
  if (validation.checks.some((check) => check.id === "token_env" && check.status === "fail")) {
    return tx(
      "panel.tokenEnvMissing",
      "The saved bot token uses an environment variable that is not set.",
    );
  }
  if (validation.checks.some((check) => check.id === "proxy_format" && check.status === "fail")) {
    return tx(
      "panel.invalidProxy",
      "Enter a full proxy URL, such as http://127.0.0.1:7890.",
    );
  }
  if (validation.status === "connected") {
    const identity = normalizedBotHandle(validation.identity?.name);
    return identity
      ? tx("panel.connectedAs", "Connected as {{name}}.", { name: identity })
      : tx("panel.connected", "Telegram accepted the saved token.");
  }
  if (validation.status === "configured") {
    return tx(
      "panel.configuredUnverified",
      "A saved token was found, but Telegram could not be reached. Check your network or proxy, then try again.",
    );
  }
  if (validation.status === "needs_setup") {
    return tx("panel.tokenRequired", "Enter the BotFather token first.");
  }
  if (validation.status === "invalid") {
    return tx("panel.invalidToken", "Telegram rejected this bot token.");
  }
  return tx("panel.checkFailed", "The connection could not be checked.");
}

function proxyConnectionFailed(validation: ChannelValidationPayload): boolean {
  return validation.checks.some(
    (check) => check.id === "proxy_connection" && check.status !== "pass",
  );
}

function normalizedBotHandle(value: string | undefined): string {
  const name = value?.trim();
  if (!name) return "";
  return name.startsWith("@") ? name : `@${name}`;
}

function defaultTelegramInstance(feature: NanobotFeatureInfo): NanobotChannelInstanceInfo {
  return {
    id: "default",
    name: feature.config_values?.[NAME_KEY] ?? "nanobot",
    enabled: feature.enabled,
    running: feature.running,
    runtime_status: feature.runtime_status,
    runtime_error: feature.runtime_error,
    configured: Boolean(feature.configured),
    config_values: feature.config_values ?? {},
    configured_fields: feature.configured_fields ?? [],
  };
}

export function isVisibleTelegramInstance(instance: NanobotChannelInstanceInfo): boolean {
  if (instance.configured || instance.enabled) return true;

  return instance.configured_fields.some((field) => {
    if (field === NAME_KEY) {
      const name = instance.config_values[NAME_KEY]?.trim();
      return Boolean(name && name !== "nanobot");
    }
    if (field === GROUP_POLICY_KEY) {
      const policy = instance.config_values[GROUP_POLICY_KEY]?.trim();
      return Boolean(policy && policy !== "mention");
    }
    return true;
  });
}

function withoutGenericProxyField(feature: NanobotFeatureInfo): NanobotFeatureInfo {
  if (!feature.setup?.fields.some((field) => field.key === PROXY_KEY)) return feature;
  return {
    ...feature,
    setup: {
      ...feature.setup,
      fields: feature.setup.fields.filter((field) => field.key !== PROXY_KEY),
    },
  };
}

function hasConfiguredProxy(instance: NanobotChannelInstanceInfo): boolean {
  return instance.configured_fields.includes(PROXY_KEY);
}

export function nextTelegramInstanceId(instances: NanobotChannelInstanceInfo[]): string {
  const reusableDefault = instances.find((instance) => instance.id === "default");
  if (!reusableDefault || !isVisibleTelegramInstance(reusableDefault)) return "default";

  const ids = new Set(instances.map((instance) => instance.id));
  let index = 2;
  while (ids.has(`bot-${index}`)) index += 1;
  return `bot-${index}`;
}

function defaultBotName(instanceId: string, tx: ChannelTranslator): string {
  if (instanceId === "default") return tx("panel.defaultBotName", "Telegram bot");
  const number = instanceId.replace(/^bot-/, "");
  return tx("panel.numberedBotName", "Telegram bot {{number}}", { number });
}

function instanceDisplayName(instance: NanobotChannelInstanceInfo): string {
  return instance.display_name?.trim() || instance.name.trim() || instance.id;
}
