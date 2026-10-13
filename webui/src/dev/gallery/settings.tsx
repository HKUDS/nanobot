import { useMemo, useState } from "react";

import { AdvancedSettings, networkSafetyFormFromPayload } from "@/components/settings/capabilities/SecuritySettings";
import { ImageGenerationSettings, imageGenerationFormFromPayload } from "@/components/settings/capabilities/ImageGenerationSettings";
import { TranscriptionSettings, transcriptionFormFromPayload } from "@/components/settings/capabilities/TranscriptionSettings";
import { WebSettings, webSearchDraftState, webSearchFormFromPayload } from "@/components/settings/capabilities/WebSettings";
import { ChannelCatalogRow } from "@/components/settings/channels/ChannelCatalogRow";
import { ChannelFieldGroups, channelRequirementErrors } from "@/components/settings/channels/ChannelCredentialFields";
import { ChannelHelpMenu } from "@/components/settings/channels/ChannelHelpMenu";
import { ChannelLogo, ChannelRuntimeError, ChannelStatusBadge } from "@/components/settings/channels/ChannelIdentity";
import { ChannelProviderPresets, ChannelSetupActions } from "@/components/settings/channels/ChannelSetupParts";
import { ChannelValidationProgress } from "@/components/settings/channels/ChannelValidationProgress";
import type { ChannelConfigField, ChannelProviderPreset } from "@/channel-plugins/catalog";
import type { SettingsSectionKey } from "@/components/settings/contracts";
import { ModelAPIControl } from "@/components/settings/models/ModelAPIControl";
import { ProviderAPIControl } from "@/components/settings/models/ProviderAPIControl";
import { ProviderParameterFields, type RequestParameterDraft } from "@/components/settings/models/ProviderParameterFields";
import { ProviderSearchList } from "@/components/settings/models/ProviderSearchList";
import { ReasoningEffortPicker } from "@/components/settings/models/ReasoningEffortPicker";
import { OverviewSettings } from "@/components/settings/overview/OverviewSettings";
import { SettingsSidebar } from "@/components/settings/SettingsSidebar";
import { CatalogSkeleton } from "@/components/settings/shared/CatalogSkeleton";
import { ModelIdPicker, ProviderPicker, ProviderPickerIcon } from "@/components/settings/shared/ModelControls";
import { ProviderIcon } from "@/components/settings/shared/ProviderIcon";
import { RemoveActionButton } from "@/components/settings/shared/RemoveActionButton";
import { SettingsGroup, SettingsRow } from "@/components/settings/shared/SettingsControls";
import { SettingsHint } from "@/components/settings/shared/SettingsHint";
import { SettingsTextEditor } from "@/components/settings/shared/SettingsTextEditor";
import { SkeletonStatus } from "@/components/settings/shared/SkeletonStatus";
import { TimezonePicker } from "@/components/settings/shared/TimezonePicker";
import { AutomationCalendar } from "@/components/settings/system/AutomationCalendar";
import { AutomationRunDialogView } from "@/components/settings/system/AutomationRunDialogView";
import { AutomationRunAtPicker } from "@/components/settings/system/AutomationRunAtPicker";
import { TokenUsageCard } from "@/components/settings/TokenUsageCard";
import { Button } from "@/components/ui/button";
import type { ChannelValidationPayload, ModelAPIConfig, NanobotFeatureInfo, SessionAutomationJob, SettingsPayload } from "@/lib/types";
import { Sample, StatePicker, type ComponentExample } from "./example";

const providers: SettingsPayload["providers"] = [
  { name: "openai", label: "OpenAI", configured: true, auth_type: "api_key", model_catalog: "builtin", model_api_configurable: true,
    request_apis: ["responses", "chat_completions"], provider_api_configurable: true },
  { name: "anthropic", label: "Anthropic", configured: true, auth_type: "api_key", model_catalog: "builtin", request_apis: ["anthropic_messages"] },
  { name: "openai_codex", label: "OpenAI Codex", configured: true, auth_type: "oauth", model_catalog: "builtin" },
  { name: "ollama", label: "Ollama", configured: true, auth_type: "api_key", model_catalog: "local" },
];

