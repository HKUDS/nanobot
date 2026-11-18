import { useState } from "react";

import { SettingsView } from "@/components/settings/SettingsView";
import { StartupSkeleton } from "@/components/StartupSkeleton";
import "@/components/startup-skeleton.css";
import { settings } from "@/dev/gallery/settings";

export function installToolsCatalogPreviewApi() {
  const fetch = window.fetch.bind(window);
  window.fetch = (input, init) => String(input) === "/api/settings"
    ? Promise.resolve(Response.json(settings))
    : fetch(input, init);
}

export function ToolsCatalogFixture() {
  const [open, setOpen] = useState(true);
  const params = new URLSearchParams(location.search);
  const requested = params.get("section");
  const section = requested === "skills" || requested === "channels" || requested === "automations" ? requested : "apps";
  if (params.has("startup")) return <StartupSkeleton embedded surface={section} sidebarExpanded={false} />;
  return <main className={params.has("layout") ? "h-dvh" : undefined}>
    {!params.has("layout") && <button onClick={() => setOpen(value => !value)}>{open ? "Leave settings" : "Open settings"}</button>}
    {open && <SettingsView
      initialSection={section}
      initialSettings={settings}
      showSidebar={false}
      themePreference="light"
      onChangeTheme={() => {}}
      onModelNameChange={() => {}}
      onStartAutomationChat={section === "automations" ? () => {} : undefined}
      onBackToChat={() => setOpen(false)}
    />}
  </main>;
}
