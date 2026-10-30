import { useState } from "react";

import { SettingsView } from "@/components/settings/SettingsView";
import { RUNTIME_CONFIG_FIELDS } from "@/components/settings/system/runtime-config-fields";
import { settings } from "@/dev/gallery/settings";
import { NanobotClient } from "@/lib/nanobot-client";
import type { RuntimeConfigValue, SettingsPayload } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

const path = "agents.defaults.session_ttl_minutes";
const storageKey = "fixture.idle-compaction-minutes";
const client = new NanobotClient({ url: "ws://127.0.0.1:1", reconnect: false });
let failNext = false;
const initial: SettingsPayload = {
  ...settings,
  runtime_config: Object.fromEntries(RUNTIME_CONFIG_FIELDS.map((field) => [field.path,
    field.kind === "boolean" ? false : field.kind === "toggle" ? field.options?.[0] ?? ""
      : field.kind === "list" ? [] : field.kind === "number" ? 20 : field.kind === "duration" ? 60 : "",
  ])),
};
initial.runtime_config![path] = Number(localStorage.getItem(storageKey) ?? 720);
let persisted = initial;

client.requestMutation = async <T,>(action: string, payload?: Record<string, unknown>): Promise<T> => {
  if (action !== "settings.runtime_config.update") throw new Error(`Unexpected mutation: ${action}`);
  if (failNext) {
    failNext = false;
    throw new Error("Fixture save failed");
  }
  const values = payload?.values as Record<string, RuntimeConfigValue>;
  if (path in values) localStorage.setItem(storageKey, String(values[path]));
  persisted = { ...persisted, runtime_config: { ...persisted.runtime_config, ...values }, requires_restart: true,
    restart_required_sections: ["runtime"] };
  return persisted as T;
};

export function installIdleCompactionApi() {
  const fetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return fetch(input, init);
    const bodies: Record<string, unknown> = {
      "/api/settings": persisted,
      "/api/settings/nanobot-features": { features: [], enabled_count: 0, requires_restart: false },
      "/api/settings/api-service": { installed: false, running: false, managed: false, host: "127.0.0.1",
        port: 8900, timeout: 120, endpoint: "http://127.0.0.1:8900/v1", command: "nanobot serve" },
    };
    return Response.json(bodies[url.pathname] ?? {});
  };
}

export function IdleCompactionFixture() {
  const [snapshot, setSnapshot] = useState(initial);
  return <ClientProvider client={client} token="fixture">
    <div className="flex min-h-screen flex-col">
      <div className="flex gap-3 p-2 text-xs">
        <button onClick={() => { failNext = true; }}>Fail next save</button>
        <output aria-label="Persisted minutes">{String(snapshot.runtime_config?.[path])}</output>
      </div>
      <SettingsView themePreference="light" initialSection="runtime" initialSettings={initial}
        onSettingsChange={setSnapshot} onChangeTheme={() => {}} onBackToChat={() => {}}
        onModelNameChange={() => {}} onRestart={() => {}} />
    </div>
  </ClientProvider>;
}