export const settings: SettingsPayload = {
  agent: { model: "gpt-5.4", provider: "openai", resolved_provider: "openai", has_api_key: true, model_preset: null,
    max_tokens: 8192, context_window_tokens: 200_000, temperature: 0.1, reasoning_effort: null, timezone: "UTC", tool_hint_max_length: 40 },
  model_presets: [], model_call_order: [], model_call_order_editable: true,
  providers,
  web_search: { provider: "duckduckgo", max_results: 5, timeout: 30, providers: [
    { name: "duckduckgo", label: "DuckDuckGo", credential: "none" },
    { name: "brave", label: "Brave Search", credential: "api_key" },
    { name: "searxng", label: "SearXNG", credential: "base_url" },
  ] },
  web: { enable: true, search: { max_results: 5, timeout: 30 }, fetch: { use_jina_reader: true } },
  image_generation: { enabled: true, provider: "openai", provider_configured: true, model: "gpt-image-1",
    default_aspect_ratio: "1:1", default_image_size: "1024x1024", max_images_per_turn: 4, save_dir: "workspace/images",
    providers: [{ name: "openai", label: "OpenAI", configured: true, uses_images_api: true,
      default_api_base: "https://api.openai.com/v1", models: ["gpt-image-1", "gpt-image-1-mini"] }] },
  transcription: { enabled: true, provider: "groq", provider_configured: true, model: "whisper-large-v3", language: null,
    max_duration_sec: 120, max_upload_mb: 25, providers: [{ name: "groq", label: "Groq", configured: true }] },
  runtime: { config_path: "config.json", workspace_path: "workspace", gateway_host: "127.0.0.1", gateway_port: 8765,
    heartbeat: { enabled: true, interval_s: 1800 }, dream: { schedule: "0 3 * * *" }, unified_session: false },
  advanced: { restrict_to_workspace: true, ssrf_whitelist_count: 0, webui_allow_local_service_access: true,
    webui_default_access_mode: "default", private_service_protection_enabled: true, mcp_server_count: 0,
    exec_enabled: true, exec_path_prepend_set: false, exec_path_append_set: false },
  requires_restart: false,
};

function usePreviewForm<T>(initial: T) {
  const [form, setForm] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  return { form, setForm, dirty, save: () => setSaved(form) };
}

function FormStatus({ dirty }: { dirty: boolean }) {
  return <p role="status" className="mt-4 text-xs text-muted-foreground">{dirty ? "正在保存预览值…" : "预览值已保存"}</p>;
}

function ModelPickerPreview() {
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-5.4");
  const [effort, setEffort] = useState("medium");
  const [action, setAction] = useState("");
  const models = provider === "anthropic" ? ["claude-sonnet-4", "claude-opus-4"] : ["gpt-5.4", "gpt-5-mini", "gpt-4.1"];
  return <div className="settings-grid space-y-4">
    <SettingsGroup>
      <SettingsRow title="服务商"><ProviderPicker providers={providers.slice(0, 2)} value={provider} emptyLabel="选择服务商"
        onChange={(next) => { setProvider(next); setModel(next === "anthropic" ? "claude-sonnet-4" : "gpt-5.4"); }}
        onAddProvider={() => setAction("添加服务商")}
        onConfigureProvider={(next) => setAction(`配置 ${next}`)} /></SettingsRow>
      <SettingsRow title="模型"><ModelIdPicker token="" settings={settings} provider={provider} models={models}
        value={model} showProviderLogos={false} onChange={setModel} /></SettingsRow>
      <SettingsRow title="推理强度"><ReasoningEffortPicker token="" provider={undefined} model={model}
        savedValues={["low", "medium", "high"]} value={effort} onChange={setEffort} /></SettingsRow>
    </SettingsGroup>
    <p role="status" className="text-xs text-muted-foreground">{provider} / {model} / {effort || "default"}{action ? ` · ${action}` : ""}</p>
  </div>;
}

function ProviderIconsPreview() {
  const [size, setSize] = useState<"regular" | "compact" | "fill">("regular");
  return <><StatePicker label="图标尺寸" value={size} options={["regular", "compact", "fill"]} onChange={setSize} />
    <div className="flex flex-wrap gap-8">{providers.map((provider) => <Sample key={provider.name} label={provider.label}>
      <div className="flex items-center gap-3"><span className={size === "fill" ? "block h-12 w-12" : ""}>
        <ProviderIcon provider={provider.name} compact={size === "compact"} fill={size === "fill"} showBrandLogos={false} />
      </span><ProviderPickerIcon provider={provider.name} showBrandLogos={false} />
        <ProviderPickerIcon provider={provider.name} showBrandLogos={false} unconfigured /></div>
    </Sample>)}</div></>;
}

function TimezonePreview() {
  const [value, setValue] = useState("Asia/Shanghai");
  return <div className="max-w-sm space-y-4"><TimezonePicker value={value} onChange={setValue} aria-label="选择时区" />
    <p role="status" className="text-sm text-muted-foreground">{new Intl.DateTimeFormat("zh-CN", {
      timeZone: value, dateStyle: "medium", timeStyle: "short",
    }).format(Date.UTC(2026, 0, 1, 12))} · {value}</p></div>;
}

