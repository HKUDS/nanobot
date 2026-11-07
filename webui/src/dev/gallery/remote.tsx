import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { PairRouteSettingsView } from "@/components/remote/PairRouteSettingsView";
import { QuickPairSetupView, type PairConnectionPreview, type QuickPairSetupState } from "@/components/remote/QuickPairSetupView";
import { SSHHostPickerView } from "@/components/remote/SSHHostPickerView";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { copyTextToClipboard } from "@/lib/clipboard";
import type { SSHDiscovery } from "@/lib/remote-instances";
import { StatePicker, type ComponentExample } from "./example";
import { useGalleryTranslation } from "./i18n";
import "@/components/remote/remote-layout.css";

const routes = [{ id: "gallery-ssh", name: "开发 SSH 路由" }, { id: "gallery-vpn", name: "VPN 路由" }];
type RouteStory = "direct" | "saved_route" | "saving" | "save_error" | "refresh_error";

function RouteEditor({ story }: { story: RouteStory }) {
  const { t } = useTranslation();
  const initial = story === "saved_route" ? "saved" : story === "direct" ? "direct" : "gallery-ssh";
  const [route, setRoute] = useState(initial);
  const [original, setOriginal] = useState(story === "saving" || story === "save_error" ? "direct" : initial);
  const [saved, setSaved] = useState(story === "refresh_error");
  const [error, setError] = useState(story === "save_error" ? "remote.errors.pair_route_mismatch"
    : story === "refresh_error" ? "remote.errors.directory_unavailable" : "");
  return <PairRouteSettingsView hasSavedRoute={story === "saved_route"} routes={routes}
    route={route} original={original} busy={story === "saving"} error={error ? t(error) : ""} saved={saved}
    onRouteChange={(next) => { setRoute(next); setError(""); setSaved(false); }}
    onSave={() => { setOriginal(route); setSaved(true); setError(""); }} />;
}

function PairRoutePreview() {
  const { t } = useGalleryTranslation();
  const [story, setStory] = useState<RouteStory>("direct");
  return <>
    <StatePicker label={t("previews.pairRoute.state")} value={story} options={["direct", "saved_route", "saving", "save_error", "refresh_error"]} onChange={setStory} />
    <RouteEditor key={story} story={story} />
  </>;
}

const preview: PairConnectionPreview = {
  id: "gallery-invitation", host: "developer@dev.example", hostname: "开发主机",
  fingerprint: "SHA256:gallery-example-fingerprint", authorized_until: Date.UTC(2026, 10, 1) / 1000,
  revoke_command: "nanobot remote revoke gallery-authorization",
};
type PairStory = "invite" | "copied" | "manual" | "confirm" | "existing" | "saved_retry" | "waiting" | "expired";

function pairState(story: PairStory): QuickPairSetupState {
  return {
    request: story === "waiting" ? null : {
      id: "gallery-invitation", command: "nanobot remote pair nbpr1.gallery-example", expires: Date.now() / 1000 + (story === "expired" ? -60 : 600),
    },
    preview: story === "confirm" || story === "saved_retry" ? preview : story === "existing" ? {
      ...preview, existing_connection: { id: "gallery-host", name: "团队主机", connected: true },
    } : null,
    code: ["manual", "confirm", "existing", "saved_retry"].includes(story) ? "nbpc1.gallery-example" : "",
    saved: story === "saved_retry", busy: false, busyVisible: story === "waiting",
    error: story === "saved_retry" ? "remote.errors.ssh_connection_closed" : "",
    status: story === "waiting" ? "connecting" : "open", copied: story === "copied", expired: story === "expired",
    manual: ["manual", "confirm", "existing", "saved_retry"].includes(story), panel: null, returned: false,
  };
}

