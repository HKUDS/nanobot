import { ChevronLeft } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogLayoutContext, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { SettingsExitGuard } from "@/components/settings/contracts";
import { isCapabilitySection, type SettingsSectionKey } from "@/components/settings/contracts";
import { SettingsFeature } from "@/components/settings/shared/SettingsFeature";
import { SettingsSectionSkeleton } from "@/components/settings/shared/SettingsSectionSkeleton";

import { SkillsCatalogSettings } from "@/components/settings/SkillsCatalogSettings";
import { ImageGenerationSettings } from "@/components/settings/capabilities/ImageGenerationSettings";
import { AdvancedSettings } from "@/components/settings/capabilities/SecuritySettings";
import { TranscriptionSettings } from "@/components/settings/capabilities/TranscriptionSettings";
import { WebSettings } from "@/components/settings/capabilities/WebSettings";
import {
  ModelPresetDeleteDialog,
  ModelsSettings,
} from "@/components/settings/models/ModelsSettings";
import {
  ProviderOAuthLoginDialog,
  ProvidersSettings,
  type ProviderSettingsEntry,
} from "@/components/settings/models/ProviderSettings";
import { providerFormFromRow } from "@/components/settings/models/providerForm";
import { AboutSettings, AppearanceSettings, OverviewSettings } from "@/components/settings/overview/OverviewSettings";
import { NotificationSettings } from "@/components/settings/notifications/NotificationSettings";
import { SettingsSidebar, standaloneSectionTitle } from "@/components/settings/SettingsSidebar";
import {
  NanobotFeatureInstallDialog,
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
  RestartRequiredNotice,
} from "@/components/settings/shared/SettingsControls";
import { AppsCatalogSettings } from "@/components/settings/system/AppsSettings";
import {
  AutomationDeleteDialog,
  AutomationEditDialog,
  AutomationsSettings,
} from "@/components/settings/system/AutomationsSettings";
import { ChannelsSettings } from "@/components/settings/system/ChannelsSettings";
import { RUNTIME_CONFIG_FIELDS, type RuntimeConfigPage } from "@/components/settings/system/runtime-config-fields";
import { RuntimeConfigSettings } from "@/components/settings/system/RuntimeConfigSettings";
import { RuntimeSettings } from "@/components/settings/system/RuntimeSettings";
import type { SettingsController } from "@/components/settings/useSettingsController";
import type { SendAttachment, SendOptions } from "@/hooks/useNanobotStream";
import type { ChatSummary, SessionAutomationJob, SkillSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SettingsPageProps {
  registerExitGuard?: (guard: SettingsExitGuard | null) => void;
  controller: SettingsController;
  theme: "light" | "dark";
  showSidebar: boolean;
  mainNavigationExpanded: boolean;
  onToggleTheme: () => void;
  onBackToChat: () => void;
  skills: SkillSummary[];
  skillsLoading: boolean;
  skillsError: boolean;
  onStartAutomationChat?: (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
    modelPreset?: string | null,
  ) => boolean | void | Promise<boolean | void>;
  titleOverrides?: Record<string, string>;
  sessions?: ChatSummary[];
  onLogout?: () => void;
  isRestarting: boolean;
  hostChromeInset: boolean;
}

export function SettingsPage({
  registerExitGuard,
  controller,
  theme,
  showSidebar,
  mainNavigationExpanded,
  onToggleTheme,
  onBackToChat,
  skills,
  skillsLoading,
  skillsError,
  onStartAutomationChat,
  titleOverrides,
  sessions,
  onLogout,
  isRestarting,
  hostChromeInset,
}: SettingsPageProps) {
  const [dialogLayoutAnchor, setDialogLayoutAnchor] = useState<HTMLDivElement | null>(null);
  const [mcpSetupName, setMcpSetupName] = useState<string | null>(null);
  const presetDeletedCallback = useRef<(() => void) | null>(null);
  const [providerPanel, setProviderPanel] = useState<ProviderSettingsEntry | null>(null);
  const providerSetupOrigin = useRef<{
    trigger: HTMLButtonElement | null;
    onAdded?: (provider: string) => void;
  } | null>(null);
  const [pendingExit, setPendingExit] = useState<(() => void) | null>(null);
  const [automationDetailReturn, setAutomationDetailReturn] =
    useState<SessionAutomationJob | null>(null);
  const {
    modelState,
    modelActions,
    capabilityState,
    capabilityActions,
    systemState,
    systemActions,
    activeSection,
    closeProviderOAuthFlow,
    error,
    featureCatalog,
    hostEngineApplying,
    imageGenerationDirty,
    loading,
    localPrefs,
    modelDirty,
    networkSafetyDirty,
    pendingRestartSections: controllerPendingRestartSections,
    remoteBrowserAccess,
    restartViaSettingsSurface,
    selectSection,
    setLocalPrefs,
    settings,
    t,
    token,
    transcriptionDirty,
  } = controller;
  const { providerOAuthFlow } = modelState;

  const restartInProgress = isRestarting || hostEngineApplying;
  const requestExit = useCallback<SettingsExitGuard>((leave) => {
    if (settings?.requires_restart && !restartInProgress) setPendingExit(() => leave);
    else leave();
  }, [settings?.requires_restart, restartInProgress]);
  useEffect(() => {
    registerExitGuard?.(requestExit);
    return () => registerExitGuard?.(null);
  }, [registerExitGuard, requestExit]);
  const backToChat = () => registerExitGuard ? onBackToChat() : requestExit(onBackToChat);
  const pendingRestartSections = showSidebar
    ? { runtime: false, image: false, browser: false }
    : controllerPendingRestartSections;

  const runtimeConfiguration = (page: RuntimeConfigPage) => settings && (
    <RuntimeConfigSettings page={page} settings={settings} state={controller.runtimeConfigState}
      onRestart={showSidebar ? undefined : restartViaSettingsSurface} isRestarting={restartInProgress}
      remoteBrowserAccess={remoteBrowserAccess}>
      {page === "advanced" ? (
        <AdvancedSettings
          error={capabilityState.capabilityErrors.safety}
          form={capabilityState.networkSafetyForm}
          dirty={networkSafetyDirty}
          saving={capabilityState.networkSafetySaving}
          isNativeHostSurface={(settings.surface ?? settings.runtime_surface) === "native"}
          onChangeForm={capabilityState.setNetworkSafetyForm}
          onSave={capabilityActions.saveNetworkSafetySettings}
          onRestart={restartViaSettingsSurface}
          isRestarting={restartInProgress}
          requiresRestartPending={pendingRestartSections.runtime}
        />
      ) : null}
    </RuntimeConfigSettings>
  );

  const renderSettingsSection = (section: SettingsSectionKey, embedded = false): ReactNode => {
    if (!settings) return null;
    switch (section) {
      case "capabilities": {
        const state = controller.runtimeConfigState;
        const toggleRuntime = (path: string, enabled: boolean) => {
          const field = RUNTIME_CONFIG_FIELDS.find((item) => item.path === path);
          if (field) state.change(field, enabled);
        };
        return (
          <section className="settings-stack">
            <div className="settings-section-heading">
              <SettingsSectionTitle>{t("settings.nav.capabilities")}</SettingsSectionTitle>
              {!showSidebar && settings.requires_restart ? <RestartRequiredNotice message={t("settings.status.savedRestartApply")}
                onRestart={restartViaSettingsSurface} isRestarting={restartInProgress} /> : null}
            </div>
            <SettingsFeature title={t("settings.rows.imageGeneration")} enabled={capabilityState.imageGenerationForm.enabled}
              error={capabilityState.imageGenerationForm.enabled && !settings.image_generation.providers.find((provider) => provider.name === capabilityState.imageGenerationForm.provider)?.configured
                ? t("settings.image.missingCredential") : capabilityState.capabilityErrors.image}
              disabled={restartInProgress || capabilityState.imageGenerationSaving} initialOpen={activeSection === "image"}
              onChange={(enabled) => capabilityState.setImageGenerationForm((prev) => ({ ...prev, enabled }))}>
              {renderSection("image", true)}
            </SettingsFeature>
            <SettingsFeature title={t("settings.rows.transcription")} enabled={capabilityState.transcriptionForm.enabled}
              error={capabilityState.capabilityErrors.voice}
              disabled={restartInProgress || capabilityState.transcriptionSaving} initialOpen={activeSection === "voice"}
              onChange={(enabled) => capabilityState.setTranscriptionForm((prev) => ({ ...prev, enabled }))}>
              {renderSection("voice", true)}
            </SettingsFeature>
            <SettingsFeature title={t("settings.runtimeConfig.groups.web.title")}
              enabled={settings.runtime_config ? state.value("tools.web.enable") === true : settings.web.enable}
              disabled={restartInProgress || state.saving === "web" || !settings.runtime_config}
              initialOpen={activeSection === "browser"} error={state.errors.web || capabilityState.capabilityErrors.web}
              onChange={(enabled) => toggleRuntime("tools.web.enable", enabled)}>
              {renderSection("browser", true)}
            </SettingsFeature>
            <SettingsFeature title={t("settings.runtimeConfig.fields.agents_defaults_dream_enabled.label")}
              enabled={state.value("agents.defaults.dream.enabled") === true}
              disabled={restartInProgress || state.saving === "memory" || !settings.runtime_config} error={state.errors.memory}
              onChange={(enabled) => toggleRuntime("agents.defaults.dream.enabled", enabled)} />
            {!settings.runtime_config ? <p className="settings-list-inset text-[13px] text-muted-foreground">{t("settings.runtimeConfig.unavailable")}</p> : null}
          </section>
        );
      }
      case "overview":
        return (
          <OverviewSettings
            settings={settings}
            showBrandLogos={localPrefs.brandLogos}
            onSelectSection={selectSection}
          />
        );
      case "about":
        return <AboutSettings settings={settings} />;
      case "notifications":
        return <NotificationSettings localPrefs={localPrefs} onChangeLocalPrefs={setLocalPrefs} />;
      case "appearance":
        return (
          <AppearanceSettings
            theme={theme}
            onToggleTheme={onToggleTheme}
            localPrefs={localPrefs}
            onChangeLocalPrefs={setLocalPrefs}
          />
        );
      case "models":
        return (
          <div className="settings-stack">
            <ModelsSettings
              token={token}
              form={modelState.form}
              setForm={modelState.setForm}
              editingPresetName={modelState.modelPresetEditingName}
              presetNameError={modelState.modelPresetNameError}
              settings={settings}
              dirty={modelDirty}
              creating={modelState.modelPresetCreating}
              creatingSaving={modelState.modelConfigurationSaving}
              callOrder={modelState.modelCallOrder}
              saving={modelState.saving}
              orderSaving={modelState.modelCallOrderSaving || modelState.modelConfigurationSaving}
              migrationSaving={modelState.modelMigrationSaving}
              showBrandLogos={localPrefs.brandLogos}
              providerSaving={modelState.providerOperation?.action === "login" ? modelState.providerSaving : null}
              onChangeCallOrder={modelActions.changeModelCallOrder}
              onProviderOAuthLogin={(provider) => modelActions.runProviderOAuth(provider, "login")}
              onAddProvider={(trigger, onAdded) => {
                providerSetupOrigin.current = { trigger, onAdded };
                setProviderPanel({ kind: "add" });
              }}
              onConfigureProvider={(provider, trigger) => {
                providerSetupOrigin.current = { trigger };
                modelActions.resetProviderDraft(provider);
                setProviderPanel({ kind: "edit", provider });
              }}
              onManageProviders={(trigger) => {
                providerSetupOrigin.current = { trigger };
                setProviderPanel({ kind: "manage" });
              }}
              onSave={modelActions.saveModelSettings}
              onSaveRequestSettings={modelActions.saveModelRequestSettings}
              onMigrate={modelActions.handleMigrateModelConfigurations}
              onBeginCreate={modelActions.beginModelPresetCreation}
              onCancelCreate={modelActions.cancelModelPresetCreation}
              onClearPresetNameError={() => modelState.setModelPresetNameError(null)}
              onSelectConfiguration={(name) => {
                modelState.setModelPresetCreating(false);
                modelState.setModelPresetEditingName(name);
                modelState.setModelPresetNameError(null);
                modelState.modelPresetBeforeCreateRef.current = null;
              }}
              onDeleteConfiguration={(preset, onDeleted) => {
                presetDeletedCallback.current = onDeleted;
                modelState.setModelPresetPendingDelete(preset);
              }}
            />
            {providerPanel ? <ProvidersSettings
              entry={providerPanel}
              onClose={() => setProviderPanel(null)}
              onProviderAdded={providerSetupOrigin.current?.onAdded
                ? (provider) => providerSetupOrigin.current?.onAdded?.(provider)
                : undefined}
              onCloseAutoFocus={(event) => {
                if (providerSetupOrigin.current) {
                  event.preventDefault();
                  providerSetupOrigin.current.trigger?.focus({ preventScroll: true });
                  providerSetupOrigin.current = null;
                }
              }}
              settings={settings}
              nanobotFeatures={systemState.nanobotFeatures}
              featureAction={systemState.nanobotFeatureAction}
              capabilityError={systemState.nanobotFeaturesError}
              providerForms={modelState.providerForms}
              visibleProviderKeys={modelState.visibleProviderKeys}
              editingProviderKeys={modelState.editingProviderKeys}
              providerSaving={modelState.providerSaving}
              showBrandLogos={localPrefs.brandLogos}
              remoteBrowserAccess={remoteBrowserAccess}
              onResetProviderDraft={modelActions.resetProviderDraft}
              onToggleProviderKey={modelActions.toggleProviderKeyVisibility}
              onToggleProviderKeyEditing={modelActions.toggleProviderKeyEditing}
              onChangeProviderForm={(provider, value) => {
                const row = settings.providers.find((item) => item.name === provider);
                if (!row) return;
                modelState.setProviderForms((prev) => ({
                  ...prev,
                  [provider]: {
                    ...(prev[provider] ?? providerFormFromRow(row)),
                    ...value,
                  },
                }));
              }}
              onSaveProvider={modelActions.saveProvider}
              onCreateCustomProvider={modelActions.createCustomProvider}
              providerOperation={modelState.providerOperation}
              onProviderOAuthLogin={(provider) => modelActions.runProviderOAuth(provider, "login")}
              onProviderOAuthLogout={(provider) => modelActions.runProviderOAuth(provider, "logout")}
            /> : null}
          </div>
        );
      case "image":
        return (
          <div className="settings-stack">
            <ImageGenerationSettings
              error={capabilityState.capabilityErrors.image}
              embedded={embedded}
              token={token}
              settings={settings}
              form={capabilityState.imageGenerationForm}
              dirty={imageGenerationDirty}
              saving={capabilityState.imageGenerationSaving}
              onChangeForm={capabilityState.setImageGenerationForm}
              onSave={capabilityActions.saveImageGenerationSettings}
              onSaveRequestSettings={capabilityActions.saveImageRequestSettings}
              onOpenProviders={() => selectSection("models")}
              showBrandLogos={localPrefs.brandLogos}
              onRestart={restartViaSettingsSurface}
              isRestarting={restartInProgress}
              requiresRestartPending={pendingRestartSections.image}
            >
              {capabilityState.imageGenerationForm.enabled ? runtimeConfiguration("image") : null}
            </ImageGenerationSettings>
          </div>
        );
      case "voice":
        return (
          <TranscriptionSettings
            error={capabilityState.capabilityErrors.voice}
            embedded={embedded}
            settings={settings}
            form={capabilityState.transcriptionForm}
            dirty={transcriptionDirty}
            saving={capabilityState.transcriptionSaving}
            onChangeForm={capabilityState.setTranscriptionForm}
            onSave={capabilityActions.saveTranscriptionSettings}
            onOpenProviders={() => selectSection("models")}
            showBrandLogos={localPrefs.brandLogos}
            onRestart={restartViaSettingsSurface}
            isRestarting={restartInProgress}
            requiresRestartPending={pendingRestartSections.browser}
          />
        );
      case "browser":
        return (
          <div className="settings-stack">
            {!embedded ? runtimeConfiguration("browser") : null}
            <WebSettings
              error={capabilityState.capabilityErrors.web || controller.runtimeConfigState.errors.web}
              embedded={embedded}
              enabled={settings.runtime_config
                ? controller.runtimeConfigState.value("tools.web.enable") !== false
                : settings.web.enable}
              settings={settings}
              form={capabilityState.webSearchForm}
              keyVisible={capabilityState.webSearchKeyVisible}
              keyEditing={capabilityState.webSearchKeyEditing}
              saving={capabilityState.webSearchSaving}
              onChangeForm={capabilityState.setWebSearchForm}
              onChangeProvider={capabilityActions.handleWebSearchProviderChange}
              onToggleKey={() => capabilityState.setWebSearchKeyVisible((visible) => !visible)}
              onToggleKeyEditing={() => {
                capabilityState.setWebSearchKeyEditing((editing) => !editing);
                capabilityState.setWebSearchKeyVisible(false);
                capabilityState.setWebSearchForm((prev) => ({ ...prev, apiKey: "" }));
              }}
              onReset={capabilityActions.resetWebSearchDraft}
              onSave={capabilityActions.saveWebSearch}
              showBrandLogos={localPrefs.brandLogos}
              onRestart={restartViaSettingsSurface}
              isRestarting={restartInProgress}
              requiresRestartPending={pendingRestartSections.browser}
              olostepFeature={featureCatalog.find((feature) => feature.name === "olostep")}
              olostepInstalling={systemState.nanobotFeatureAction === "enable:olostep"}
              capabilityError={systemState.nanobotFeaturesError}
            >
              {settings.runtime_config ? runtimeConfiguration("network") : null}
            </WebSettings>
          </div>
        );
      case "runtime":
        return (
          <div className="settings-stack">
            {runtimeConfiguration("runtime")}
            <RuntimeSettings
              form={modelState.form}
              settings={settings}
              onRestart={showSidebar ? undefined : restartViaSettingsSurface}
              isRestarting={restartInProgress}
              requiresRestartPending={pendingRestartSections.runtime}
              apiService={systemState.apiService}
              apiServiceLoading={systemState.apiServiceLoading}
              apiServiceAction={systemState.apiServiceAction}
              apiServiceError={systemState.apiServiceError}
              langfuseFeature={featureCatalog.find((feature) => feature.name === "langfuse")}
              capabilitiesLoading={systemState.nanobotFeaturesLoading}
              capabilityAction={systemState.nanobotFeatureAction}
              capabilityError={systemState.nanobotFeaturesError}
              onApiServiceAction={systemActions.handleApiServiceAction}
              onInstallCapability={(name) => void systemActions.installCapabilities([name])}
            />
          </div>
        );
      case "memory":
        return runtimeConfiguration("memory");
      case "advanced":
        return runtimeConfiguration("advanced");
      default:
        return null;
    }
  };

  const renderSection = (section: SettingsSectionKey, embedded = false): ReactNode => {
    switch (section) {
      case "channels":
        return (
          <ChannelsSettings
            onConfigureMcp={(name) => {
              setMcpSetupName(name);
              systemState.setAppsKindFilter("mcp");
              systemState.setAppsQuery(name);
              selectSection("apps");
            }}
            token={token}
            nanobotFeatures={systemState.nanobotFeatures}
            loading={systemState.nanobotFeaturesLoading}
            actionKey={systemState.nanobotFeatureAction}
            chatAppsDocsUrl={settings?.docs?.chat_apps_url}
            showBrandLogos={localPrefs.brandLogos}
            error={systemState.nanobotFeaturesError}
            requiresRestartPending={pendingRestartSections.runtime}
            onAction={systemActions.handleNanobotFeatureAction}
            onFeaturesUpdate={systemState.setNanobotFeatures}
            onDismissStatus={() => {
              systemState.setNanobotFeaturesError(null);
            }}
            onRestart={restartViaSettingsSurface}
            isRestarting={restartInProgress}
          />
        );
      case "apps":
        return (
          <div className="settings-stack">
            <AppsCatalogSettings
              setupName={mcpSetupName}
              onSetupOpened={() => setMcpSetupName(null)}
              cliApps={systemState.cliApps}
              mcpPresets={systemState.mcpPresets}
              cliAppsLoading={systemState.cliAppsLoading}
              mcpPresetsLoading={systemState.mcpPresetsLoading}
              query={systemState.appsQuery}
              filter={systemState.appsKindFilter}
              cliActionKey={systemState.cliAppsAction}
              mcpActionKey={systemState.mcpPresetAction}
              mcpOAuthFlow={systemState.mcpOAuthFlow}
              mcpOAuthPopupBlocked={systemState.mcpOAuthPopupBlocked}
              mcpOAuthCallbackUrl={systemState.mcpOAuthCallbackUrl}
              mcpOAuthCompleting={systemState.mcpOAuthCompleting}
              mcpOAuthCallbackError={systemState.mcpOAuthCallbackError}
              cliMessage={systemState.cliAppsMessage}
              cliError={systemState.cliAppsError}
              cliFocusName={systemState.cliAppsFocusName}
              mcpMessage={systemState.mcpMessage}
              mcpError={systemState.mcpError}
              mcpFieldValues={systemState.mcpFieldValues}
              customMcpForm={systemState.customMcpForm}
              mcpConfigImport={systemState.mcpConfigImport}
              showBrandLogos={localPrefs.brandLogos}
              requiresRestartPending={pendingRestartSections.runtime}
              onQueryChange={systemState.setAppsQuery}
              onFilterChange={systemState.setAppsKindFilter}
              onCliAction={systemActions.handleCliAppAction}
              onMcpAction={systemActions.handleMcpPresetAction}
              onMcpOAuthConnect={systemActions.handleMcpOAuthConnect}
              onMcpOAuthCancel={() => void systemActions.handleMcpOAuthCancel()}
              onMcpOAuthOpen={systemActions.handleMcpOAuthOpen}
              onMcpOAuthCallbackUrlChange={(value) => {
                systemState.setMcpOAuthCallbackUrl(value);
                systemState.setMcpOAuthCallbackError(null);
              }}
              onMcpOAuthComplete={() => void systemActions.handleMcpOAuthComplete()}
              onDismissStatus={() => {
                systemState.setCliAppsMessage(null);
                systemState.setCliAppsError(null);
                systemState.setMcpMessage(null);
                systemState.setMcpError(null);
              }}
              onBackToChat={onBackToChat}
              onMcpFieldChange={(presetName, fieldName, value) => {
                systemState.setMcpFieldValues((prev) => ({
                  ...prev,
                  [presetName]: {
                    ...(prev[presetName] ?? {}),
                    [fieldName]: value,
                  },
                }));
              }}
              onCustomMcpFormChange={systemState.setCustomMcpForm}
              onMcpConfigImportChange={systemState.setMcpConfigImport}
              onSaveCustomMcp={systemActions.handleSaveCustomMcp}
              onImportMcpConfig={systemActions.handleImportMcpConfig}
              onMcpToolsChange={systemActions.handleMcpToolsChange}
              onRestart={restartViaSettingsSurface}
              isRestarting={restartInProgress}
            />
          </div>
        );
      case "automations":
        return (
          <div className="settings-stack">
            <AutomationsSettings
              token={token}
              payload={systemState.automations}
              titleOverrides={titleOverrides}
              sessions={sessions}
              settingsSnapshot={controller.settings}
              onStartChat={onStartAutomationChat}
              loading={systemState.automationsLoading}
              filter={systemState.automationsFilter}
              actionKey={systemState.automationAction}
              error={systemState.automationsError}
              onFilterChange={systemState.setAutomationsFilter}
              onAction={systemActions.handleAutomationAction}
              onRequestEdit={(job) => {
                setAutomationDetailReturn(null);
                systemState.setAutomationPendingEdit(job);
              }}
              onRequestDelete={systemState.setAutomationPendingDelete}
              onChangeChat={systemActions.handleAutomationChat}
              onManageModels={() => selectSection("models")}
              returnToDetailJob={automationDetailReturn}
              onReturnToDetailHandled={() => setAutomationDetailReturn(null)}
            />
          </div>
        );
      case "skills":
        return <SkillsCatalogSettings skills={skills} loading={skillsLoading} error={skillsError} />;
      default:
        return renderSettingsSection(section, embedded);
    }
  };
  const sectionReady = settings !== null || activeSection === "skills" || activeSection === "apps"
    || activeSection === "channels" || activeSection === "automations";

  return (
    <DialogLayoutContext.Provider value={dialogLayoutAnchor}>
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-settings-canvas lg:flex-row">
      <Dialog open={pendingExit !== null} onOpenChange={(open) => { if (!open) setPendingExit(null); }}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("settings.exit.title")}</DialogTitle>
            <DialogDescription>{t("settings.exit.description")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => { const leave = pendingExit; setPendingExit(null); leave?.(); }}>{t("settings.exit.later")}</Button>
            <Button onClick={() => { setPendingExit(null); void restartViaSettingsSurface(); }}>{t("app.system.restartAction")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {showSidebar ? (
        <SettingsSidebar
          activeSection={activeSection}
          onSelectSection={selectSection}
          onBackToChat={backToChat}
          onLogout={onLogout ? () => requestExit(onLogout) : undefined}
          hostChromeInset={hostChromeInset}
          onRestart={settings ? restartViaSettingsSurface : undefined}
          isRestarting={restartInProgress}
          restartPending={settings?.requires_restart}
          isNativeHost={(settings?.surface ?? settings?.runtime_surface) === "native"}
        />
      ) : null}

      <ModelPresetDeleteDialog
        preset={modelState.modelPresetPendingDelete}
        deleting={modelState.saving}
        onOpenChange={(open) => {
          if (!open) {
            modelState.setModelPresetPendingDelete(null);
            presetDeletedCallback.current = null;
          }
        }}
        onConfirm={async () => {
          if (await modelActions.handleDeleteModelConfiguration()) {
            presetDeletedCallback.current?.();
            presetDeletedCallback.current = null;
          }
        }}
      />

      <ProviderOAuthLoginDialog
        flow={providerOAuthFlow}
        providerLabel={
          providerOAuthFlow
            ? settings?.providers.find((provider) => provider.name === providerOAuthFlow.provider)
              ?.label ?? providerOAuthFlow.provider
            : ""
        }
        authorizationResponse={modelState.providerOAuthResponse}
        completing={modelState.providerOAuthCompleting}
        error={modelState.providerOAuthDialogError}
        remoteBrowserAccess={remoteBrowserAccess}
        onAuthorizationResponseChange={(value) => {
          modelState.setProviderOAuthResponse(value);
          modelState.setProviderOAuthDialogError(null);
        }}
        onOpenAuthorization={() => {
          if (!providerOAuthFlow) return;
          const opened = window.open(
            providerOAuthFlow.authorization_url,
            "_blank",
            "noopener,noreferrer",
          );
          if (opened) opened.opener = null;
        }}
        onComplete={() => void modelActions.completeProviderOAuthResponse()}
        onClose={closeProviderOAuthFlow}
      />

      <NanobotFeatureInstallDialog
        feature={systemState.nanobotFeatureConfirm?.feature ?? null}
        installOnly={systemState.nanobotFeatureConfirm?.installOnly ?? false}
        installing={systemState.nanobotFeatureAction === `${systemState.nanobotFeatureConfirm?.installOnly ? "install" : "enable"}:${systemState.nanobotFeatureConfirm?.feature.name ?? ""}`}
        onOpenChange={(open) => {
          if (!open) systemState.setNanobotFeatureConfirm(null);
        }}
        onConfirm={(feature) => systemActions.handleNanobotFeatureAction("enable", feature.name, {
          confirmed: true,
          installOnly: systemState.nanobotFeatureConfirm?.installOnly,
        })}
      />

      <AutomationDeleteDialog
        job={systemState.automationPendingDelete}
        deleting={systemState.automationAction === `delete:${systemState.automationPendingDelete?.id ?? ""}`}
        onOpenChange={(open) => {
          if (!open) systemState.setAutomationPendingDelete(null);
        }}
        onConfirm={(job) => systemActions.handleAutomationAction("delete", job)}
      />

      <AutomationEditDialog
        job={systemState.automationPendingEdit}
        saving={systemState.automationAction === `update:${systemState.automationPendingEdit?.id ?? ""}`}
        onOpenChange={(open) => {
          if (!open) systemState.setAutomationPendingEdit(null);
        }}
        onCancel={(job) => setAutomationDetailReturn(job)}
        onSave={systemActions.handleAutomationEdit}
      />

      <div
        className={cn(
          "min-w-0 flex-1 bg-settings-canvas [scrollbar-gutter:stable]",
          "overflow-y-auto",
        )}
      >
        <div
          key={activeSection}
          data-testid="settings-section-transition"
          ref={setDialogLayoutAnchor}
          data-settings-section={activeSection}
          data-main-navigation-expanded={mainNavigationExpanded}
          className={cn(
            "mx-auto w-full animate-in fade-in-0 slide-in-from-bottom-1 py-6 duration-200 ease-out",
            "motion-reduce:animate-none sm:py-8 lg:py-12",
            "settings-grid",
            activeSection === "about" && "flex min-h-full flex-col",
            !showSidebar && "settings-feature-page",
            !showSidebar && activeSection === "automations" && "settings-automations-grid",
            hostChromeInset && "pt-[4.25rem] sm:pt-[4.25rem] lg:pt-[4.75rem]",
          )}
        >
          {!showSidebar ? (
            <div className={activeSection === "automations" ? "lg:hidden" : "settings-feature-header mb-7"}>
              <button
                type="button"
                onClick={backToChat}
                className="touch-target mb-4 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors settings-hover hover:text-foreground lg:hidden"
              >
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
                {t("settings.backToChat")}
              </button>
              {activeSection !== "automations" ? <h1 className="text-[24px] font-normal leading-tight tracking-normal text-foreground sm:text-[28px]">
                {t(`settings.nav.${activeSection}`, {
                  defaultValue: standaloneSectionTitle(activeSection),
                })}
              </h1> : null}
            </div>
          ) : null}

          {loading && !sectionReady ? (
            <SettingsSectionSkeleton section={activeSection} showRestart={!showSidebar} />
          ) : error && !sectionReady ? (
            <SettingsGroup>
              <SettingsRow title={t("settings.status.loadError")}>
                <span className="max-w-[520px] text-sm text-muted-foreground">{error}</span>
              </SettingsRow>
            </SettingsGroup>
          ) : sectionReady ? (
            <div
              className={cn(
                "settings-stack",
                activeSection === "about" && "flex flex-1 flex-col",
                activeSection === "channels" &&
                  "flex min-h-0 flex-1 flex-col xl:overflow-hidden",
              )}
            >
              {error ? (
                <div className="rounded-floating border border-destructive/20 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">
                  {error}
                </div>
              ) : null}
              {renderSection(isCapabilitySection(activeSection) ? "capabilities" : activeSection)}
            </div>
          ) : null}
        </div>
      </div>
    </div>
    </DialogLayoutContext.Provider>
  );
}