function TextEditorPreview() {
  const [value, setValue] = useState("Keep replies concise. Explain the reason for a change.");
  const [mode, setMode] = useState<"editable" | "disabled">("editable");
  return <><StatePicker label="编辑状态" value={mode} options={["editable", "disabled"]} onChange={setMode} />
    <SettingsGroup><SettingsRow title={<SettingsHint description="打开编辑器后可以修改、保存或取消。清空内容可查看错误状态。">示例说明</SettingsHint>}>
      <SettingsTextEditor title="编辑示例说明" description="保存后，下方显示修改的内容。" value={value} disabled={mode === "disabled"}
        onSave={(next) => { if (!next.trim()) throw new Error("请输入内容。"); setValue(next); }} />
    </SettingsRow></SettingsGroup>
    <pre role="status" className="mt-4 whitespace-pre-wrap rounded-control bg-muted p-4 text-sm">{value}</pre></>;
}

function RemovePresetPreview() {
  const initial = [{ id: 1, name: "默认模型", primary: true }, { id: 2, name: "代码助手", primary: false }];
  const [items, setItems] = useState(initial);
  return <div className="settings-grid"><SettingsGroup>
    {items.map((item) => <SettingsRow key={item.id} title={item.name}>
      <RemoveActionButton disabled={item.primary} aria-label={`删除 ${item.name}`}
        aria-describedby={item.primary ? "gallery-primary-model-hint" : undefined}
        onClick={() => setItems((current) => current.filter((entry) => entry.id !== item.id))}>删除</RemoveActionButton>
    </SettingsRow>)}
  </SettingsGroup><p id="gallery-primary-model-hint" className="mt-4 text-xs text-muted-foreground">默认模型使用中的预设不能删除。</p>
    <p role="status" className="mt-2 text-xs text-muted-foreground">{items.length} 个预览预设</p>
    <Button className="mt-3" variant="outline" size="sm" onClick={() => setItems(initial)}>重置预览</Button></div>;
}

function LoadingPreview() {
  const [layout, setLayout] = useState<"apps" | "channels" | "skills">("apps");
  return <><StatePicker label="目录布局" value={layout} options={["apps", "channels", "skills"]} onChange={setLayout} />
    <Sample label="CatalogSkeleton"><CatalogSkeleton label="正在加载预览目录" layout={layout} /></Sample>
    <div className="mt-6"><Sample label="SkeletonStatus"><SkeletonStatus label="正在加载设置" className="space-y-3">
      <div className="h-4 w-1/3 rounded bg-muted" /><div className="h-9 rounded-control bg-muted" />
    </SkeletonStatus></Sample></div></>;
}

function SidebarPreview() {
  const [section, setSection] = useState<SettingsSectionKey>("models");
  const [pending, setPending] = useState(true);
  const [action, setAction] = useState("");
  return <div className="flex min-h-96 flex-col gap-6 lg:flex-row">
    <SettingsSidebar activeSection={section} onSelectSection={setSection} restartPending={pending}
      onBackToChat={() => setAction("返回聊天")}
      onLogout={() => setAction("退出登录")}
      onRestart={() => { setPending(false); setAction("已处理预览重启操作"); }} />
    <div className="space-y-3 p-4"><p role="status" className="text-sm">选中：{section}</p>
      <p className="text-xs text-muted-foreground">{action || "选择设置分类，或缩小浏览器查看移动端导航。"}</p>
      <Button variant="outline" size="sm" onClick={() => setPending((value) => !value)}>切换待重启状态</Button></div>
  </div>;
}

function ProviderSearchPreview() {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  return <><div className="flex h-[400px] flex-col overflow-hidden rounded-panel border pt-4">
    <ProviderSearchList providers={providers} showBrandLogos={false} query={query} onQueryChange={setQuery}
      onSelect={setSelected} onCustom={() => setSelected("custom")} onClose={() => { setQuery(""); setSelected("已关闭搜索"); }} />
  </div><p role="status" className="mt-4 text-sm text-muted-foreground">{selected ? `选择：${selected}` : "搜索服务商，或用方向键选择。"}</p></>;
}

function RequestParametersPreview() {
  const [form, setForm] = useState<RequestParameterDraft>({ extraHeaders: '{"X-Project":"gallery"}', extraQuery: "{}", extraBody: '{"service_tier":"auto"}' });
  return <div className="space-y-4"><ProviderParameterFields fields={["extra_headers", "extra_query", "extra_body"]} form={form}
    onChange={(next) => setForm((current) => ({ ...current, ...next }))} />
    <pre role="status" className="overflow-auto rounded-control bg-muted p-4 text-xs">{JSON.stringify(form, null, 2)}</pre></div>;
}

function RequestAPIPreview() {
  const [providerAPI, setProviderAPI] = useState<ModelAPIConfig>({ supported_apis: ["responses", "chat_completions"], preferred_api: "responses" });
  const [modelAPI, setModelAPI] = useState<ModelAPIConfig | null>(null);
  return <div className="grid gap-8 md:grid-cols-2">
    <Sample label="服务商协议"><ProviderAPIControl value={providerAPI} onChange={setProviderAPI} /></Sample>
    <Sample label="模型覆盖"><SettingsGroup><ModelAPIControl provider={providers[0]} automaticAPI="responses" value={modelAPI} onChange={setModelAPI} /></SettingsGroup></Sample>
    <pre role="status" className="overflow-auto rounded-control bg-muted p-4 text-xs md:col-span-2">{JSON.stringify({ providerAPI, modelAPI }, null, 2)}</pre>
  </div>;
}

