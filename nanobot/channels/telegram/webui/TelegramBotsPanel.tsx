import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Eye, EyeOff, Loader2, Plus, RefreshCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  channelTranslator,
  type ChannelTranslator,
} from "@/channel-plugins/i18n";
import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import { ChannelInstancesPanel } from "@/components/settings/channels/ChannelInstancesPanel";
import { channelSetup } from "@/components/settings/channels/ChannelIdentity";
import { ChannelSetupLinks } from "@/components/settings/channels/ChannelSetupParts";
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

const NAME_KEY = "channels.telegram.name";
const TOKEN_KEY = "channels.telegram.token";
const PROXY_KEY = "channels.telegram.proxy";
const GROUP_POLICY_KEY = "channels.telegram.groupPolicy";
export const TELEGRAM_PROXY_CLEAR_VALUE = "__nanobot_clear_telegram_proxy__";

export function TelegramBotsPanel({
  token,
  feature,
  showBrandLogos,
  chatAppsDocsUrl,
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

  return (
    <ChannelInstancesPanel
      token={token}
      feature={panelFeature}
      showBrandLogos={showBrandLogos}
      chatAppsDocsUrl={chatAppsDocsUrl}
      instances={instances}
      onFeaturesUpdate={onFeaturesUpdate}
      customization={{
        countLabel: (runningCount) => telegramBotCountLabel(
          configuredCount,
          runningCount,
          tx,
        ),
        toggleAriaLabel: (instance) => tx("custom.toggleBot", "{{name}} bot", {
          name: instanceDisplayName(instance),
        }),
        configuredLabel: tx("custom.running", "Running"),
        needsSetupLabel: tx("custom.needsToken", "Needs token"),
        renderInstanceSummary: (instance) => (
          instance.id === "default"
            ? tx("custom.defaultInstance", "Default bot")
            : tx("custom.instanceId", "Instance {{id}}", { id: instance.id })
        ),
        renderInstanceAction: (instance) => instance.configured ? (
          <TelegramConnectionCheck key={instance.id} token={token} instance={instance} />
        ) : (
          <TelegramCredentialsForm
            key={instance.id}
            token={token}
            instanceId={instance.id}
            initialName={instance.config_values?.[NAME_KEY] ?? instanceDisplayName(instance)}
            proxyConfigured={hasConfiguredProxy(instance)}
            instanceEnabled={instance.enabled}
            submitLabel={tx("custom.finishSetup", "Check and finish setup")}
            tx={tx}
            onFeaturesUpdate={onFeaturesUpdate}
          />
        ),
        showSetupSteps: (instance) => !instance.configured,
        renderInstanceAdvanced: (instance) => instance.configured ? (
          <TelegramProxySettings
            key={instance.id}
            token={token}
            instance={instance}
            onFeaturesUpdate={onFeaturesUpdate}
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
            onFeaturesUpdate={onFeaturesUpdate}
          />
        ),
      }}
    />
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
  onFeaturesUpdate,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  instances: NanobotChannelInstanceInfo[];
  visibleInstances: NanobotChannelInstanceInfo[];
  setup: ReturnType<typeof channelSetup>;
  chatAppsDocsUrl?: string;
  tx: ChannelTranslator;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const firstBot = visibleInstances.length === 0;
  const [open, setOpen] = useState(firstBot);
  const instanceId = nextTelegramInstanceId(instances);

  useEffect(() => {
    if (firstBot) setOpen(true);
  }, [firstBot]);

  return (
    <section className="mt-4 overflow-hidden rounded-[16px] border border-border/70 bg-background px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-foreground">
            {firstBot
              ? tx("custom.connectFirst", "Connect your first bot")
              : tx("custom.addAnother", "Add another bot")}
          </div>
          {firstBot ? (
            <p className="mt-1 text-[12.5px] leading-5 text-muted-foreground">
              {tx(
                "custom.connectFirstHint",
                "Paste a BotFather token. nanobot will verify it before saving anything.",
              )}
            </p>
          ) : null}
          {firstBot || open ? (
            <ChannelSetupLinks
              feature={feature}
              setup={setup}
              chatAppsDocsUrl={chatAppsDocsUrl}
            />
          ) : null}
        </div>
        {!open ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 shrink-0 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold"
            onClick={() => setOpen(true)}
          >
            <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            {tx("custom.addBot", "Add bot")}
          </Button>
        ) : null}
      </div>

      {open ? (
        <div className="mt-4 border-t border-border/55 pt-4">
          <TelegramCredentialsForm
            token={token}
            instanceId={instanceId}
            submitLabel={firstBot
              ? tx("custom.connectBot", "Check and connect")
              : tx("custom.addBot", "Add bot")}
            tx={tx}
            onFeaturesUpdate={onFeaturesUpdate}
            onComplete={() => {
              if (!firstBot) setOpen(false);
            }}
            onCancel={!firstBot ? () => setOpen(false) : undefined}
          />
        </div>
      ) : null}
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
      setError(tx("custom.tokenRequired", "Enter the BotFather token first."));
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
              "custom.proxyUnavailable",
              "Telegram could not be reached through this proxy. Check the address and credentials.",
            )
            : tx(
              "custom.verificationUnavailable",
              "Telegram could not verify this token right now. Try again before connecting.",
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
      setMessage(tx("custom.proxyRemoved", "Saved proxy removed."));
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
          {tx("custom.botToken", "Bot token")}
          <span className="ml-0.5 text-destructive" aria-hidden>*</span>
        </span>
        <span className="relative mt-1 block">
          <Input
            aria-label={tx("custom.botToken", "Bot token")}
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
              ? tx("custom.hideToken", "Hide token")
              : tx("custom.showToken", "Show token")}
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
            {tx("custom.advancedOptions", "Advanced options")}
            <ChevronDown
              className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-180"
              aria-hidden
            />
          </span>
          <span className={cn(
            "rounded-full px-2 py-0.5 text-[10px] font-semibold",
            proxyConfigured
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
              : "bg-muted text-muted-foreground",
          )}>
            {proxyConfigured
              ? tx("custom.proxyConfigured", "Configured")
              : tx("custom.proxyOptional", "Optional")}
          </span>
        </summary>
        <div className="mt-3 space-y-3 border-t border-border/50 pt-3">
          <label className="block">
            <span className="text-[11px] font-medium text-foreground/85">
              {tx("custom.botName", "Bot name")}
            </span>
            <Input
              aria-label={tx("custom.botName", "Bot name")}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={tx("custom.botNamePlaceholder", "Support bot")}
              className="mt-1 h-9 rounded-[10px] border-border/60 bg-background text-[13px]"
            />
          </label>

          <div className="block">
            <span className="text-[11px] font-medium text-foreground/85">
              {tx("custom.networkProxy", "Network proxy (optional)")}
            </span>
            <span className="relative mt-1 block">
              <Input
                aria-label={tx("custom.networkProxy", "Network proxy (optional)")}
                type={showProxy ? "text" : "password"}
                autoComplete="off"
                value={proxy}
                onChange={(event) => setProxy(event.target.value)}
                placeholder={proxyConfigured
                  ? tx("custom.savedProxyPlaceholder", "A proxy is already saved")
                  : "http://127.0.0.1:7890"}
                className="h-9 rounded-[10px] border-border/60 bg-background pr-9 font-mono text-[12px]"
              />
              <button
                type="button"
                aria-label={showProxy
                  ? tx("custom.hideProxy", "Hide proxy")
                  : tx("custom.showProxy", "Show proxy")}
                onClick={() => setShowProxy((current) => !current)}
                className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {showProxy ? (
                  <EyeOff className="h-3.5 w-3.5" aria-hidden />
                ) : (
                  <Eye className="h-3.5 w-3.5" aria-hidden />
                )}
              </button>
            </span>
            <span className="mt-1 block text-[11px] leading-4 text-muted-foreground">
              {proxyConfigured && !proxy
                ? tx(
                  "custom.savedProxyHint",
                  "Leave this blank to keep the saved proxy. Enter a new URL to replace it.",
                )
                : tx(
                  "custom.proxyHint",
                  "Used for both connection checks and bot traffic. HTTP and SOCKS URLs are supported.",
                )}
            </span>
            {proxyConfigured && !proxy ? (
              <button
                type="button"
                className="mt-1.5 text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                onClick={() => void removeProxy()}
                disabled={busy}
              >
                {tx("custom.removeProxy", "Remove saved proxy")}
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

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[11.5px] leading-5 text-muted-foreground">
          {tx("custom.secretHint", "The token stays masked after it is saved.")}
        </p>
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
              {tx("custom.cancel", "Cancel")}
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
      setError(tx("custom.proxyRequired", "Enter a proxy URL first."));
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
            "custom.proxyUnavailable",
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
      setMessage(tx("custom.proxySaved", "Proxy saved and connection verified."));
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
      setMessage(tx("custom.proxyRemoved", "Saved proxy removed."));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label={tx("custom.networkProxy", "Network proxy (optional)")}>
      <div className="flex items-center justify-between gap-3 text-[12px] font-medium text-foreground">
        <span>{tx("custom.networkProxy", "Network proxy (optional)")}</span>
        <span className={cn(
          "rounded-full px-2 py-0.5 text-[10px] font-semibold",
          configured
            ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
            : "bg-muted text-muted-foreground",
        )}>
          {configured
            ? tx("custom.proxyConfigured", "Configured")
            : tx("custom.proxyOptional", "Optional")}
        </span>
      </div>
      <div className="mt-2">
        <p className="text-[11px] leading-4 text-muted-foreground">
          {tx(
            "custom.proxyHint",
            "Used for both connection checks and bot traffic. HTTP and SOCKS URLs are supported.",
          )}
        </p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <span className="relative block min-w-0 flex-1">
            <Input
              aria-label={tx("custom.networkProxy", "Network proxy (optional)")}
              type={showProxy ? "text" : "password"}
              autoComplete="off"
              value={proxy}
              onChange={(event) => setProxy(event.target.value)}
              placeholder={configured
                ? tx("custom.savedProxyPlaceholder", "A proxy is already saved")
                : "http://127.0.0.1:7890"}
              className="h-9 rounded-[10px] border-border/60 bg-background pr-9 font-mono text-[12px]"
            />
            <button
              type="button"
              aria-label={showProxy
                ? tx("custom.hideProxy", "Hide proxy")
                : tx("custom.showProxy", "Show proxy")}
              onClick={() => setShowProxy((current) => !current)}
              className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {showProxy ? (
                <EyeOff className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <Eye className="h-3.5 w-3.5" aria-hidden />
              )}
            </button>
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-9 shrink-0 rounded-[10px] px-3 text-[12px] font-semibold"
            onClick={() => void applyProxy()}
            disabled={busy || !proxy.trim()}
          >
            {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
            {tx("custom.saveProxy", "Check and save")}
          </Button>
        </div>
        {configured ? (
          <button
            type="button"
            className="mt-2 text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            onClick={() => void removeProxy()}
            disabled={busy}
          >
            {tx("custom.removeProxy", "Remove saved proxy")}
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
}: {
  token: string;
  instance: NanobotChannelInstanceInfo;
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
  }, [instance]);

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
        "custom.proxyUnavailable",
        "Telegram could not be reached through this proxy. Check the address and credentials.",
      )
      : validationMessage(validation, tx)
    : null;
  const feedback = error ?? status;
  return (
    <div className={cn(
      "mt-3 flex flex-wrap items-center gap-3",
      feedback ? "justify-between" : "justify-end",
    )}>
      {feedback ? (
        <div
          role="status"
          className={cn(
            "min-w-0 flex-1 text-[12px] leading-5",
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
        className="h-8 shrink-0 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold"
        onClick={() => void checkConnection()}
        disabled={busy}
      >
        {busy ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
        )}
        {tx("custom.checkConnection", "Check connection")}
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
      "custom.proxyEnvMissing",
      "The saved proxy uses an environment variable that is not set.",
    );
  }
  if (validation.checks.some((check) => check.id === "token_env" && check.status === "fail")) {
    return tx(
      "custom.tokenEnvMissing",
      "The saved bot token uses an environment variable that is not set.",
    );
  }
  if (validation.checks.some((check) => check.id === "proxy_format" && check.status === "fail")) {
    return tx(
      "custom.invalidProxy",
      "Enter a full proxy URL, such as http://127.0.0.1:7890.",
    );
  }
  if (validation.status === "connected") {
    const identity = normalizedBotHandle(validation.identity?.name);
    return identity
      ? tx("custom.connectedAs", "Connected as {{name}}.", { name: identity })
      : tx("custom.connected", "Telegram accepted the saved token.");
  }
  if (validation.status === "configured") {
    return tx(
      "custom.configuredUnverified",
      "A saved token was found, but Telegram could not verify it right now.",
    );
  }
  if (validation.status === "needs_setup") {
    return tx("custom.tokenRequired", "Enter the BotFather token first.");
  }
  if (validation.status === "invalid") {
    return tx("custom.invalidToken", "Telegram rejected this bot token.");
  }
  return tx("custom.checkFailed", "The connection could not be checked.");
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
  if (instanceId === "default") return tx("custom.defaultBotName", "Telegram bot");
  const number = instanceId.replace(/^bot-/, "");
  return tx("custom.numberedBotName", "Telegram bot {{number}}", { number });
}

function instanceDisplayName(instance: NanobotChannelInstanceInfo): string {
  return instance.display_name?.trim() || instance.name.trim() || instance.id;
}

function telegramBotCountLabel(
  configuredCount: number,
  runningCount: number,
  tx: ChannelTranslator,
): string {
  if (configuredCount === 0) return tx("custom.countNone", "No bots configured");
  if (configuredCount === 1) {
    return tx("custom.countOne", "1 bot configured · {{running}} running", {
      running: runningCount,
    });
  }
  return tx(
    "custom.countMany",
    "{{count}} bots configured · {{running}} running",
    { count: configuredCount, running: runningCount },
  );
}
