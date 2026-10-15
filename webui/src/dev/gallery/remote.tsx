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
import "@/components/remote/remote-layout.css";

const routes = [{ id: "gallery-ssh", name: "开发 SSH 路由" }, { id: "gallery-vpn", name: "VPN 路由" }];
type RouteStory = "direct" | "saved_route" | "saving" | "save_error" | "refresh_error";

function RouteEditor({ story }: { story: RouteStory }) {
  const { t } = useTranslation();
  const initial = story === "saved_route" ? "saved" : story === "direct" ? "direct" : "gallery-ssh";
  const [route, setRoute] = useState(initial);
  const [original, setOriginal] = useState(story === "saving" || story === "save_error" ? "direct" : initial);
  const [saved, setSaved] = useState(story === "refresh_error");
  const [error, setError] = useState(story === "save_error" ? t("remote.errors.pair_route_mismatch")
    : story === "refresh_error" ? t("remote.errors.directory_unavailable") : "");
  return <PairRouteSettingsView hasSavedRoute={story === "saved_route"} routes={routes}
    route={route} original={original} busy={story === "saving"} error={error} saved={saved}
    onRouteChange={(next) => { setRoute(next); setError(""); setSaved(false); }}
    onSave={() => { setOriginal(route); setSaved(true); setError(""); }} />;
}

function PairRoutePreview() {
  const [story, setStory] = useState<RouteStory>("direct");
  return <>
    <StatePicker label="路由状态" value={story} options={["direct", "saved_route", "saving", "save_error", "refresh_error"]} onChange={setStory} />
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
  const [story, setStory] = useState<PairStory>("invite");
  const [state, setState] = useState(() => pairState("invite"));
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  return <div className="space-y-4">
    <StatePicker label="配对阶段" value={story} options={["invite", "copied", "manual", "confirm", "existing", "saved_retry", "waiting", "expired"]}
      onChange={(next) => { setStory(next); setState(pairState(next)); setFeedback(""); }} />
    <Button variant="outline" onClick={() => setOpen(true)}>打开快速配对</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="remote-dialog max-w-sm">
        <QuickPairSetupView state={state} routeSettings={<RouteEditor story="saved_route" />}
          onStart={() => { setState(pairState("invite")); setStory("invite"); }}
          onReview={() => setState((current) => ({ ...current, preview, error: "" }))}
          onConnect={() => { setFeedback("已选择连接：开发主机。"); setOpen(false); }}
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
          onCancel={() => setOpen(false)} onSSH={() => { setFeedback("已选择 SSH 连接方式。"); setOpen(false); }} />
      </DialogContent>
    </Dialog>
    <p role="status" className="text-xs text-muted-foreground">{feedback || "示例邀请与回执仅用于展示；确认动作更新本地反馈。"}</p>
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
  const [story, setStory] = useState<SSHStory>("ready");
  const [value, setValue] = useState("");
  const [feedback, setFeedback] = useState("");
  const input = useRef<HTMLInputElement>(null);
  return <div className="space-y-4">
    <StatePicker label="SSH 地址状态" value={story} options={["ready", "custom_config", "imported", "loading", "error", "partial", "address_only"]}
      onChange={(next) => { setStory(next); setValue(next === "custom_config" ? "developer@192.0.2.10" : next === "imported" ? "dev" : ""); setFeedback(""); }} />
    <SSHHostPickerView disabled={false} value={value} imported={story === "imported"}
      suggestions={story !== "address_only"} customConfig={story === "custom_config"}
      discovery={story === "error" ? null : story === "partial" ? { ...discovery, incomplete: true } : discovery}
      busy={story === "loading"} error={story === "error" ? t("remote.discoveryError") : ""}
      onRefresh={() => { setStory("ready"); setFeedback("已刷新示例地址。"); }}
      onChange={setValue} onBlur={() => setFeedback(value ? `已输入：${value}` : "")}
      inputRef={input} />
    <p role="status" className="text-xs text-muted-foreground">{feedback || "输入内容筛选地址；按方向键选择 SSH 别名。"}</p>
  </div>;
}

export const remoteExamples: ComponentExample[] = [
  { title: "PairRouteSettingsView · 配对路由", files: ["webui/src/components/remote/PairRouteSettingsView.tsx"], Preview: PairRoutePreview,
    description: "切换已存路由、保存、出错和刷新失败状态，选择路由后在本地保存。",
    options: "route 与 original 由调用方管理；routes 提供 SSH 路由。保存成功与目录刷新失败分别呈现，画廊与实际设置使用同一个视图。",
    code: '<PairRouteSettingsView hasSavedRoute={hasSavedRoute} routes={routes} route={route} original={original} busy={busy} error={error} saved={saved} onRouteChange={setRoute} onSave={save} />' },
  { title: "QuickPairSetupView · 快速配对", files: ["webui/src/components/remote/QuickPairSetupView.tsx"], Preview: QuickPairPreview,
    description: "体验邀请复制、回执输入、访问确认、已有主机和保存后重试界面。",
    options: "state 提供当前配对结果与显示状态，回调交给所属界面执行动作，routeSettings 组合路由设置。画廊使用示例数据和本地回调；实际配对由 QuickPairSetup 管理。",
    code: '<QuickPairSetupView state={state} routeSettings={routeSettings} onStart={start} onReview={review} onConnect={connect} onCopyCommand={copy} onCodeChange={setCode} onManualChange={setManual} onPanelChange={setPanel} onBack={back} onCancel={cancel} onSSH={showSSH} />' },
  { title: "SSHHostPickerView · SSH 地址", files: ["webui/src/components/remote/SSHHostPickerView.tsx"], Preview: SSHHostPreview,
    description: "筛选 SSH 别名，使用方向键选择，查看导入、读取和错误状态。",
    options: "discovery 提供当前配置文件的地址；value、busy、error 与回调由调用方控制。customConfig 保留自定义配置的别名发现行为，inputRef 用于选择后的焦点。",
    code: '<SSHHostPickerView disabled={false} value={host} imported={false} discovery={discovery} busy={busy} error={error} onRefresh={refresh} onChange={setHost} onBlur={validateHost} inputRef={hostInput} />' },
];