type Usage = NonNullable<SettingsPayload["usage"]>;
const usage: Usage = (() => {
  const now = new Date();
  const days: Usage["days"] = Array.from({ length: 30 }, (_, index) => {
    const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - 29 + index));
    const scale = index % 7 === 0 ? 0 : index % 5 + 1;
    return { date: date.toISOString().slice(0, 10), input_tokens: scale * 4000, output_tokens: scale * 1000,
      cache_read_tokens: scale * 2000, cache_write_tokens: 0, cache_read_observed_input_tokens: scale * 3000,
      cache_write_observed_input_tokens: 0, total_tokens: scale * 5000, requests: scale * 2 };
  });
  const total = days.reduce((sum, day) => sum + day.total_tokens, 0);
  return { days, total_tokens: total, total_tokens_30d: total, total_tokens_365d: total,
    peak_day_tokens: Math.max(...days.map((day) => day.total_tokens)), current_streak_days: 3, longest_streak_days: 6,
    active_days_30d: days.filter((day) => day.total_tokens > 0).length, requests_30d: days.reduce((sum, day) => sum + day.requests, 0),
    model_days_30d: days.flatMap((day) => [
      { date: day.date, provider: "openai", model: "gpt-5.4", total_tokens: day.total_tokens * 0.6 },
      { date: day.date, provider: "anthropic", model: "claude-sonnet-4", total_tokens: day.total_tokens * 0.4 },
    ]) };
})();

function UsagePreview() {
  const [mode, setMode] = useState<"active" | "empty" | "unavailable">("active");
  return <><StatePicker label="用量状态" value={mode} options={["active", "empty", "unavailable"]} onChange={setMode} />
    <TokenUsageCard usage={mode === "unavailable" ? undefined : mode === "empty" ? { ...usage, days: [], model_days_30d: [] } : usage} timeZone="UTC" /></>;
}

function OverviewPreview() {
  const [section, setSection] = useState<SettingsSectionKey>("overview");
  return <><OverviewSettings settings={{ ...settings, usage }} showBrandLogos={false} onSelectSection={setSection} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">选择的分类：{section}</p></>;
}

function WebPreview() {
  const [savedSettings, setSavedSettings] = useState(settings);
  const [form, setForm] = useState(webSearchFormFromPayload(settings));
  const [keyVisible, setKeyVisible] = useState(false);
  const [keyEditing, setKeyEditing] = useState(false);
  const { dirty } = webSearchDraftState(savedSettings, form);
  return <><WebSettings settings={savedSettings} form={form} saving={false} keyVisible={keyVisible} keyEditing={keyEditing}
    onChangeForm={setForm} onChangeProvider={(provider) => setForm((current) => ({ ...current, provider, apiKey: "", baseUrl: "" }))}
    onToggleKey={() => setKeyVisible((value) => !value)} onToggleKeyEditing={() => setKeyEditing((value) => !value)}
    onReset={() => setForm(webSearchFormFromPayload(savedSettings))}
    onSave={() => {
      setSavedSettings((current) => ({ ...current,
        web_search: { ...current.web_search, provider: form.provider,
          api_key_hint: form.apiKey ? "••••••••" : form.provider === current.web_search.provider ? current.web_search.api_key_hint : undefined,
          base_url: form.baseUrl, max_results: form.maxResults ?? current.web_search.max_results, timeout: form.timeout ?? current.web_search.timeout },
        web: { ...current.web, fetch: { use_jina_reader: form.useJinaReader ?? current.web.fetch.use_jina_reader } },
      })); setForm((current) => ({ ...current, apiKey: "" })); setKeyEditing(false);
    }} showBrandLogos={false} requiresRestartPending={false} olostepInstalling={false} capabilityError={null} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">{dirty ? "预览草稿尚未保存" : "预览值已保存"}</p></>;
}

function ImagePreview() {
  const { form, setForm, dirty, save } = usePreviewForm(imageGenerationFormFromPayload(settings));
  const [notice, setNotice] = useState("");
  return <><ImageGenerationSettings token="" settings={settings} form={form} dirty={dirty} saving={false}
    onChangeForm={setForm} onSave={save} showBrandLogos={false} requiresRestartPending={false}
    onSaveRequestSettings={async (next) => setForm((current) => ({ ...current, ...next }))}
    onOpenProviders={() => setNotice("选择了服务商配置操作")} />
    <FormStatus dirty={dirty} />{notice ? <p className="mt-2 text-xs text-muted-foreground">{notice}</p> : null}</>;
}

