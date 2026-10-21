import {
  ModelsIcon,
  WebSearchIcon,
  ImageGenerationIcon,
  VoiceIcon,
} from "@/components/icons/product-icons";
import { useContext, useState, type Dispatch, type SetStateAction } from "react";
import {
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { HostNavigationContext } from "@/components/remote/HostSwitcher";
import { StarLink } from "@/components/StarPrompt";
import { AboutSettingsView } from "./AboutSettingsView";
import { AppearanceSettingsView } from "./AppearanceSettingsView";
import { VersionCheckRowView, type VersionCheckState, type VersionInfoProps } from "./VersionCheckRowView";
import { DEFAULT_TRANSCRIPTION_SETTINGS } from "@/components/settings/capabilities/TranscriptionSettings";
import type { SettingsSectionKey } from "@/components/settings/contracts";
import { settingsProviderConfigured } from "@/components/settings/shared/ModelControls";
import {
  SettingsGroup,
  SettingsSectionTitle,
} from "@/components/settings/shared/SettingsControls";
import { TokenUsageCard } from "@/components/settings/TokenUsageCard";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { checkVersion } from "@/lib/api";
import type {
  LocalPreferences,
} from "@/lib/local-preferences";
import { providerBrand, providerDisplayLabel } from "@/lib/provider-brand";
import type { SettingsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export function OverviewSettings({
  settings,
  onSelectSection,
  showBrandLogos,
}: {
  settings: SettingsPayload;
  onSelectSection: (section: SettingsSectionKey) => void;
  showBrandLogos: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const activePresetName = settings.agent.model_preset;
  const activePreset =
    activePresetName && activePresetName !== "default"
      ? settings.model_presets.find((preset) => preset.name === activePresetName)?.name ??
        activePresetName
      : null;
  const activeProvider = settings.agent.resolved_provider ?? settings.agent.provider;
  const activeProviderConfigured = settingsProviderConfigured(settings, activeProvider);
  const activeProviderLabel = providerDisplayLabel(settings.providers, activeProvider);
  const activeModelValue = activeProviderConfigured
    ? settings.agent.model
    : tx("settings.values.notConfigured", "Not configured");
  const activeModelCaption = activeProviderConfigured
    ? [activeProvider, activePreset].filter(Boolean).join(" ")
    : activeProviderLabel || settings.agent.model
      ? [activeProviderLabel, settings.agent.model].filter(Boolean).join(" ")
      : tx("settings.byok.noConfiguredProviders", "No configured providers");
  const webStatus = settings.web.enable
    ? tx("settings.values.enabled", "Enabled")
    : tx("settings.values.disabled", "Disabled");
  const imageStatus = settings.image_generation.enabled
    ? tx("settings.values.enabled", "Enabled")
    : tx("settings.values.disabled", "Disabled");
  const transcription = settings.transcription ?? DEFAULT_TRANSCRIPTION_SETTINGS;
  const voiceStatus = transcription.enabled
    ? tx("settings.values.enabled", "Enabled")
    : tx("settings.values.disabled", "Disabled");
  return (
    <div className="settings-stack">
      <section className="rounded-panel bg-settings-surface p-6">
        <TokenUsageCard usage={settings.usage} timeZone={settings.agent.timezone} />
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.ai", "AI")}</SettingsSectionTitle>
        <SettingsGroup>
          <OverviewListRow
            icon={ModelsIcon}
            valueLogoProvider={activeProvider}
            title={tx("settings.overview.model", "Current model")}
            value={activeModelValue}
            caption={activeModelCaption}
            showBrandLogos={showBrandLogos}
            onClick={() => onSelectSection("models")}
          />
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.capabilities", "Capabilities")}</SettingsSectionTitle>
        <SettingsGroup>
          <OverviewListRow
            icon={WebSearchIcon}
            valueLogoProvider={settings.web_search.provider}
            title={tx("settings.overview.webSearch", "Web search")}
            value={webStatus}
            showBrandLogos={showBrandLogos}
            onClick={() => onSelectSection("browser")}
          />
          <OverviewListRow
            icon={ImageGenerationIcon}
            valueLogoProvider={settings.image_generation.provider}
            title={tx("settings.overview.imageGeneration", "Image generation")}
            value={imageStatus}
            showBrandLogos={showBrandLogos}
            onClick={() => onSelectSection("image")}
          />
          <OverviewListRow
            icon={VoiceIcon}
            valueLogoProvider={transcription.provider}
            title={tx("settings.overview.voiceInput", "Voice input")}
            value={voiceStatus}
            showBrandLogos={showBrandLogos}
            onClick={() => onSelectSection("voice")}
          />
        </SettingsGroup>
      </section>

    </div>
  );
}

export function AboutSettings({ settings }: { settings: SettingsPayload }) {
  const hostPicker = useContext(HostNavigationContext);
  const currentVersion = settings.version?.current;
  const currentCommit = settings.version?.commit;
  const environment = settings.environment;
  const reportIssueUrl = new URL("https://github.com/HKUDS/nanobot/issues/new");
  reportIssueUrl.searchParams.set("template", "bug_report.yml");
  const reportedVersion = [currentVersion, currentCommit && `(commit ${currentCommit})`]
    .filter(Boolean).join(" ");
  if (reportedVersion) reportIssueUrl.searchParams.set("version", reportedVersion);
  reportIssueUrl.searchParams.set("channel", "WebSocket");
  if (environment) {
    reportIssueUrl.searchParams.set("python_version", environment.python_version);
    const osName = environment.os === "Darwin" ? "macOS" : environment.os;
    const osVersion = [osName, environment.os_version].filter(Boolean).join(" ");
    reportIssueUrl.searchParams.set("os", environment.architecture
      ? `${osVersion} (${environment.architecture})` : osVersion);
  }
  if (settings.agent.model) reportIssueUrl.searchParams.set("model", settings.agent.model);
  const provider = settings.agent.resolved_provider || settings.agent.provider;
  if (provider) reportIssueUrl.searchParams.set("llm_provider", provider);
  reportIssueUrl.searchParams.set("browser", navigator.userAgent);
  reportIssueUrl.searchParams.set("connection", hostPicker?.kind === "embedded"
    ? "Remote host" : hostPicker ? "Local host" : "Direct WebUI");
  return <AboutSettingsView reportIssueUrl={reportIssueUrl.href}
    versionCheck={<VersionCheckRow currentVersion={currentVersion} currentCommit={currentCommit} />}
    starLink={<StarLink />} />;
}

function VersionCheckRow({ currentVersion, currentCommit }: VersionInfoProps) {
  const { token } = useClient();
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<VersionCheckState>(null);

  const handleCheck = async () => {
    setChecking(true);
    setResult(null);
    try {
      const res = await checkVersion(token);
      if (res.updateAvailable) {
        setResult({
          type: "update",
          latestVersion: res.updateAvailable.latestVersion,
          pypiUrl: res.updateAvailable.pypiUrl,
        });
      } else {
        setResult({ type: "up-to-date" });
      }
    } catch (err) {
      setResult({ type: "error", message: (err as Error).message });
    } finally {
      setChecking(false);
    }
  };

  return <VersionCheckRowView currentVersion={currentVersion} currentCommit={currentCommit}
    checking={checking} result={result} onCheck={() => void handleCheck()} />;
}

export function AppearanceSettings({ theme, onToggleTheme, localPrefs, onChangeLocalPrefs }: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  localPrefs: LocalPreferences;
  onChangeLocalPrefs: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  return <AppearanceSettingsView theme={theme} onToggleTheme={onToggleTheme}
    localPrefs={localPrefs} onChangeLocalPrefs={onChangeLocalPrefs} />;
}

function OverviewRowIcon({
  icon: Icon,
}: {
  icon: LucideIcon;
}) {
  return (
    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-control bg-muted text-foreground/82 transition-colors dark:bg-muted/70">
      <Icon className="h-4 w-4" aria-hidden />
    </span>
  );
}

function OverviewValueLogo({
  provider,
  showBrandLogos,
}: {
  provider: string | null | undefined;
  showBrandLogos: boolean;
}) {
  const brand = provider ? providerBrand(provider) : null;
  const { logoUrl, logoLoaded, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);
  const isLogoTile = brand?.logoLayout === "tile" && logoUrl === brand.logoUrl;

  if (!provider || !showBrandLogos || !brand) return null;

  if (logoUrl) {
    return (
      <span
        data-testid={`overview-logo-${provider}`}
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
          style={{ backgroundColor: brand.color }}
        >
          {brand.initials}
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

  return (
    <span
      data-testid={`overview-logo-fallback-${provider}`}
      className="grid h-5 w-5 shrink-0 place-items-center rounded-md text-[7.5px] font-semibold text-white"
      style={{ backgroundColor: brand.color }}
      aria-hidden
    >
      {brand.initials}
    </span>
  );
}

function OverviewListRow({
  icon: Icon,
  valueLogoProvider,
  title,
  value,
  caption,
  showBrandLogos = false,
  onClick,
}: {
  icon: LucideIcon;
  valueLogoProvider?: string | null;
  title: string;
  value: string;
  caption?: string;
  showBrandLogos?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex min-h-[68px] w-full select-none items-center gap-3 px-4 py-3.5 text-left transition-colors settings-hover sm:px-5"
    >
      <OverviewRowIcon icon={Icon} />
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium leading-5 text-foreground">{title}</span>
        {caption ? <span className="sr-only">{caption}</span> : null}
      </span>
      <span className="ml-auto flex min-w-0 max-w-[48%] items-center gap-2">
        <OverviewValueLogo provider={valueLogoProvider} showBrandLogos={showBrandLogos} />
        <span className="truncate text-right text-[13px] leading-5 text-muted-foreground">
          {value}
        </span>
        <ChevronRight
          className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5"
          aria-hidden
        />
      </span>
    </button>
  );
}
