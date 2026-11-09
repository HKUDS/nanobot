import { useState } from "react";

import { SettingsView } from "@/components/settings/SettingsView";
import { settings } from "@/dev/gallery/settings";

export function installToolsCatalogPreviewApi() {
  const fetch = window.fetch.bind(window);
  window.fetch = (input, init) => String(input) === "/api/settings"
    ? Promise.resolve(Response.json(settings))
    : fetch(input, init);
}

export function ToolsCatalogFixture() {
  const [open, setOpen] = useState(true);
  return <main>
    <button onClick={() => setOpen(value => !value)}>{open ? "Leave settings" : "Open settings"}</button>
    {open && <SettingsView
      initialSection="apps"
      initialSettings={settings}
      themePreference="light"
      onChangeTheme={() => {}}
      onModelNameChange={() => {}}
      onBackToChat={() => setOpen(false)}
    />}
  </main>;
}
