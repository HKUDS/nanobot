import { useState } from "react";

import { SettingsPage } from "@/components/settings/SettingsPage";
import { useSettingsController } from "@/components/settings/useSettingsController";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { settings as baseSettings } from "@/dev/gallery/settings";
import type { ModelOptionsCapability, SessionModelOptions, SettingsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ClientProvider } from "@/providers/ClientProvider";
import { createStreamClient } from "@/tests/stream-client";

const params = new URLSearchParams(location.search);
const isChinese = params.get("lang")?.startsWith("zh");
const showSettings = params.has("settings");
const loadCodexCatalog = params.has("codex-catalog");
const providers = {
  openai_codex: { label: "OpenAI Codex", auth_type: "oauth", codex_fast_mode_supported: true, codex_ultrafast_models: ["gpt-6.2-sol"] },
  github_copilot: { label: "GitHub Copilot", auth_type: "oauth" },
  openai: { label: "OpenAI" },
  anthropic: { label: "Anthropic" },
  deepseek: { label: "DeepSeek" },
  mistral: { label: "Mistral" },
  openrouter: { label: "OpenRouter" },
  orcarouter: { label: "OrcaRouter" },
  azure_openai: { label: "Azure OpenAI" },
  bedrock: { label: "AWS Bedrock" },
  ollama: { label: "Ollama" },
  vllm: { label: "vLLM" },
  custom: { label: "Custom API" },
} satisfies Record<string, Partial<SettingsPayload["providers"][number]>>;

type Preset = SettingsPayload["model_presets"][number];
const codexEfforts = ["none", "low", "medium", "high", "xhigh"];
function preset(
  name: string, provider: keyof typeof providers, model: string, effort: string | null = "medium",
  values = ["low", "medium", "high"], speed?: ModelOptionsCapability["codex_fast_mode"],
): Preset {
  return {
    name, label: name, active: false, is_default: false, model, provider, resolved_provider: provider,
    max_tokens: 8192, context_window_tokens: 200_000, temperature: 0.1,
    reasoning_effort: effort, reasoning_effort_values: values,
    model_options: { reasoning_effort: { default: effort, values }, ...(speed && { codex_fast_mode: speed }) },
  };
}

const standardCodex = preset("Codex", "openai_codex", "gpt-5.5", "medium", codexEfforts, { default: false });
const ultrafastCodex = preset("Review", "openai_codex", "gpt-6.2-sol", "medium", codexEfforts, { default: false, ultrafast_supported: true });
const groups = [
  { id: "oauth", label: isChinese ? "登录授权" : "OAuth", presets: [
    ultrafastCodex, standardCodex, preset("GitHub Copilot", "github_copilot", "github-copilot/gpt-5.4-mini", "low"),
  ] },
  { id: "direct", label: isChinese ? "直连 API" : "Direct APIs", presets: [
    preset("DeepSeek", "deepseek", "deepseek-v4-pro", "high", ["none", "low", "high", "max"]),
    preset("OpenAI", "openai", "gpt-5.4"),
    preset("Anthropic", "anthropic", "claude-opus-4-7", "high"),
    preset("Mistral", "mistral", "magistral-medium-latest", null, []),
  ] },
  { id: "gateway", label: isChinese ? "聚合网关" : "Gateways", presets: [
    preset("OpenRouter", "openrouter", "openai/gpt-5.4", null),
    preset("OrcaRouter", "orcarouter", "deepseek/deepseek-v4-pro", "high"),
  ] },
  { id: "cloud", label: isChinese ? "云平台" : "Cloud platforms", presets: [
    preset("AWS Bedrock", "bedrock", "anthropic.claude-sonnet-4-6", "high"),
    preset("Azure OpenAI", "azure_openai", "azure/gpt-5.4"),
  ] },
  { id: "local", label: isChinese ? "本地与自建" : "Local & self-hosted", presets: [
    preset("Ollama", "ollama", "qwen3:8b", null),
    preset("vLLM", "vllm", "Qwen/Qwen3-32B", "high"),
    preset("Custom API", "custom", "team-assistant", "extended"),
  ] },
];
const group = groups.find(({ id }) => id === params.get("group")) ?? groups[0]!;
const base = loadCodexCatalog
  ? preset("Review", "openai_codex", "openai-codex/gpt-6.2-sol", "xhigh", ["low", "medium", "high"], { default: false, ultrafast_supported: true })
  : group.id === "oauth" ? (params.has("ultrafast") ? ultrafastCodex : standardCodex) : group.presets[0]!;
const extraPresets = params.has("many-presets")
  ? Array.from({ length: 12 }, (_, index) => preset(`Example ${index + 1}`, "openai_codex", "gpt-6.2-sol"))
  : [];
