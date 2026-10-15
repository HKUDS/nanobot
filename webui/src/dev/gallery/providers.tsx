import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ProvidersSettings, type ProviderSettingsEntry } from "@/components/settings/models/ProviderSettings";
import { parseProviderObject, providerFormFromRow, type CustomProviderDraft, type ProviderForm } from "@/components/settings/models/providerForm";
import { Button } from "@/components/ui/button";
import type { SettingsPayload } from "@/lib/types";
import type { ComponentExample } from "./example";
import { settings } from "./settings";

type ProviderRow = SettingsPayload["providers"][number];

const previewProviders: ProviderRow[] = [
  { name: "custom", label: "Custom", configured: true, auth_type: "api_key", api_key_hint: "••••••••", api_base: "https://api.example.com/v1" },
  { name: "anthropic", label: "Anthropic", configured: true, auth_type: "api_key", api_key_hint: "••••••••", api_base: "https://api.anthropic.com", request_apis: ["anthropic_messages"] },
  { name: "openai_codex", label: "OpenAI Codex", configured: true, auth_type: "oauth", api_key_required: false, oauth_login_supported: true, advanced_fields: ["proxy", "extra_body"] },
  { name: "xai_grok", label: "xAI Grok", configured: true, auth_type: "oauth", api_key_required: false, oauth_login_supported: true, advanced_fields: ["proxy", "extra_body"] },
  { name: "deepseek", label: "DeepSeek", configured: true, auth_type: "api_key", api_key_hint: "••••••••", api_base: "https://api.deepseek.com" },
  { name: "zhipu", label: "Zhipu AI", configured: true, auth_type: "api_key", api_key_hint: "••••••••", api_base: "https://open.bigmodel.cn/api/paas/v4" },
  { name: "minimax", label: "MiniMax", configured: true, auth_type: "api_key", api_key_hint: "••••••••", api_base: "https://api.minimax.io/v1" },
  { name: "groq", label: "Groq", configured: true, auth_type: "api_key", api_key_hint: "••••••••", api_base: "https://api.groq.com/openai/v1" },
  { name: "openai", label: "OpenAI", configured: false, auth_type: "api_key", default_api_base: "https://api.openai.com/v1", request_apis: ["responses", "chat_completions"], provider_api_configurable: true, model_api_configurable: true },
  { name: "ollama", label: "Ollama", configured: false, auth_type: "api_key", api_key_required: false, default_api_base: "http://localhost:11434/v1", model_catalog: "local" },
];

function stringParameters(value: string): Record<string, string> | null {
  const parsed = parseProviderObject(value);
  if (!parsed) return null;
  const result: Record<string, string> = {};
  for (const [key, entry] of Object.entries(parsed)) {
    if (typeof entry !== "string") return null;
    result[key] = entry;
  }
  return result;
}

function providerValues(form: ProviderForm) {
  const extraHeaders = stringParameters(form.extraHeaders);
  const extraQuery = stringParameters(form.extraQuery);
  const extraBody = parseProviderObject(form.extraBody);
  if (!extraHeaders || !extraQuery || !extraBody) return null;
  return {
    api_base: form.apiBase.trim() || null,
    api: form.api,
    api_key_hint: form.apiKey.trim() ? "••••••••" : undefined,
    proxy: form.proxy.trim() || null,
    extra_headers: extraHeaders,
    extra_query: extraQuery,
    extra_body: extraBody,
    thinking_style: form.thinkingStyle.trim() || null,
    region: form.region.trim() || null,
    profile: form.profile.trim() || null,
  };
}