function VoicePreview() {
  const { form, setForm, dirty, save } = usePreviewForm(transcriptionFormFromPayload(settings));
  const [notice, setNotice] = useState("");
  return <><TranscriptionSettings settings={settings} form={form} dirty={dirty} saving={false} onChangeForm={setForm}
    onSave={save} showBrandLogos={false} requiresRestartPending={false} onOpenProviders={() => setNotice("选择了服务商配置操作")} />
    <FormStatus dirty={dirty} />{notice ? <p className="mt-2 text-xs text-muted-foreground">{notice}</p> : null}</>;
}

function SafetyPreview() {
  const { form, setForm, dirty, save } = usePreviewForm(networkSafetyFormFromPayload(settings));
  return <><AdvancedSettings form={form} dirty={dirty} saving={false} requiresRestartPending={false}
    isNativeHostSurface={false} onChangeForm={setForm} onSave={save} /><FormStatus dirty={dirty} /></>;
}

const channel: NanobotFeatureInfo = {
  name: "gallery_channel", display_name: "Example channel", type: "channel", enabled: false, installed: true,
  configured: true, ready: true, status: "not_enabled", install_supported: true, requires_restart: false, runtime_status: "stopped",
  setup: { fields: [], official_url: "https://nanobot.wiki/docs/latest/getting-started/chat-apps" },
};

function ChannelCatalogPreview() {
  const [mode, setMode] = useState<"stopped" | "running" | "starting" | "failed" | "uninstalled">("stopped");
  const [selected, setSelected] = useState(false);
  const feature = { ...channel, enabled: mode === "running" || mode === "starting", installed: mode !== "uninstalled",
    runtime_status: mode === "uninstalled" ? "stopped" : mode, runtime_error: mode === "failed" ? "Example connection failed." : undefined };
  return <><StatePicker label="频道状态" value={mode} options={["stopped", "running", "starting", "failed", "uninstalled"]} onChange={setMode} />
    <div className="settings-grid"><SettingsGroup><ChannelCatalogRow feature={feature} showBrandLogos={false} actionKey={null}
      onSelect={() => setSelected(true)} onAction={(action, _name, options) => setMode(options?.installOnly ? "stopped" : action === "enable" ? "running" : "stopped")} /></SettingsGroup></div>
    <div className="mt-4 flex items-center gap-3"><ChannelLogo feature={feature} showBrandLogos={false} />
      <ChannelStatusBadge status={feature.runtime_status}>{feature.runtime_status}</ChannelStatusBadge>
      <ChannelHelpMenu feature={feature} /></div>
    <ChannelRuntimeError message={feature.runtime_error} />
    <p role="status" className="mt-4 text-xs text-muted-foreground">{selected ? "选择了频道设置" : "点击开关或安装按钮，查看状态变化。"}</p></>;
}

const channelFields: ChannelConfigField[] = [
  { key: "bot_token", label: "Bot token", secret: true, section: "credentials", placeholder: "Example token" },
  { key: "server_url", label: "Server URL", inputType: "url", section: "connection", optional: true },
  { key: "mode", label: "Reply mode", section: "behavior", options: [{ value: "mention", label: "Mentions" }, { value: "all", label: "All messages" }] },
  { key: "allow_from", label: "Allow from", section: "access", kind: "json", optional: true, placeholder: '["user-id"]' },
];
const channelPresets: ChannelProviderPreset[] = [
  { id: "local", label: "Local server", values: { server_url: "http://127.0.0.1:8080", mode: "mention" } },
  { id: "hosted", label: "Hosted server", values: { server_url: "https://example.com", mode: "all" } },
];

function CredentialsPreview() {
  const [values, setValues] = useState<Record<string, string>>({ bot_token: "", server_url: "", mode: "mention", allow_from: "[]" });
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  return <div className="space-y-5">
    <ChannelProviderPresets presets={channelPresets} onApply={(preset) => { setValues((current) => ({ ...current, ...preset.values })); setNotice(`已应用 ${preset.label}`); }} />
    <ChannelFieldGroups fields={channelFields} requirements={[{ alternatives: [["bot_token"]] }]} values={values} visibleSecrets={visibleSecrets}
      errors={errors} onChange={(key, value) => { setValues((current) => ({ ...current, [key]: value })); setErrors({}); }}
      onToggleSecret={(key) => setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }))} />
    <div className="flex flex-wrap items-center gap-3"><Button variant="outline" onClick={() => {
      const next = channelRequirementErrors(channelFields, [{ alternatives: [["bot_token"]] }], values, new Set(), new Set(), "请输入 Bot token。");
      setErrors(next); setNotice(Object.keys(next).length ? "请补全凭据。" : "预览凭据已保存。");
    }}>检查并保存</Button><ChannelSetupActions feature={channel} setup={{ actions: [{ id: "copy", label: "Example command", copyText: "nanobot gateway" }] }} onNotice={setNotice} /></div>
    <p role="status" className="text-xs text-muted-foreground">{notice || "填写凭据、切换密文显示，或应用连接预设。"}</p>
  </div>;
}

