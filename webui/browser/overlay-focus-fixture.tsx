import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { FallbackResponseSources } from "@/components/ResponseSourceBadge";
import { ModelPresetBadge } from "@/components/thread/ModelPresetBadge";
import { PromptNavigator } from "@/components/thread/PromptNavigator";
import { SessionInfoPopoverView } from "@/components/thread/SessionInfoPopoverView";
import { SettingsFeature } from "@/components/settings/shared/SettingsFeature";
import { WorkspaceProjectPicker } from "@/components/thread/WorkspaceControls";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TooltipProvider } from "@/components/ui/tooltip";
import { initializeI18n } from "@/i18n";
import "../src/globals.css";

function OverlayFocusFixture() {
  const composer = useRef<HTMLTextAreaElement>(null);
  const [preset, setPreset] = useState("First model");
  const [managing, setManaging] = useState(false);
  const [featureEnabled, setFeatureEnabled] = useState(false);
  const [featureSaving, setFeatureSaving] = useState(false);
  return <main style={{ maxWidth: 760, margin: "48px auto", padding: 24, display: "flex", flexDirection: "column", gap: 24 }}>
    <textarea ref={composer} aria-label="Composer draft" className="rounded-control border p-3" defaultValue="Keep editing here" />
    <div className="flex items-center gap-6">
      <ModelPresetBadge label={preset} modelPreset={preset} isHero={false}
        modelPresets={[{ name: "First model" }, { name: "Second model" }]}
        onPresetChange={setPreset} onRequestComposerFocus={() => composer.current?.focus()}
        onManageModels={() => setManaging(true)} />
      <PromptNavigator messages={[{ id: "prompt", role: "user", content: "Earlier question", createdAt: 1_700_000_000_000 }]}
        onJumpToPrompt={() => composer.current?.focus()} />
      <SessionInfoPopoverView jobs={[]} loading={false} loadFailed={false} now={Date.now()}
        onAction={async () => []} onEdit={async () => []} />
      <FallbackResponseSources sources={[{ preset: "Fallback model", provider: "openai", model: "gpt-4", fallback: true }]} />
    </div>
    <div className="flex items-center gap-6">
      <Dialog><DialogTrigger asChild><Button variant="outline">Open dialog</Button></DialogTrigger>
        <DialogContent aria-describedby={undefined}><DialogTitle>Example dialog</DialogTitle><input aria-label="Dialog field" /></DialogContent>
      </Dialog>
      <DropdownMenu modal={false}><DropdownMenuTrigger asChild><Button variant="outline">Open menu</Button></DropdownMenuTrigger>
        <DropdownMenuContent><DropdownMenuItem>Example action</DropdownMenuItem></DropdownMenuContent>
      </DropdownMenu>
      <Select defaultValue="first"><SelectTrigger aria-label="Example select"><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value="first">First option</SelectItem><SelectItem value="second">Second option</SelectItem></SelectContent>
      </Select>
    </div>
    <WorkspaceProjectPicker scope={{ project_path: "/workspace", access_mode: "restricted" }}
      defaultScope={{ project_path: "/workspace", access_mode: "restricted" }}
      controls={{ can_change_project: true, can_browse_directories: true }} onChange={() => {}}
      onBrowseDirectories={async () => ({ path: "/workspace", parent: "/", entries: [{ name: "project", path: "/workspace/project" }], truncated: false, host: "fixture", platform: "Linux" })} />
    <SettingsFeature title="Example feature" enabled={featureEnabled} disabled={featureSaving}
      onChange={setFeatureEnabled} onClose={() => { if (featureEnabled) setFeatureSaving(true); }}>
      <p>Feature configuration</p>
    </SettingsFeature>
    <input aria-label="Outside field" className="rounded-control border p-3" />
    <Button variant="outline">Outside button</Button>
    <Dialog open={managing} onOpenChange={setManaging}>
      <DialogContent aria-describedby={undefined}><DialogTitle>Manage models fixture</DialogTitle><input aria-label="Management field" /></DialogContent>
    </Dialog>
  </main>;
}

await initializeI18n();
createRoot(document.getElementById("root")!).render(<TooltipProvider><OverlayFocusFixture /></TooltipProvider>);