const settings: SettingsPayload = {
  ...baseSettings,
  agent: { ...baseSettings.agent, model: base.model, provider: base.provider, resolved_provider: base.provider,
    reasoning_effort: base.reasoning_effort },
  providers: Object.entries(providers).map(([name, provider]) => ({
    name, configured: true, model_catalog: loadCodexCatalog && name === "openai_codex" ? "hybrid" : "unsupported", ...provider,
  })),
  model_presets: [{ ...base, name: "default", label: "Default", active: true, is_default: true }, ...group.presets, ...extraPresets],
  model_call_order: [...group.presets, ...extraPresets].map(({ name }) => name),
};

function fixtureLink(groupId: string, settingsView: boolean) {
  const url = new URL(location.href);
  url.searchParams.set("group", groupId);
  if (settingsView) url.searchParams.set("settings", "");
  else url.searchParams.delete("settings");
  return url.href;
}

function FixtureNav() {
  return (
    <nav aria-label={isChinese ? "提供商示例" : "Provider examples"}
      className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-border bg-background px-3 py-2 text-xs text-foreground">
      {groups.map(({ id, label }) => (
        <a key={id} href={fixtureLink(id, showSettings)} aria-current={group.id === id ? "page" : undefined}
          className={cn("rounded-control px-2 py-1.5 hover:bg-muted", group.id === id && "bg-muted font-semibold")}>
          {label}
        </a>
      ))}
      <a className="ml-auto rounded-control px-2 py-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        href={fixtureLink(group.id, !showSettings)}>
        {showSettings ? (isChinese ? "会话菜单" : "Chat menu") : (isChinese ? "预设编辑" : "Preset settings")}
      </a>
    </nav>
  );
}

/** Fully task-local fixture: no real gateway, authentication, or network mutations. */
export function installModelOptionsPreviewApi() {
  const fetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input);
    if (loadCodexCatalog && url.includes("/api/settings/provider-models?")) return fetch(input, init);
    if (url.includes("/webui-thread")) return Response.json({ schemaVersion: 3, projection: "events", events: [] });
    if (url.includes("/commands")) return Response.json({ commands: [] });
    if (url.includes("/api/settings")) return Response.json(settings);
    return Response.json({}, { status: 404 });
  };
}

const noop = () => {};

function ModelSettingsFixture() {
  const controller = useSettingsController({ initialSection: "models", initialSettings: settings, onModelNameChange: noop });
  return <div className="flex min-h-0 flex-1 flex-col bg-settings-canvas">
    <SettingsPage controller={controller} themePreference={params.has("dark") ? "dark" : "light"}
      showSidebar mainNavigationExpanded={false} onChangeTheme={noop} onBackToChat={noop}
      skills={[]} skillsLoading={false} skillsError={false} isRestarting={false} hostChromeInset={false} />
  </div>;
}

export function ModelOptionsFixture() {
  const [sent, setSent] = useState<SessionModelOptions | undefined>();
  const [{ client }] = useState(() => {
    const preview = createStreamClient((data) => {
      const frame = JSON.parse(data);
      if (frame.type !== "message") return;
      if (!frame.content.startsWith("/")) setSent(frame.model_options);
      queueMicrotask(() => {
        const preset = frame.content.startsWith("/model ") ? frame.content.slice(7) : null;
        preview.receive({ event: "message", chat_id: frame.chat_id, turn_id: frame.turn_id, text: "Fixture message accepted.",
          ...(preset && { side_channel: true, command_result: { command: "/model", parts: [{ key: "model.switched", values: { preset } }] } }),
        });
        preview.receive({ event: "turn_end", chat_id: frame.chat_id, turn_id: frame.turn_id });
      });
    });
    return preview;
  });
  const temporary = params.has("temporary");
  document.documentElement.classList.toggle("dark", params.has("dark"));
  const chatId = `model-options-preview-${group.id}-${base.model}`;
  return <ClientProvider client={client} token="fixture" webuiCapabilities={["webui.core.v1", "webui.model-options.v1"]}>
    <div className="flex flex-col overflow-hidden" style={{ height: "100dvh" }}>
      <FixtureNav />
      {showSettings ? <ModelSettingsFixture /> : (
        <main className="thread-workspace flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background text-foreground">
          <ThreadShell session={{ key: `websocket:${chatId}`, channel: "websocket", chatId,
            createdAt: null, updatedAt: null, preview: "" }} title={`${group.label} · ${base.model}`} temporary={temporary}
            onToggleSidebar={noop} settingsSnapshot={settings}
            onOpenModelSettings={() => location.assign(fixtureLink(group.id, true))} />
          <output aria-label="Sent model options" className="shrink-0 px-4 py-2 text-xs text-muted-foreground">
            {sent ? `Reasoning: ${sent.reasoning_effort ?? "unchanged"}; Codex Fast: ${typeof sent.codex_fast_mode === "boolean" ? (sent.codex_fast_mode ? "on" : "off") : sent.codex_fast_mode ?? "unchanged"}` : "No model options sent"}
          </output>
        </main>)}
    </div>
  </ClientProvider>;
}
