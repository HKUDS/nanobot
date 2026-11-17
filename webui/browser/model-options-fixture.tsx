import { useState } from "react";

import { ThreadShell } from "@/components/thread/ThreadShell";
import { settings as baseSettings } from "@/dev/gallery/settings";
import type { SessionModelOptions, SettingsPayload } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";
import { createStreamClient } from "@/tests/stream-client";

const settings: SettingsPayload = {
  ...baseSettings,
  agent: { ...baseSettings.agent, model: "gpt-5.5", provider: "custom-codex", resolved_provider: "custom-codex" },
  providers: [{ name: "custom-codex", label: "Custom Codex", configured: true, model_catalog: "unsupported" }],
  model_presets: ["default", "Review"].map((name) => ({
    name, label: name === "default" ? "Default" : name, active: name === "default", is_default: name === "default",
    model: "gpt-5.5", provider: "custom-codex", resolved_provider: "custom-codex", max_tokens: 8192,
    context_window_tokens: 200_000, temperature: 0.1, reasoning_effort: "medium",
    model_options: {
      reasoning_effort: { default: "medium", values: ["none", "low", "medium", "high", "xhigh"] },
      codex_fast_mode: { default: false },
    },
  })),
  model_call_order: ["Review"],
};

/** Fully task-local fixture: no real gateway, authentication, or network mutations. */
export function installModelOptionsPreviewApi() {
  window.fetch = async (input) => {
    const url = String(input);
    if (url.includes("/webui-thread")) return Response.json({ schemaVersion: 3, projection: "events", events: [] });
    if (url.includes("/commands")) return Response.json({ commands: [] });
    if (url.includes("/api/settings")) return Response.json(settings);
    return Response.json({}, { status: 404 });
  };
}

export function ModelOptionsFixture() {
  const [sent, setSent] = useState<SessionModelOptions | undefined>();
  const [{ client }] = useState(() => {
    const preview = createStreamClient((data) => {
      const frame = JSON.parse(data);
      if (frame.type !== "message") return;
      if (!frame.content.startsWith("/")) setSent(frame.model_options);
      queueMicrotask(() => {
        preview.receive({ event: "message", chat_id: frame.chat_id, turn_id: frame.turn_id, text: "Fixture message accepted." });
        preview.receive({ event: "turn_end", chat_id: frame.chat_id, turn_id: frame.turn_id });
      });
    });
    return preview;
  });
  const temporary = new URLSearchParams(location.search).has("temporary");
  document.documentElement.classList.toggle("dark", new URLSearchParams(location.search).has("dark"));
  return <ClientProvider client={client} token="fixture" webuiCapabilities={["webui.core.v1", "webui.model-options.v1"]}>
    <main className="thread-workspace flex min-w-0 flex-col overflow-hidden bg-background text-foreground" style={{ height: "100dvh" }}>
      <ThreadShell session={{ key: "websocket:model-options-preview", channel: "websocket", chatId: "model-options-preview",
        createdAt: null, updatedAt: null, preview: "" }} title="Model options preview" temporary={temporary}
        onToggleSidebar={() => {}} settingsSnapshot={settings} onOpenModelSettings={() => {}} />
      <output aria-label="Sent model options" className="shrink-0 px-4 py-2 text-xs text-muted-foreground">
        {sent ? `Reasoning: ${sent.reasoning_effort ?? "inherit"}; Codex Fast: ${sent.codex_fast_mode === null ? "inherit" : sent.codex_fast_mode ? "on" : "off"}` : "No model options sent"}
      </output>
    </main>
  </ClientProvider>;
}