function ChannelValidationPreview() {
  const [mode, setMode] = useState<"checking" | "connected" | "invalid">("connected");
  const validation = useMemo<ChannelValidationPayload | null>(() => mode === "checking" ? null : {
    name: channel.name, status: mode, identity: { name: "Example bot", workspace: "Gallery workspace" },
    checks: [{ id: "credentials", label: "Credentials", status: "pass" },
      { id: "connection", label: "Connection", status: mode === "invalid" ? "fail" : "pass", message: mode === "invalid" ? "The example token has expired." : undefined }],
    missing_fields: [], can_enable: mode === "connected", requires_restart: false,
  }, [mode]);
  return <><StatePicker label="检查结果" value={mode} options={["checking", "connected", "invalid"]} onChange={setMode} />
    <ChannelValidationProgress validation={validation} validating={mode === "checking"} feature={channel} /></>;
}

function RunAtPreview() {
  const [value, setValue] = useState("2026-10-15T09:30");
  return <div className="max-w-md space-y-4"><AutomationRunAtPicker value={value} onChange={setValue} />
    <p role="status" className="text-sm text-muted-foreground">{value}</p></div>;
}

function AutomationCalendarPreview() {
  const [month, setMonth] = useState(() => { const now = new Date(); return new Date(now.getFullYear(), now.getMonth(), 1); });
  const [mode, setMode] = useState<"scheduled" | "history" | "empty">("scheduled");
  const [selected, setSelected] = useState("");
  const jobs: SessionAutomationJob[] = mode === "empty" ? [] : [{ id: "gallery-reminder", name: "Weekly report", enabled: mode === "scheduled",
    schedule: { kind: "cron", expr: "30 9 * * 1", tz: "UTC" }, payload: { message: "Summarize this week's changes." },
    state: { next_run_at_ms: mode === "scheduled" ? new Date(month.getFullYear(), month.getMonth(), 15, 9, 30).getTime() : null,
      run_history: [{ run_at_ms: new Date(month.getFullYear(), month.getMonth(), 8, 9, 30).getTime(), status: "ok", duration_ms: 3200, webui_session_key: null },
        { run_at_ms: new Date(month.getFullYear(), month.getMonth(), 1, 9, 30).getTime(), status: "error", duration_ms: 1200, error: "Example provider was unavailable.", webui_session_key: null }] } }];
  return <><StatePicker label="日程状态" value={mode} options={["scheduled", "history", "empty"]} onChange={setMode} />
    <div className="mb-4 flex flex-wrap items-center gap-3"><Button size="sm" variant="outline" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>上个月</Button>
      <span className="text-sm">{new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long" }).format(month)}</span>
      <Button size="sm" variant="outline" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>下个月</Button></div>
    <AutomationCalendar jobs={jobs} month={month} locale="zh-CN" onInspect={(job) => setSelected(job.name)}
      renderRunDialog={(props) => <AutomationRunDialogView {...props} result={{ status: "loaded", response: "**运行结果**\n\n示例任务已处理当前项目更新。" }} onRetry={() => {}} />}
      copy={{
      planned: "已计划", recorded: "运行记录", running: "正在运行", failed: "失败", completed: "完成", skipped: "已跳过", system: "系统任务",
      close: "关闭", noEntries: "本月没有日程", more: (count) => `另外 ${count} 条`,
    }} /><p role="status" className="mt-4 text-xs text-muted-foreground">{selected ? `选择了任务：${selected}` : "点击运行记录查看结果，或选择计划中的任务。"}</p></>;
}

const components = "webui/src/components/settings/";
export const settingsExamples: ComponentExample[] = [
  { title: "Model pickers · 模型选择", files: ["shared/ModelControls", "models/ReasoningEffortPicker"], Preview: ModelPickerPreview,
    description: "选择服务商、搜索或输入模型 ID，并调整推理强度。",
    options: "ProviderPicker 的值与操作由调用方提供。ModelIdPicker 的 models 参数可提供固定目录；ReasoningEffortPicker 的 savedValues 提供已有选项。",
    code: '<ProviderPicker providers={providers} value={provider} onChange={setProvider} emptyLabel="选择服务商" />\n<ModelIdPicker token="" settings={settings} provider={provider} models={modelIds} value={model} showProviderLogos={false} onChange={setModel} />' },
  { title: "Provider icons · 服务商图标", files: ["shared/ProviderIcon"], Preview: ProviderIconsPreview,
    description: "比较普通、紧凑与填充尺寸，以及选择器的未配置状态。", options: "provider 选择已有图标；compact 与 fill 控制尺寸。showBrandLogos=false 使用内置图标。",
    code: '<ProviderIcon provider="openai" showBrandLogos={false} compact />\n<ProviderPickerIcon provider="openai" showBrandLogos={false} unconfigured />' },
  { title: "TimezonePicker · 时区选择", files: ["shared/TimezonePicker"], Preview: TimezonePreview,
    description: "按时区名、中文名称或 UTC 偏移搜索，选择后查看同一时刻的当地时间。", options: "value 是 IANA 时区；onChange 更新调用方的值。搜索与键盘导航由组件提供。",
    code: '<TimezonePicker value={timezone} onChange={setTimezone} aria-label="选择时区" />' },
  { title: "Text editor and hint · 文本编辑", files: ["shared/SettingsTextEditor", "shared/SettingsHint"], Preview: TextEditorPreview,
    description: "打开编辑弹窗，修改、保存或取消。清空内容后保存可查看错误反馈。", options: "SettingsTextEditor 在 onSave 成功后关闭，失败时显示错误；SettingsHint 可通过悬停、焦点或点击打开。",
    code: '<SettingsHint description="补充说明">标题</SettingsHint>\n<SettingsTextEditor title="编辑说明" value={value} onSave={setValue} />' },
  { title: "RemoveActionButton · 删除预设", files: ["shared/RemoveActionButton"], Preview: RemovePresetPreview,
    description: "删除未使用的模型预设，查看默认模型使用中预设的禁用状态。", options: "这是 ModelsSettings 使用的删除按钮；disabled 与删除动作由调用方提供。提供商管理使用 ProvidersSettings 弹窗。",
    code: '<RemoveActionButton disabled={referenced} onClick={deletePreset}>删除</RemoveActionButton>' },
  { title: "Loading layouts · 加载占位", files: ["shared/CatalogSkeleton", "shared/SkeletonStatus"], Preview: LoadingPreview,
    description: "切换应用、频道与技能目录的加载布局，并查看通用状态容器。", options: "CatalogSkeleton 的 layout 选择布局。SkeletonStatus 用 label 提供读屏状态，将装饰内容标为 aria-hidden。",
    code: '<CatalogSkeleton label="正在加载目录" layout="channels" />\n<SkeletonStatus label="正在加载设置" className="space-y-3">{skeletons}</SkeletonStatus>' },
  { title: "SettingsSidebar · 设置导航", files: ["SettingsSidebar"], Preview: SidebarPreview,
    description: "选择分类、处理待重启状态，并缩小浏览器查看移动端菜单。", options: "activeSection 与 onSelectSection 控制选择；返回、退出与重启动作为调用方回调。",
    code: '<SettingsSidebar activeSection={section} onSelectSection={setSection} onBackToChat={back} onRestart={restart} restartPending />' },
  { title: "ProviderSearchList · 服务商搜索", files: ["models/ProviderSearchList"], Preview: ProviderSearchPreview,
    description: "搜索按 OAuth、API Key 与本地分组的服务商，选择条目或自定义服务商。", options: "providers 是已有目录。query 为受控搜索值；onSelect 与 onCustom 将选择交给父组件。",
    code: '<ProviderSearchList providers={providers} query={query} onQueryChange={setQuery} showBrandLogos={false} onSelect={select} onCustom={custom} onClose={close} />' },
  { title: "ProviderParameterFields · 请求参数", files: ["models/ProviderParameterFields"], Preview: RequestParametersPreview,
    description: "编辑请求头、查询参数和请求体；输入无效 JSON 可查看真实校验反馈。", options: "fields 选择显示项，form 保存 JSON 文本。请求头与查询参数只接受字符串值；请求体接受任意 JSON 对象值。",
    code: '<ProviderParameterFields fields={["extra_headers", "extra_query", "extra_body"]} form={draft} onChange={updateDraft} />' },
  { title: "Request API controls · 请求协议", files: ["models/ProviderAPIControl", "models/ModelAPIControl"], Preview: RequestAPIPreview,
    description: "选择服务商支持的协议、默认协议，以及模型覆盖和回退选项。", options: "ProviderAPIControl 至少保留一个协议。ModelAPIControl 允许 null 表示自动选择，并按服务商能力显示可用协议。",
    code: '<ProviderAPIControl value={api} onChange={setAPI} />\n<ModelAPIControl provider={provider} automaticAPI="responses" value={modelAPI} onChange={setModelAPI} />' },
  { title: "Token usage · 用量统计", files: ["TokenUsageCard", "TokenUsageDetails", "TokenUsageModelTrend"], Preview: UsagePreview,
    description: "切换有数据、空记录和不可用状态。悬停柱图查看每日用量，打开详情查看模型趋势。", options: "usage 是调用方提供的统计记录；timeZone 定义日期范围。详情弹窗与图表只展示传入数据。",
    code: '<TokenUsageCard usage={usage} timeZone="UTC" />' },
  { title: "OverviewSettings · 设置概览", files: ["overview/OverviewSettings"], Preview: OverviewPreview,
    description: "查看当前模型、能力状态和用量统计，点击功能行体验分类选择。", options: "settings 提供概览数据；onSelectSection 接收选择的设置分类。",
    code: '<OverviewSettings settings={settings} showBrandLogos={false} onSelectSection={setSection} />' },
  { title: "WebSettings · 搜索设置", files: ["capabilities/WebSettings"], Preview: WebPreview,
    description: "切换免凭据、API Key 与服务器地址三种服务商，调整搜索选项并体验自动保存。", options: "settings 保存当前配置，form 保存编辑值。保存、凭据显示与服务商切换由父组件提供。",
    code: '<WebSettings settings={settings} form={form} onChangeForm={setForm} onSave={save} {...actions} />' },
  { title: "ImageGenerationSettings · 图像设置", files: ["capabilities/ImageGenerationSettings"], Preview: ImagePreview,
    description: "开关图像生成，选择固定模型目录、宽高比与图片尺寸，展开高级选项调整数量。", options: "form 为受控配置，dirty 标记修改。组件复用服务商凭据，保存动作由父组件实现。",
    code: '<ImageGenerationSettings token="" settings={settings} form={form} dirty={dirty} onChangeForm={setForm} onSave={save} {...actions} />' },
  { title: "TranscriptionSettings · 语音设置", files: ["capabilities/TranscriptionSettings"], Preview: VoicePreview,
    description: "切换转写开关，编辑模型、语言与时长和上传大小限制，体验自动保存。", options: "settings 提供服务商信息；form 与保存回调由父组件管理。",
    code: '<TranscriptionSettings settings={settings} form={form} dirty={dirty} onChangeForm={setForm} onSave={save} {...actions} />' },
  { title: "AdvancedSettings · 访问设置", files: ["capabilities/SecuritySettings"], Preview: SafetyPreview,
    description: "切换本地服务访问与默认权限，查看设置行、提示和自动保存反馈。", options: "form 是显示值；onSave 处理保存请求。运行时的权限执行仍由 gateway 负责。",
    code: '<AdvancedSettings form={form} dirty={dirty} saving={false} requiresRestartPending={false} isNativeHostSurface={false} onChangeForm={setForm} onSave={save} />' },
  { title: "Channel catalog and identity · 频道条目", files: ["channels/ChannelCatalogRow", "channels/ChannelIdentity", "channels/ChannelHelpMenu"], Preview: ChannelCatalogPreview,
    description: "切换运行、启动、失败和未安装状态；操作开关、安装入口与帮助菜单。", options: "feature 提供安装和运行状态。onAction 与 onSelect 交给父组件处理；标识、错误和帮助使用同一频道数据。",
    code: '<ChannelCatalogRow feature={feature} showBrandLogos={false} actionKey={null} onSelect={select} onAction={act} />' },
  { title: "Channel credentials · 频道表单", files: ["channels/CredentialForm", "channels/ChannelCredentialFields", "channels/ChannelSetupParts"], Preview: CredentialsPreview,
    description: "输入凭据，显示或隐藏密文，应用连接预设，检查必填字段并复制辅助命令。", options: "fields 定义分组与控件，values 和 visibleSecrets 为受控值。requirements 定义凭据组合；预设与保存回调只更新此示例。",
    code: '<ChannelFieldGroups fields={fields} requirements={requirements} values={values} visibleSecrets={visible} onChange={change} onToggleSecret={toggle} />' },
  { title: "ChannelValidationProgress · 连接检查", files: ["channels/ChannelValidationProgress"], Preview: ChannelValidationPreview,
    description: "切换检查中、成功和失败，观察逐项揭示的检查结果与身份摘要。", options: "validation 提供检查记录，validating 控制加载状态；组件只负责展示。",
    code: '<ChannelValidationProgress feature={feature} validation={validation} validating={checking} />' },
  { title: "AutomationRunAtPicker · 定时选择", files: ["system/AutomationRunAtPicker"], Preview: RunAtPreview,
    description: "输入日期时间，或打开日历并用鼠标、方向键和翻页键选择日期。", options: "value 使用 YYYY-MM-DDTHH:mm 本地时间；onChange 返回编辑值。错误输入显示在现有表单控件上。",
    code: '<AutomationRunAtPicker value={runAt} onChange={setRunAt} />' },
  { title: "Automation calendar · 任务日历", files: ["system/AutomationCalendar"], Preview: AutomationCalendarPreview,
    description: "翻月、切换计划与历史记录，点击成功或失败记录打开结果弹窗。窄容器自动显示日程列表。", options: "jobs 与 month 决定日历内容。onInspect 处理计划中的任务；renderRunDialog 由调用方提供结果展示，日历不读取服务。",
    code: '<AutomationCalendar jobs={jobs} month={month} locale="zh-CN" copy={copy} onInspect={inspect} renderRunDialog={renderRunDialog} />' },
].map((example) => ({ ...example, files: example.files.map((file) => `${components}${file}.tsx`) }));