function ProvidersPreview() {
  const { t } = useTranslation();
  const [payload, setPayload] = useState<SettingsPayload>(() => ({
    ...settings, providers: previewProviders, provider_api_configuration_supported: true,
  }));
  const [drafts, setDrafts] = useState<Record<string, ProviderForm>>(() =>
    Object.fromEntries(previewProviders.map((provider) => [provider.name, providerFormFromRow(provider)])));
  const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});
  const [editingKeys, setEditingKeys] = useState<Record<string, boolean>>({});
  const [entry, setEntry] = useState<ProviderSettingsEntry | null>(null);
  const [showBrandLogos, setShowBrandLogos] = useState(true);
  const [notice, setNotice] = useState("");
  const trigger = useRef<HTMLButtonElement | null>(null);
  const nextCustomId = useRef(1);
  const providerRows: Record<string, ProviderRow> = Object.fromEntries(payload.providers.map((provider) => [provider.name, provider]));

  const resetDraft = (name: string) => {
    setDrafts((current) => ({ ...current, [name]: providerFormFromRow(providerRows[name]) }));
    setVisibleKeys((current) => ({ ...current, [name]: false }));
    setEditingKeys((current) => ({ ...current, [name]: false }));
  };
  const saveProvider = async (name: string) => {
    const form = drafts[name];
    const values = providerValues(form);
    if (!values) {
      setNotice("请输入有效的请求参数 JSON；请求头和查询参数的值须为字符串。");
      return false;
    }
    setPayload((current) => ({ ...current, providers: current.providers.map((provider) => provider.name === name
      ? { ...provider, ...values, api_key_hint: values.api_key_hint ?? provider.api_key_hint,
        label: provider.is_custom ? form.displayName.trim() : provider.label, configured: true }
      : provider) }));
    setDrafts((current) => ({ ...current, [name]: { ...form, apiKey: "" } }));
    setEditingKeys((current) => ({ ...current, [name]: false }));
    setNotice(`已保存 ${providerRows[name].label} 的预览配置`);
    return true;
  };
  const createCustomProvider = async (form: CustomProviderDraft) => {
    const values = providerValues(form);
    if (!values) {
      setNotice("请输入有效的请求参数 JSON；请求头和查询参数的值须为字符串。");
      return null;
    }
    const name = `custom_preview_${nextCustomId.current++}`;
    const row: ProviderRow = { ...values, name, label: form.name.trim(), is_custom: true,
      configured: true, auth_type: "api_key", api_key_required: false, provider_api_configurable: true,
      advanced_fields: ["extra_headers", "extra_body", "extra_query", "proxy", "thinking_style"] };
    const next: SettingsPayload = { ...payload, providers: [...payload.providers, row], created_provider: name };
    setPayload(next);
    setDrafts((current) => ({ ...current, [name]: providerFormFromRow(row) }));
    setNotice(`已添加 ${row.label}`);
    return next;
  };
  const changeOAuth = (name: string, configured: boolean) => {
    setPayload((current) => ({ ...current, providers: current.providers.map((provider) => provider.name === name
      ? { ...provider, configured } : provider) }));
    setNotice(configured ? "预览授权状态已设为已登录" : "预览授权状态已设为未登录");
  };

  return <div className="space-y-4">
    <div className="flex flex-wrap gap-3">
      <Button variant="outline" onClick={(event) => {
        trigger.current = event.currentTarget;
        setEntry({ kind: "manage" });
      }}>{t("settings.providers.manageProviders")}</Button>
      <Button variant="outline" onClick={(event) => {
        trigger.current = event.currentTarget;
        setEntry({ kind: "add" });
      }}>{t("settings.providers.addProvider")}</Button>
      <Button variant="ghost" aria-pressed={showBrandLogos} onClick={() => setShowBrandLogos((current) => !current)}>
        {showBrandLogos ? "使用内置图标" : "使用品牌图标"}
      </Button>
    </div>
    <p role="status" className="text-xs text-muted-foreground">
      {notice || `${payload.providers.filter((provider) => provider.configured).length} 个已配置提供商`}
    </p>
    {entry ? <ProvidersSettings entry={entry} settings={payload} showBrandLogos={showBrandLogos}
      onClose={() => setEntry(null)} onCloseAutoFocus={(event) => { event.preventDefault(); trigger.current?.focus(); }}
      onProviderAdded={() => setNotice("已添加提供商")}
      nanobotFeatures={null} featureAction={null} capabilityError={null} providerForms={drafts}
      visibleProviderKeys={visibleKeys} editingProviderKeys={editingKeys} providerSaving={null} remoteBrowserAccess={false}
      onResetProviderDraft={resetDraft}
      onToggleProviderKey={(name) => setVisibleKeys((current) => ({ ...current, [name]: !current[name] }))}
      onToggleProviderKeyEditing={(name) => setEditingKeys((current) => ({ ...current, [name]: !current[name] }))}
      onChangeProviderForm={(name, values) => setDrafts((current) => ({ ...current, [name]: { ...current[name], ...values } }))}
      onSaveProvider={saveProvider} onCreateCustomProvider={createCustomProvider}
      onProviderOAuthLogin={(name) => changeOAuth(name, true)} onProviderOAuthLogout={(name) => changeOAuth(name, false)} /> : null}
  </div>;
}

export const providerExamples: ComponentExample[] = [
  { title: "ProvidersSettings · 管理提供商", files: ["webui/src/components/settings/models/ProviderSettings.tsx"], Preview: ProvidersPreview,
    description: "查看真实提供商管理弹窗与添加流程。",
    options: "复用设置中的 ProvidersSettings。目录、表单与保存回调由调用方控制；此处修改本地示例数据，支持配置、搜索、创建与取消。",
    code: '<ProvidersSettings entry={{ kind: "manage" }} settings={settings} providerForms={drafts} showBrandLogos={true} onSaveProvider={save} onCreateCustomProvider={create} {...callbacks} />' },
];