function QuickPairPreview() {
  const { t } = useGalleryTranslation();
  const [story, setStory] = useState<PairStory>("invite");
  const [state, setState] = useState(() => pairState("invite"));
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  return <div className="space-y-4">
    <StatePicker label={t("previews.quickPair.state")} value={story} options={["invite", "copied", "manual", "confirm", "existing", "saved_retry", "waiting", "expired"]}
      onChange={(next) => { setStory(next); setState(pairState(next)); setFeedback(""); }} />
    <Button variant="outline" onClick={() => setOpen(true)}>{t("previews.quickPair.open")}</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="remote-dialog max-w-sm">
        <QuickPairSetupView state={state} routeSettings={<RouteEditor story="saved_route" />}
          onStart={() => { setState(pairState("invite")); setStory("invite"); }}
          onReview={() => setState((current) => ({ ...current, preview, error: "" }))}
          onConnect={() => { setFeedback("previews.quickPair.connected"); setOpen(false); }}
          onCopyCommand={() => {
            if (!state.request) return;
            void copyTextToClipboard(state.request.command).then((copied) => setState((current) => ({
              ...current, copied, panel: copied ? null : "command", error: copied ? "" : "remote.pair.copyFailed",
            })));
          }}
          onCodeChange={(code) => setState((current) => ({ ...current, code, error: "" }))}
          onManualChange={(manual) => setState((current) => ({ ...current, manual, panel: null, error: "" }))}
          onPanelChange={(panel) => setState((current) => ({ ...current, panel }))}
          onBack={() => setState((current) => ({ ...current, preview: null, error: "", manual: current.manual || !current.request?.command }))}
          onCancel={() => setOpen(false)} onSSH={() => { setFeedback("previews.quickPair.ssh"); setOpen(false); }} />
      </DialogContent>
    </Dialog>
    <p role="status" className="text-xs text-muted-foreground">{t(feedback || "previews.quickPair.hint", { name: preview.hostname })}</p>
  </div>;
}

const discovery: SSHDiscovery = {
  hosts: [
    { host: "dev", source: "~/.ssh/config", ssh_config: "~/.ssh/config" },
    { host: "team-staging", source: "~/.ssh/team.conf", ssh_config: "~/.ssh/config" },
    { host: "team-production", source: "~/.ssh/team.conf", ssh_config: "~/.ssh/config" },
  ],
  files: ["~/.ssh/config", "~/.ssh/team.conf"], incomplete: false,
};
type SSHStory = "ready" | "custom_config" | "imported" | "loading" | "error" | "partial" | "address_only";

function SSHHostPreview() {
  const { t } = useTranslation();
  const { t: g } = useGalleryTranslation();
  const [story, setStory] = useState<SSHStory>("ready");
  const [value, setValue] = useState("");
  const [feedback, setFeedback] = useState<{ key: string; value?: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  return <div className="space-y-4">
    <StatePicker label={g("previews.sshHost.state")} value={story} options={["ready", "custom_config", "imported", "loading", "error", "partial", "address_only"]}
      onChange={(next) => { setStory(next); setValue(next === "custom_config" ? "developer@192.0.2.10" : next === "imported" ? "dev" : ""); setFeedback(null); }} />
    <SSHHostPickerView disabled={false} value={value} imported={story === "imported"}
      suggestions={story !== "address_only"} customConfig={story === "custom_config"}
      discovery={story === "error" ? null : story === "partial" ? { ...discovery, incomplete: true } : discovery}
      busy={story === "loading"} error={story === "error" ? t("remote.discoveryError") : ""}
      onRefresh={() => { setStory("ready"); setFeedback({ key: "previews.sshHost.refreshed" }); }}
      onChange={setValue} onBlur={() => setFeedback(value ? { key: "previews.sshHost.entered", value } : null)}
      inputRef={input} />
    <p role="status" className="text-xs text-muted-foreground">{feedback ? g(feedback.key, { value: feedback.value }) : g("previews.sshHost.hint")}</p>
  </div>;
}

export const remoteExamples: ComponentExample[] = [
  { title: "previews.pairRoute.title", files: ["webui/src/components/remote/PairRouteSettingsView.tsx"], Preview: PairRoutePreview,
    description: "previews.pairRoute.description",
    options: "previews.pairRoute.options",
    code: '<PairRouteSettingsView hasSavedRoute={hasSavedRoute} routes={routes} route={route} original={original} busy={busy} error={error} saved={saved} onRouteChange={setRoute} onSave={save} />' },
  { title: "previews.quickPair.title", files: ["webui/src/components/remote/QuickPairSetupView.tsx"], Preview: QuickPairPreview,
    description: "previews.quickPair.description",
    options: "previews.quickPair.options",
    code: '<QuickPairSetupView state={state} routeSettings={routeSettings} onStart={start} onReview={review} onConnect={connect} onCopyCommand={copy} onCodeChange={setCode} onManualChange={setManual} onPanelChange={setPanel} onBack={back} onCancel={cancel} onSSH={showSSH} />' },
  { title: "previews.sshHost.title", files: ["webui/src/components/remote/SSHHostPickerView.tsx"], Preview: SSHHostPreview,
    description: "previews.sshHost.description",
    options: "previews.sshHost.options",
    code: '<SSHHostPickerView disabled={false} value={host} imported={false} discovery={discovery} busy={busy} error={error} onRefresh={refresh} onChange={setHost} onBlur={validateHost} inputRef={hostInput} />' },
];
