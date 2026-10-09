import { useEffect, useId, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { fetchProviderModels } from "@/lib/api";
import type { ProviderModelsPayload, SettingsPayload } from "@/lib/types";

const DEFAULT_OPTION = "__reasoning_default__";
const CUSTOM_OPTION = "__reasoning_custom__";
const GENERIC_EFFORT_SUGGESTIONS = ["low", "medium", "high"];

const PROVIDER_ID_PREFIXES: Record<string, readonly string[]> = {
  openai_codex: ["openai-codex/", "openai_codex/"],
  xai_grok: ["xai-grok/", "xai_grok/"],
  github_copilot: ["github-copilot/", "github_copilot/"],
};

function effectiveProviderFor(
  provider: string,
  model: string,
  selectedPreset: SettingsPayload["model_presets"][number] | null,
  settings: SettingsPayload,
): string | null {
  if (provider && provider !== "auto") return provider;
  if (provider !== "auto") return null;
  if (selectedPreset?.resolved_provider && selectedPreset.model === model) {
    return selectedPreset.resolved_provider;
  }
  if (model && settings.agent.model === model) {
    return settings.agent.resolved_provider ?? settings.agent.provider ?? null;
  }
  return null;
}

function stripProviderPrefix(id: string, provider: string | null): string {
  for (const prefix of PROVIDER_ID_PREFIXES[provider ?? ""] ?? []) {
    if (id.startsWith(prefix)) return id.slice(prefix.length);
  }
  return id;
}

function catalogModelFor(
  models: ProviderModelsPayload["models"],
  model: string,
  provider: string | null,
): ProviderModelsPayload["models"][number] | null {
  if (!model) return null;
  const wireId = stripProviderPrefix(model, provider);
  return (
    models.find((entry) => entry.id === model) ??
    models.find((entry) => stripProviderPrefix(entry.id, provider) === wireId) ??
    null
  );
}

export function ReasoningEffortControl({
  token,
  settings,
  selectedPreset,
  provider,
  model,
  value,
  onProviderOAuthLogin,
  providerSigningIn = false,
  onChange,
}: {
  token: string;
  settings: SettingsPayload;
  selectedPreset: SettingsPayload["model_presets"][number] | null;
  provider: string;
  model: string;
  value: string;
  onProviderOAuthLogin?: (provider: string) => void;
  providerSigningIn?: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const selectId = useId();
  const noticeId = useId();
  const [payload, setPayload] = useState<ProviderModelsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [customSelected, setCustomSelected] = useState(false);

  const effectiveProvider = effectiveProviderFor(provider, model, selectedPreset, settings);
  const providerRow = settings.providers.find((row) => row.name === effectiveProvider) ?? null;
  const discoverable = Boolean(
    effectiveProvider && providerRow?.configured && providerRow.model_catalog === "hybrid",
  );

  useEffect(() => {
    if (!discoverable || !effectiveProvider) {
      setPayload(null);
      setFailed(false);
      setLoading(false);
      return;
    }
    setLoading(true);
    setFailed(false);
    let cancelled = false;
    fetchProviderModels(tokenRef.current, effectiveProvider)
      .then((nextPayload) => {
        if (!cancelled) setPayload(nextPayload);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveProvider, discoverable, providerRow]);

  useEffect(() => {
    setCustomSelected(false);
  }, [provider, model, selectedPreset?.name]);

  const catalog = payload?.provider === effectiveProvider ? payload : null;
  const authRejected = catalog?.error_kind === "auth_required";
  const catalogModel = catalogModelFor(catalog?.models ?? [], model, effectiveProvider);
  const catalogEfforts = [
    ...new Set((catalogModel?.reasoning_efforts ?? []).filter((effort) => effort.trim())),
  ];
  const providerConfirmed = catalogModel?.reasoning_efforts_from_provider === true;

  let options: string[];
  let sourceNote: string;
  if (catalogEfforts.length) {
    options = catalogEfforts;
    sourceNote = providerConfirmed
      ? catalog?.source === "remote"
        ? tx("settings.models.reasoningEffortSourceLive", "Levels reported by the provider for this model.")
        : catalog?.source === "cache"
          ? tx("settings.models.reasoningEffortSourceCached", "Levels reported by the provider (cached).")
          : tx("settings.models.reasoningEffortSourceStale", "Last provider-reported levels; may be out of date.")
      : tx("settings.models.reasoningEffortSourceBuiltin", "Built-in suggestions; not confirmed by the provider.");
  } else {
    const presetProvider = selectedPreset
      ? selectedPreset.resolved_provider ??
        (selectedPreset.provider === "auto" ? null : selectedPreset.provider)
      : null;
    const presetMatches =
      selectedPreset !== null &&
      selectedPreset.model === model &&
      presetProvider === effectiveProvider;
    const presetEffortValues = selectedPreset?.reasoning_effort_values;
    const presetSuggestions =
      presetMatches && presetEffortValues?.length
        ? [
            ...new Set(
              presetEffortValues.filter((effort) => effort.trim()),
            ),
          ]
        : undefined;
    if (presetSuggestions === undefined) {
      options = GENERIC_EFFORT_SUGGESTIONS;
      sourceNote = tx("settings.models.reasoningEffortSourceGeneric", "Generic suggestions; supported levels for this model are unknown.");
    } else if (presetSuggestions.length) {
      options = presetSuggestions;
      sourceNote = tx("settings.models.reasoningEffortSourcePreset", "Suggested for this provider; not confirmed for this model.");
    } else {
      options = [];
      sourceNote = tx("settings.models.reasoningEffortDefaultOnly", "This model uses automatic reasoning; no effort levels are configurable.");
    }
  }

  const listed = value !== "" && options.includes(value);
  const customMode = customSelected || (value !== "" && !listed);
  const selectValue = value === "" && !customSelected ? DEFAULT_OPTION : listed && !customSelected ? value : CUSTOM_OPTION;

  return (
    <div className="w-full space-y-2">
      <Select
        value={selectValue}
        onValueChange={(next) => {
          if (next === CUSTOM_OPTION) {
            setCustomSelected(true);
            return;
          }
          setCustomSelected(false);
          onChange(next === DEFAULT_OPTION ? "" : next);
        }}
      >
        <SelectTrigger
          id={selectId}
          type="button"
          aria-label={tx("settings.models.reasoningEffort", "Reasoning effort")}
          aria-describedby={noticeId}
          className="h-9 w-full justify-between rounded-full border-input bg-background px-3 text-[13px] font-normal shadow-none settings-hover focus-visible:ring-2 focus-visible:ring-ring"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={DEFAULT_OPTION}>
            {tx("settings.values.default", "Default")}
          </SelectItem>
          {options.map((effort) => (
            <SelectItem key={effort} value={effort}>
              {effort}
            </SelectItem>
          ))}
          <SelectItem value={CUSTOM_OPTION}>
            {tx("settings.models.reasoningEffortCustom", "Custom")}
          </SelectItem>
        </SelectContent>
      </Select>
      {customMode ? (
        <Input
          value={value}
          onFocus={() => setCustomSelected(true)}
          onChange={(event) => {
            setCustomSelected(true);
            onChange(event.target.value);
          }}
          placeholder={tx("settings.models.reasoningEffortCustomPlaceholder", "e.g. minimal, xhigh")}
          aria-label={tx("settings.models.reasoningEffortCustom", "Custom")}
          autoCapitalize="none"
          spellCheck={false}
          className="h-9 text-[13px]"
        />
      ) : null}
      <p id={noticeId} role="status" className="text-[11px] leading-4 text-muted-foreground">
        {authRejected ? (
          <>
            {tx(
              "settings.models.reasoningEffortAuthRequired",
              "Sign in to load this provider’s model levels. The saved value is unchanged.",
            )}
            {onProviderOAuthLogin && providerRow?.oauth_login_supported && effectiveProvider ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="ml-2 h-6 rounded-full px-2.5 text-[11px]"
                disabled={providerSigningIn}
                onClick={() => onProviderOAuthLogin(effectiveProvider)}
              >
                {providerSigningIn ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" aria-hidden />
                ) : null}
                {providerSigningIn
                  ? tx("settings.oauth.signingIn", "Signing in...")
                  : tx("settings.oauth.signIn", "Sign in")}
              </Button>
            ) : null}
          </>
        ) : loading && discoverable ? (
          <span className="inline-flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            {tx("settings.models.reasoningEffortLoading", "Loading model levels...")}
          </span>
        ) : failed ? (
          tx("settings.models.reasoningEffortLoadFailed", "Could not load model levels.")
        ) : (
          sourceNote
        )}
        {value !== "" && !listed ? (
          <span className="block">
            {tx(
              "settings.models.reasoningEffortNotListed",
              "“{{value}}” is not a listed level; it will be kept as a custom value.",
              { value },
            )}
          </span>
        ) : null}
      </p>
    </div>
  );
}
