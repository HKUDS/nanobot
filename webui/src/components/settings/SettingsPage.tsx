import { ChevronLeft, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogLayoutContext, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { SettingsExitGuard } from "@/components/settings/contracts";
import { isCapabilitySection, type SettingsSectionKey } from "@/components/settings/contracts";
import { SettingsFeature } from "@/components/settings/shared/SettingsFeature";

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
  providerFormFromRow,
} from "@/components/settings/models/ProviderSettings";
import { AboutSettings, AppearanceSettings, OverviewSettings } from "@/components/settings/overview/OverviewSettings";
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
import type { SkillSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SettingsPageProps {
  registerExitGuard?: (guard: SettingsExitGuard | null) => void;
  controller: SettingsController;
  theme: "light" | "dark";
  showSidebar: boolean;
  onToggleTheme: () => void;
  onBackToChat: () => void;
  skills: SkillSummary[];
  onLogout?: () => void;
  isRestarting: boolean;
  hostChromeInset: boolean;
}

export function SettingsPage({
  registerExitGuard,
  controller,
  theme,
  showSidebar,
  onToggleTheme,
  onBackToChat,
  skills,
  onLogout,
  isRestarting,
  hostChromeInset,
}: SettingsPageProps) {
  const [dialogLayoutAnchor, setDialogLayoutAnchor] = useState<HTMLDivElement | null>(null);
  const [pendingExit, setPendingExit] = useState<(() => void) | null>(null);
  const {
    activeSection,
    apiService,
    apiServiceAction,
    apiServiceError,
    apiServiceLoading,
    appsKindFilter,
    appsQuery,
    automationAction,
    automationPendingDelete,
    automationPendingEdit,
    automations,
    automationsError,
    automationsFilter,
    automationsLoading,
    automationsQuery,
    automationsSort,
    beginModelPresetCreation,
    cancelModelPresetCreation,
    changeModelCallOrder,
    cliApps,
    cliAppsAction,
    cliAppsError,
    cliAppsFocusName,
    cliAppsLoading,
    cliAppsMessage,
    closeProviderOAuthFlow,
    completeProviderOAuthResponse,
    createCustomProvider,
    customMcpForm,
    editingProviderKeys,
    error,
    expandedProvider,
    featureCatalog,
    form,
    handleApiServiceAction,
    handleAutomationAction,
    handleAutomationEdit,
    handleCliAppAction,
    handleDeleteModelConfiguration,
    handleImportMcpConfig,
    handleMcpOAuthCancel,
    handleMcpOAuthComplete,
    handleMcpOAuthConnect,
    handleMcpOAuthOpen,
    handleMcpPresetAction,
    handleMcpToolsChange,
    handleMigrateModelConfigurations,
    handleNanobotFeatureAction,
    handleSaveCustomMcp,
    handleToggleProvider,
    handleWebSearchProviderChange,
    hostEngineApplying,
    imageGenerationDirty,
    imageGenerationForm,
    imageGenerationSaving,
    installCapabilities,
    loading,
    localPrefs,
    mcpConfigImport,
    mcpError,
    mcpFieldValues,
    mcpMessage,
    mcpOAuthCallbackError,
    mcpOAuthCallbackUrl,
    mcpOAuthCompleting,
    mcpOAuthFlow,
    mcpOAuthPopupBlocked,
    mcpPresetAction,
    mcpPresets,
    mcpPresetsLoading,
    modelCallOrder,
    modelCallOrderSaving,
    modelConfigurationSaving,
    modelDirty,
    modelMigrationSaving,
    modelPresetBeforeCreateRef,
    modelPresetCreating,
    modelPresetEditingName,
    modelPresetNameError,
    modelPresetPendingDelete,
    nanobotFeatureAction,
    nanobotFeatureConfirm,
    nanobotFeatures,
    nanobotFeaturesError,
    nanobotFeaturesLoading,
    networkSafetyDirty,
    networkSafetyForm,
    networkSafetySaving,
    pendingRestartSections: controllerPendingRestartSections,
    providerForms,
    providerOAuthCompleting,
    providerOAuthDialogError,
    providerOAuthFlow,
    providerOAuthResponse,
    providerSaving,
    remoteBrowserAccess,
    resetWebSearchDraft,
    restartViaSettingsSurface,
    runProviderOAuth,
    saveImageGenerationSettings,
    saveModelSettings,
    saveNetworkSafetySettings,
    saveProvider,
    saveTranscriptionSettings,
    saveWebSearch,
    saving,
    selectSection,
    setAppsKindFilter,
    setAppsQuery,
    setAutomationPendingDelete,
    setAutomationPendingEdit,
    setAutomationsFilter,
    setAutomationsQuery,
    setAutomationsSort,
    setCliAppsError,
    setCliAppsMessage,
    setCustomMcpForm,
    setForm,
    setImageGenerationForm,
    setLocalPrefs,
    setMcpConfigImport,
    setMcpError,
    setMcpFieldValues,
    setMcpMessage,
    setMcpOAuthCallbackError,
    setMcpOAuthCallbackUrl,
    setModelPresetCreating,
    setModelPresetEditingName,
    setModelPresetNameError,
    setModelPresetPendingDelete,
    setNanobotFeatureConfirm,
    setNanobotFeatures,
    setNanobotFeaturesError,
    setNetworkSafetyForm,
    setProviderForms,
    setProviderOAuthDialogError,
    setProviderOAuthResponse,
    setTranscriptionForm,
    setWebSearchForm,
    setWebSearchKeyEditing,
    setWebSearchKeyVisible,
    settings,
    t,
    toggleProviderKeyEditing,
    toggleProviderKeyVisibility,
    token,
    transcriptionDirty,
    transcriptionForm,
    transcriptionSaving,
    visibleProviderKeys,
    webSearchForm,
    webSearchKeyEditing,
    webSearchKeyVisible,
    webSearchSaving,
  } = controller;

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
          error={controller.capabilityErrors.safety}
          form={networkSafetyForm}
          dirty={networkSafetyDirty}
          saving={networkSafetySaving}
          isNativeHostSurface={(settings.surface ?? settings.runtime_surface) === "native"}
          onChangeForm={setNetworkSafetyForm}
          onSave={saveNetworkSafetySettings}
          onRestart={restartViaSettingsSurface}
          isRestarting={restartInProgress}
          requiresRestartPending={pendingRestartSections.runtime}
        />
      ) : null}
    </RuntimeConfigSettings>
  );

  const renderSection = (section: SettingsSectionKey, embedded = false): ReactNode => {
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
            <SettingsFeature title={t("settings.rows.imageGeneration")} enabled={imageGenerationForm.enabled}
              error={imageGenerationForm.enabled && !settings.image_generation.providers.find((provider) => provider.name === imageGenerationForm.provider)?.configured
                ? t("settings.image.missingCredential") : controller.capabilityErrors.image}
              disabled={restartInProgress || imageGenerationSaving} initialOpen={activeSection === "image"}
              onChange={(enabled) => setImageGenerationForm((prev) => ({ ...prev, enabled }))}>
              {renderSection("image", true)}
            </SettingsFeature>
            <SettingsFeature title={t("settings.rows.transcription")} enabled={transcriptionForm.enabled}
              error={controller.capabilityErrors.voice}
              disabled={restartInProgress || transcriptionSaving} initialOpen={activeSection === "voice"}
              onChange={(enabled) => setTranscriptionForm((prev) => ({ ...prev, enabled }))}>
              {renderSection("voice", true)}
            </SettingsFeature>
            <SettingsFeature title={t("settings.runtimeConfig.groups.web.title")}
              enabled={settings.runtime_config ? state.value("tools.web.enable") === true : settings.web.enable}
              disabled={restartInProgress || state.saving === "web" || !settings.runtime_config}
              initialOpen={activeSection === "browser"} error={state.errors.web || controller.capabilityErrors.web}
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
        return <AboutSettings currentVersion={settings.version?.current} />;
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
              form={form}
              setForm={setForm}
              editingPresetName={modelPresetEditingName}
              presetNameError={modelPresetNameError}
              settings={settings}
              dirty={modelDirty}
              creating={modelPresetCreating}
              creatingSaving={modelConfigurationSaving}
              callOrder={modelCallOrder}
              saving={saving}
              orderSaving={modelCallOrderSaving || modelConfigurationSaving}
              migrationSaving={modelMigrationSaving}
              showBrandLogos={localPrefs.brandLogos}
              providerSaving={providerSaving}
              onChangeCallOrder={changeModelCallOrder}
              onProviderOAuthLogin={(provider) => runProviderOAuth(provider, "login")}
              onSave={saveModelSettings}
              onMigrate={handleMigrateModelConfigurations}
              onBeginCreate={beginModelPresetCreation}
              onCancelCreate={cancelModelPresetCreation}
              onClearPresetNameError={() => setModelPresetNameError(null)}
              onSelectConfiguration={(name) => {
                setModelPresetCreating(false);
                setModelPresetEditingName(name);
                setModelPresetNameError(null);
                modelPresetBeforeCreateRef.current = null;
              }}
              onDeleteConfiguration={setModelPresetPendingDelete}
            />
            <ProvidersSettings
              settings={settings}
              nanobotFeatures={nanobotFeatures}
              featureAction={nanobotFeatureAction}
              capabilityError={nanobotFeaturesError}
              expandedProvider={expandedProvider}
              providerForms={providerForms}
              visibleProviderKeys={visibleProviderKeys}
              editingProviderKeys={editingProviderKeys}
              providerSaving={providerSaving}
              showBrandLogos={localPrefs.brandLogos}
              remoteBrowserAccess={remoteBrowserAccess}
              onToggleProvider={handleToggleProvider}
              onToggleProviderKey={toggleProviderKeyVisibility}
              onToggleProviderKeyEditing={toggleProviderKeyEditing}
              onChangeProviderForm={(provider, value) =>
                setProviderForms((prev) => ({
                  ...prev,
                  [provider]: {
                    ...(prev[provider] ?? providerFormFromRow(
                      settings.providers.find((row) => row.name === provider) ?? {
                        name: provider,
                        label: provider,
                        configured: false,
                      },
                    )),
                    ...value,
                  },
                }))
              }
              onSaveProvider={saveProvider}
              onCreateCustomProvider={createCustomProvider}
              onProviderOAuthLogin={(provider) => runProviderOAuth(provider, "login")}
              onProviderOAuthLogout={(provider) => runProviderOAuth(provider, "logout")}
            />
          </div>
        );
      case "image":
        return (
          <div className="settings-stack">
            <ImageGenerationSettings
              error={controller.capabilityErrors.image}
              embedded={embedded}
              token={token}
              settings={settings}
              form={imageGenerationForm}
              dirty={imageGenerationDirty}
              saving={imageGenerationSaving}
              onChangeForm={setImageGenerationForm}
              onSave={saveImageGenerationSettings}
              onOpenProviders={() => selectSection("models")}
              showBrandLogos={localPrefs.brandLogos}
              onRestart={restartViaSettingsSurface}
              isRestarting={restartInProgress}
              requiresRestartPending={pendingRestartSections.image}
            >
              {imageGenerationForm.enabled ? runtimeConfiguration("image") : null}
            </ImageGenerationSettings>
          </div>
        );
      case "voice":
        return (
          <TranscriptionSettings
            error={controller.capabilityErrors.voice}
            embedded={embedded}
            settings={settings}
            form={transcriptionForm}
            dirty={transcriptionDirty}
            saving={transcriptionSaving}
            onChangeForm={setTranscriptionForm}
            onSave={saveTranscriptionSettings}
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
              error={controller.capabilityErrors.web || controller.runtimeConfigState.errors.web}
              embedded={embedded}
              enabled={settings.runtime_config
                ? controller.runtimeConfigState.value("tools.web.enable") !== false
                : settings.web.enable}
              settings={settings}
              form={webSearchForm}
              keyVisible={webSearchKeyVisible}
              keyEditing={webSearchKeyEditing}
              saving={webSearchSaving}
              onChangeForm={setWebSearchForm}
              onChangeProvider={handleWebSearchProviderChange}
              onToggleKey={() => setWebSearchKeyVisible((visible) => !visible)}
              onToggleKeyEditing={() => {
                setWebSearchKeyEditing((editing) => !editing);
                setWebSearchKeyVisible(false);
                setWebSearchForm((prev) => ({ ...prev, apiKey: "" }));
              }}
              onReset={resetWebSearchDraft}
              onSave={saveWebSearch}
              showBrandLogos={localPrefs.brandLogos}
              onRestart={restartViaSettingsSurface}
              isRestarting={restartInProgress}
              requiresRestartPending={pendingRestartSections.browser}
              olostepFeature={featureCatalog.find((feature) => feature.name === "olostep")}
              olostepInstalling={nanobotFeatureAction === "enable:olostep"}
              capabilityError={nanobotFeaturesError}
            />
          </div>
        );
      case "channels":
        return (
          <ChannelsSettings
            token={token}
            nanobotFeatures={nanobotFeatures}
            loading={nanobotFeaturesLoading}
            actionKey={nanobotFeatureAction}
            chatAppsDocsUrl={settings.docs?.chat_apps_url}
            showBrandLogos={localPrefs.brandLogos}
            error={nanobotFeaturesError}
            requiresRestartPending={pendingRestartSections.runtime}
            onAction={handleNanobotFeatureAction}
            onFeaturesUpdate={setNanobotFeatures}
            onDismissStatus={() => {
              setNanobotFeaturesError(null);
            }}
            onRestart={restartViaSettingsSurface}
            isRestarting={restartInProgress}
          />
        );
      case "apps":
        return (
          <div className="settings-stack">
            {runtimeConfiguration("apps")}
            <AppsCatalogSettings
              cliApps={cliApps}
              mcpPresets={mcpPresets}
              cliAppsLoading={cliAppsLoading}
              mcpPresetsLoading={mcpPresetsLoading}
              query={appsQuery}
              filter={appsKindFilter}
              cliActionKey={cliAppsAction}
              mcpActionKey={mcpPresetAction}
              mcpOAuthFlow={mcpOAuthFlow}
              mcpOAuthPopupBlocked={mcpOAuthPopupBlocked}
              mcpOAuthCallbackUrl={mcpOAuthCallbackUrl}
              mcpOAuthCompleting={mcpOAuthCompleting}
              mcpOAuthCallbackError={mcpOAuthCallbackError}
              cliMessage={cliAppsMessage}
              cliError={cliAppsError}
              cliFocusName={cliAppsFocusName}
              mcpMessage={mcpMessage}
              mcpError={mcpError}
              mcpFieldValues={mcpFieldValues}
              customMcpForm={customMcpForm}
              mcpConfigImport={mcpConfigImport}
              showBrandLogos={localPrefs.brandLogos}
              requiresRestartPending={pendingRestartSections.runtime}
              onQueryChange={setAppsQuery}
              onFilterChange={setAppsKindFilter}
              onCliAction={handleCliAppAction}
              onMcpAction={handleMcpPresetAction}
              onMcpOAuthConnect={handleMcpOAuthConnect}
              onMcpOAuthCancel={() => void handleMcpOAuthCancel()}
              onMcpOAuthOpen={handleMcpOAuthOpen}
              onMcpOAuthCallbackUrlChange={(value) => {
                setMcpOAuthCallbackUrl(value);
                setMcpOAuthCallbackError(null);
              }}
              onMcpOAuthComplete={() => void handleMcpOAuthComplete()}
              onDismissStatus={() => {
                setCliAppsMessage(null);
                setCliAppsError(null);
                setMcpMessage(null);
                setMcpError(null);
              }}
              onBackToChat={onBackToChat}
              onMcpFieldChange={(presetName, fieldName, value) => {
                setMcpFieldValues((prev) => ({
                  ...prev,
                  [presetName]: {
                    ...(prev[presetName] ?? {}),
                    [fieldName]: value,
                  },
                }));
              }}
              onCustomMcpFormChange={setCustomMcpForm}
              onMcpConfigImportChange={setMcpConfigImport}
              onSaveCustomMcp={handleSaveCustomMcp}
              onImportMcpConfig={handleImportMcpConfig}
              onMcpToolsChange={handleMcpToolsChange}
              onRestart={restartViaSettingsSurface}
              isRestarting={restartInProgress}
            />
          </div>
        );
      case "automations":
        return (
          <div className="settings-stack">
            <AutomationsSettings
              payload={automations}
              loading={automationsLoading}
              query={automationsQuery}
              filter={automationsFilter}
              sort={automationsSort}
              actionKey={automationAction}
              error={automationsError}
              onQueryChange={setAutomationsQuery}
              onFilterChange={setAutomationsFilter}
              onSortChange={setAutomationsSort}
              onAction={handleAutomationAction}
              onRequestEdit={setAutomationPendingEdit}
              onRequestDelete={setAutomationPendingDelete}
              onBackToChat={onBackToChat}
            />
          </div>
        );
      case "skills":
        return <SkillsCatalogSettings skills={skills} />;
      case "runtime":
        return (
          <div className="settings-stack">
            {runtimeConfiguration("runtime")}
            <RuntimeSettings
              form={form}
              settings={settings}
              onRestart={showSidebar ? undefined : restartViaSettingsSurface}
              isRestarting={restartInProgress}
              requiresRestartPending={pendingRestartSections.runtime}
              apiService={apiService}
              apiServiceLoading={apiServiceLoading}
              apiServiceAction={apiServiceAction}
              apiServiceError={apiServiceError}
              langfuseFeature={featureCatalog.find((feature) => feature.name === "langfuse")}
              capabilitiesLoading={nanobotFeaturesLoading}
              capabilityAction={nanobotFeatureAction}
              capabilityError={nanobotFeaturesError}
              onApiServiceAction={handleApiServiceAction}
              onInstallCapability={(name) => void installCapabilities([name])}
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

  return (
    <DialogLayoutContext.Provider value={dialogLayoutAnchor}>
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-settings-canvas lg:flex-row">
      <Dialog open={pendingExit !== null} onOpenChange={(open) => { if (!open) setPendingExit(null); }}>
        <DialogContent>
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
        preset={modelPresetPendingDelete}
        deleting={saving}
        onOpenChange={(open) => {
          if (!open) setModelPresetPendingDelete(null);
        }}
        onConfirm={handleDeleteModelConfiguration}
      />

      <ProviderOAuthLoginDialog
        flow={providerOAuthFlow}
        providerLabel={
          providerOAuthFlow
            ? settings?.providers.find((provider) => provider.name === providerOAuthFlow.provider)
              ?.label ?? providerOAuthFlow.provider
            : ""
        }
        authorizationResponse={providerOAuthResponse}
        completing={providerOAuthCompleting}
        error={providerOAuthDialogError}
        remoteBrowserAccess={remoteBrowserAccess}
        onAuthorizationResponseChange={(value) => {
          setProviderOAuthResponse(value);
          setProviderOAuthDialogError(null);
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
        onComplete={() => void completeProviderOAuthResponse()}
        onClose={closeProviderOAuthFlow}
      />

      <NanobotFeatureInstallDialog
        feature={nanobotFeatureConfirm}
        installing={nanobotFeatureAction === `enable:${nanobotFeatureConfirm?.name ?? ""}`}
        onOpenChange={(open) => {
          if (!open) setNanobotFeatureConfirm(null);
        }}
        onConfirm={(feature) => handleNanobotFeatureAction("enable", feature.name, true)}
      />

      <AutomationDeleteDialog
        job={automationPendingDelete}
        deleting={automationAction === `delete:${automationPendingDelete?.id ?? ""}`}
        onOpenChange={(open) => {
          if (!open) setAutomationPendingDelete(null);
        }}
        onConfirm={(job) => handleAutomationAction("delete", job)}
      />

      <AutomationEditDialog
        job={automationPendingEdit}
        saving={automationAction === `update:${automationPendingEdit?.id ?? ""}`}
        onOpenChange={(open) => {
          if (!open) setAutomationPendingEdit(null);
        }}
        onSave={handleAutomationEdit}
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
          className={cn(
            "mx-auto w-full animate-in fade-in-0 slide-in-from-bottom-1 py-6 duration-200 ease-out",
            "motion-reduce:animate-none sm:py-8 lg:py-12",
            "settings-grid",
            hostChromeInset && "pt-[4.25rem] sm:pt-[4.25rem] lg:pt-[4.75rem]",
          )}
        >
          {!showSidebar ? (
            <div className="mb-7">
              <button
                type="button"
                onClick={backToChat}
                className="touch-target mb-4 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors settings-hover hover:text-foreground lg:hidden"
              >
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
                {t("settings.backToChat")}
              </button>
              <h1 className="text-[24px] font-normal leading-tight tracking-normal text-foreground sm:text-[28px]">
                {t(`settings.nav.${activeSection}`, {
                  defaultValue: standaloneSectionTitle(activeSection),
                })}
              </h1>
            </div>
          ) : null}

          {loading ? (
            <div className="flex h-48 items-center justify-center rounded-panel bg-settings-surface text-sm text-muted-foreground">
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
            <div
              className={cn(
                "settings-stack",
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
