import { useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { AlertCircle, ArrowUpRight, Check, ChevronDown, ChevronLeft, FolderOpen, Laptop, Loader2, MoreHorizontal, Plus, Server } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SettingsGroup } from "@/components/settings/shared/SettingsControls";
import { CodeBlock } from "@/components/CodeBlock";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DisclosureContent } from "@/components/ui/disclosure";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useClient } from "@/providers/ClientProvider";
import { groupRemoteProfiles, isCompatibilityError, remoteAction, type RemoteInspection, type RemoteProfile } from "@/lib/remote-instances";
import { cn } from "@/lib/utils";
import { parseSSHAddress } from "@/lib/ssh-address";
import { clearPairReturn, readPairReturn, subscribePairReturn } from "@/lib/remote-pair-return";
import { useRemoteConnections } from "./RemoteInstances";
import { SSHHostPicker } from "./SSHHostPicker";
import { QuickPairSetup } from "./QuickPairSetup";
import { PairRouteSettings } from "./PairRouteSettings";
import { HostConnectionStatus } from "./HostConnectionStatus";
import { HostCompatibilityDialog } from "./HostCompatibilityDialog";
import "./remote-layout.css";

const emptyProfile = (): Omit<RemoteProfile, "id" | "connected"> => ({
  name: "", host: "", port: null, ssh_config: "", identity_file: "",
  config_path: "~/.nanobot/config.json", runtime_user: "",
});

/** The page is a server directory. Add/edit/first-use verification share one dialog. */
export function RemoteConnectionsPage({ mainNavigationExpanded = false, hostChromeInset = false, onBackToChat }: {
  mainNavigationExpanded?: boolean;
  hostChromeInset?: boolean;
  onBackToChat: () => void;
}) {
  const { t } = useTranslation();
  const { client } = useClient();
  const connections = useRemoteConnections();
  const [form, setForm] = useState(emptyProfile);
  const [editorOpen, setEditorOpen] = useState(false);
  const returnedPair = useSyncExternalStore(subscribePairReturn, readPairReturn);
  const [quickOpen, setQuickOpen] = useState(!!returnedPair);
  const [quickReturn, setQuickReturn] = useState(returnedPair);
  const [pairRoute, setPairRoute] = useState("");
  const [details, setDetails] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [versionId, setVersionId] = useState("");
  const [renaming, setRenaming] = useState<RemoteProfile | null>(null);
  const [name, setName] = useState("");
  const [renameError, setRenameError] = useState("");
  const [editing, setEditing] = useState(false);
  const [savedId, setSavedId] = useState("");
  const [busy, setBusy] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const error = errorCode ? t(`remote.errors.${errorCode}`, { defaultValue: t("remote.errors.unknown") }) : "";
  const [sshOptions, setSSHOptions] = useState(false);
  const [manualLocation, setManualLocation] = useState(false);
  const [inspection, setInspection] = useState<RemoteInspection | null>(null);
  const [inspectBeforeConnect, setInspectBeforeConnect] = useState(true);
  const [commandImported, setCommandImported] = useState(false);
  const [removing, setRemoving] = useState<RemoteProfile | null>(null);
  const [disconnecting, setDisconnecting] = useState<RemoteProfile | null>(null);
  const lastRemoval = useRef<RemoteProfile | null>(null);
  const lastDisconnect = useRef<RemoteProfile | null>(null);
  const [fingerprint, setFingerprint] = useState<{ id: string; fingerprint: string; challenge: string; inspect: boolean } | null>(null);
  const hostInput = useRef<HTMLInputElement>(null);
  const editorTrigger = useRef<HTMLButtonElement | null>(null);
  const mounted = useRef(true);
  const operation = useRef(0);
  const optionsId = useId();
  const statusId = useId();
  const nameId = useId();
  const nameInput = useRef<HTMLInputElement>(null);
  const refresh = connections?.refresh;
  const page = useRef<HTMLDivElement>(null);
  useEffect(() => { if (connections?.managing) page.current?.focus({ preventScroll: true }); }, [connections?.managing]);

  // Keep confirmation content intact during Radix's exit animation.
  useEffect(() => { if (removing) lastRemoval.current = removing; }, [removing]);
  useEffect(() => { if (disconnecting) lastDisconnect.current = disconnecting; }, [disconnecting]);

  useEffect(() => { if (returnedPair) { setQuickReturn(returnedPair); setQuickOpen(true); } }, [returnedPair]);

  useEffect(() => {
    mounted.current = true;
    void refresh?.().catch(() => {});
    return () => { mounted.current = false; operation.current += 1; };
  }, [refresh]);

  if (!connections) return null;
  const { directory, directoryError, connect: connectHost, disconnect: disconnectHost } = connections;
  const wanted = (attempt: number) => mounted.current && attempt === operation.current;
  const showError = (reason: unknown) => {
    const code = reason instanceof Error ? reason.message : "unknown";
    if (/^(ssh_|host_key_|local_file_not_found)/.test(code)) {
      setInspection(null); setManualLocation(false); setInspectBeforeConnect(true);
    }
    setErrorCode(code);
  };
  const closeEditor = () => {
    operation.current += 1;
    if (busy) connections.cancel();
    setBusy(""); setEditorOpen(false); setFingerprint(null); setErrorCode("");
  };
  const beginEditor = (profile?: RemoteProfile) => {
    operation.current += 1;
    setEditing(!!profile); setSavedId(profile?.id || "");
    setSSHOptions(false); setManualLocation(false); setInspection(null);
    setInspectBeforeConnect(!profile); setErrorCode("");
    setForm(profile ? { name: profile.name, host: profile.host, port: profile.port,
      ssh_config: profile.ssh_config, identity_file: profile.identity_file,
      config_path: profile.config_path, runtime_user: profile.runtime_user } : emptyProfile());
    setCommandImported(false); setEditorOpen(true); setFingerprint(null);
  };

  const importCommand = () => {
    if (!/^ssh\s/.test(form.host.trim())) return;
    try {
      setForm({ ...form, ...parseSSHAddress(form.host) });
      setCommandImported(true); setErrorCode("");
    } catch (reason) { showError(reason); }
  };

  const pickFile = async (field: "ssh_config" | "identity_file") => {
    const attempt = ++operation.current;
    setBusy(`pick-${field}`); setErrorCode("");
    try {
      const result = await remoteAction<{ path: string | null }>(client, "pick_file", {});
      if (wanted(attempt) && typeof result.path === "string" && result.path) {
        setForm((previous) => ({ ...previous, [field]: result.path }));
      }
    } catch (reason) { if (wanted(attempt)) showError(reason); }
    finally { if (wanted(attempt)) setBusy(""); }
  };
  const filePicker = (field: "ssh_config" | "identity_file") => <Button type="button" variant="ghost" size="icon" className="shrink-0"
    disabled={!!busy} title={t("remote.setup.chooseFile", { field: t(`remote.${field}`) })}
    aria-label={t("remote.setup.chooseFile", { field: t(`remote.${field}`) })} onClick={() => { void pickFile(field); }}>
    {busy === `pick-${field}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
  </Button>;

  const connect = async (id: string, attempt = ++operation.current, inspect = false) => {
    setBusy(inspect ? "inspect" : id); setErrorCode("");
    try {
      if (inspect) {
        const result = await remoteAction<RemoteInspection>(client, "inspect", { id });
        if (!wanted(attempt)) return;
        if (!result || !Array.isArray(result.candidates) || typeof result.hostname !== "string") throw new Error("probe_failed");
        setInspection(result);
        setInspectBeforeConnect(false);
        const single = result.candidates.length === 1 ? result.candidates[0] : null;
        if (single) setForm((previous) => ({ ...previous, config_path: single.config_path, runtime_user: single.runtime_user }));
        else if (result.candidates.length) setForm((previous) => ({ ...previous, config_path: "", runtime_user: "" }));
        // Only the unambiguous login-user default is automatic. Service accounts
        // always require an explicit choice before attempting existing sudo access.
        if (!single || single.runtime_user) {
          setManualLocation(!result.candidates.length);
          return;
        }
        // Keep the submitted profile (including a newly imported SSH command).
        const address = parseSSHAddress(form.host);
        const profile = { ...form, ...address,
          name: form.name.trim() || address.host,
          config_path: single.config_path, runtime_user: single.runtime_user };
        if (profile.config_path !== form.config_path || profile.runtime_user !== form.runtime_user) {
          await remoteAction(client, "save", { id, profile });
        }
        if (!wanted(attempt)) return;
        await refresh?.();
        if (!wanted(attempt)) return;
        setBusy(id);
      }
      await connectHost(id, () => wanted(attempt));
      if (wanted(attempt)) { setEditorOpen(false); setFingerprint(null); }
    } catch (reason) {
      if (!wanted(attempt)) return;
      if (reason instanceof Error && reason.message === "local_webui_unavailable") {
        showError(reason);
        return;
      }
      if (reason instanceof Error && isCompatibilityError(reason.message)) {
        await refresh?.().catch(() => {});
        if (wanted(attempt)) { setEditorOpen(false); setVersionId(id); showError(reason); }
        return;
      }
      if (reason instanceof Error && reason.message === "host_key_unknown") {
        try {
          const result = await remoteAction<{ fingerprint: string; challenge: string }>(client, "fingerprint", { id });
          if (wanted(attempt)) setFingerprint({ id, ...result, inspect });
        } catch (scanError) { if (wanted(attempt)) showError(scanError); }
      } else {
        if (!editorOpen) {
          const profile = directory?.profiles.find((item) => item.id === id);
          if (profile && !profile.paired) {
            setForm({ name: profile.name, host: profile.host, port: profile.port,
              ssh_config: profile.ssh_config, identity_file: profile.identity_file,
              config_path: profile.config_path, runtime_user: profile.runtime_user });
            setSavedId(id); setEditing(false); setEditorOpen(true); setInspectBeforeConnect(true);
            setInspection(null); setManualLocation(false); setSSHOptions(false);
          }
        }
        showError(reason);
      }
    } finally { if (wanted(attempt)) setBusy(""); }
  };

  const trustHost = async () => {
    if (!fingerprint) return;
    const attempt = ++operation.current;
    const id = fingerprint.id;
    setBusy("trust"); setErrorCode("");
    try {
      await remoteAction(client, "trust", { id, challenge: fingerprint.challenge });
      if (wanted(attempt)) { setFingerprint(null); await connect(id, attempt, fingerprint.inspect); }
    } catch (reason) { if (wanted(attempt)) showError(reason); }
    finally { if (wanted(attempt)) setBusy(""); }
  };

  const save = async () => {
    const attempt = ++operation.current;
    setBusy("save"); setErrorCode("");
    try {
      // Also parse here for Enter submission, which doesn't blur the address.
      const address = parseSSHAddress(form.host);
      const normalized = { ...form, ...address, name: form.name.trim() || address.host };
      setForm({ ...form, ...address });
      const result = await remoteAction<{ id: string }>(client, "save", {
        id: savedId, profile: normalized,
      });
      // Retain the saved id on failures so retry never creates duplicate profiles.
      if (wanted(attempt)) setSavedId(result.id);
      await refresh?.();
      if (!wanted(attempt)) return;
      if (editing) setEditorOpen(false);
      else await connect(result.id, attempt, inspectBeforeConnect && !manualLocation);
    } catch (reason) { if (wanted(attempt)) showError(reason); }
    finally { if (wanted(attempt)) setBusy(""); }
  };

  const remove = async () => {
    if (!removing) return;
    setBusy("remove"); setErrorCode("");
    try {
      await connections.remove(removing.id);
      if (mounted.current) setRemoving(null);
    } catch (reason) { if (mounted.current) showError(reason); }
    finally { if (mounted.current) setBusy(""); }
  };
  const rename = async () => {
    if (!renaming || busy || !name.trim() || name.trim() === renaming.name) return;
    setBusy("rename"); setRenameError("");
    try {
      await connections.rename(renaming.id, name.trim());
      if (mounted.current) setRenaming(null);
    } catch (reason) {
      if (mounted.current) setRenameError(t(`remote.errors.${reason instanceof Error ? reason.message : "unknown"}`, { defaultValue: t("remote.errors.unknown") }));
    } finally { if (mounted.current) setBusy(""); }
  };
  const disconnect = async (id: string) => {
    setBusy(id); setErrorCode("");
    try { await disconnectHost(id); if (mounted.current) setDisconnecting(null); }
    catch (reason) { if (mounted.current) showError(reason); }
    finally { if (mounted.current) setBusy(""); }
  };
  const pageError = error || (directoryError ? t("remote.errors.directory_unavailable") : "");
  const nanobotError = /^(config_|runtime_user_|webui_|remote_auth_|remote_unreachable|incompatible_gateway|public_ws_|python_|probe_failed)/.test(errorCode);
  const locationStep = !!inspection || manualLocation || nanobotError;
  const openingProfile = !editorOpen && !fingerprint && !removing && !disconnecting
    ? directory?.profiles.find((profile) => profile.id === busy) : null;
  const editorAction = editing ? "remote.save" : locationStep ? "remote.setup.openNanobot" : "remote.connect";
  const editorLabel = !busy || busy.startsWith("pick-") ? editorAction : busy === "save" ? "remote.saving"
    : busy === "inspect" ? "remote.setup.checking" : "remote.setup.opening";
  const editingProfile = editing ? directory?.profiles.find((profile) => profile.id === savedId) : null;
  const removalProfile = removing || lastRemoval.current;
  const disconnectProfile = disconnecting || lastDisconnect.current;
  const editSSH = () => {
    setInspection(null); setManualLocation(false); setInspectBeforeConnect(true);
    setErrorCode(""); setSSHOptions(true);
  };
  const groups = groupRemoteProfiles(directory?.profiles || [], connections.activeHostId);
  const detailGroup = groups.find((group) => group.id === details);
  const detailConnection = detailGroup?.connections.find((profile) => profile.connected || connections.openHostIds.includes(profile.id));
  const removalIsShared = groups.some((group) => group.connections.length > 1 && group.connections.some((profile) => profile.id === removalProfile?.id));
  const connectionActions = (profile: RemoteProfile, grouped = false) => <>
    {!profile.paired && <DropdownMenuItem disabled={profile.connected || connections.openHostIds.includes(profile.id)} onSelect={() => { setDetailsOpen(false); beginEditor(profile); }}>{t("remote.edit")}</DropdownMenuItem>}
    {profile.paired && <DropdownMenuItem disabled={profile.connected || connections.openHostIds.includes(profile.id)} onSelect={() => { setDetailsOpen(false); setPairRoute(profile.id); setRouteOpen(true); }}>{t("remote.pair.route")}</DropdownMenuItem>}
    {(profile.connected || connections.openHostIds.includes(profile.id)) && <DropdownMenuItem onSelect={() => { setDetailsOpen(false); setErrorCode(""); setDisconnecting(profile); }}>{t("remote.disconnect")}</DropdownMenuItem>}
    <DropdownMenuItem tone="destructive" onSelect={() => { setDetailsOpen(false); setErrorCode(""); setRemoving(profile); }}>{t(grouped ? "remote.sameInstance.forgetConnection" : "remote.forget")}</DropdownMenuItem>
  </>;

  return <div ref={page} tabIndex={-1} role="region" aria-label={t("remote.title")} className="flex min-h-0 flex-1 flex-col overflow-hidden bg-settings-canvas outline-none">
    <div className="min-w-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
      <div data-settings-section="remote" data-main-navigation-expanded={mainNavigationExpanded}
        className={cn("settings-grid settings-feature-page mx-auto w-full animate-in fade-in-0 slide-in-from-bottom-1 py-6 duration-200 ease-out motion-reduce:animate-none sm:py-8 lg:py-12",
          hostChromeInset && "pt-[4.25rem] sm:pt-[4.25rem] lg:pt-[4.75rem]")}>
        <div className="settings-feature-header mb-7">
          <Button variant="ghost" size="sm" className={cn("touch-target mb-4 gap-1", !connections.managing && "lg:hidden")} onClick={onBackToChat}>
            <ChevronLeft className="h-4 w-4" />{t(connections.managing ? "remote.back" : "settings.backToChat")}
          </Button>
          <h1 className="text-[24px] font-normal leading-tight tracking-normal text-foreground sm:text-[28px]">{t("remote.title")}</h1>
        </div>
        <div className="settings-stack">
          <p className="settings-list-inset text-[13px] leading-6 text-muted-foreground">{t("remote.description")}</p>
          {directory?.available && <>
            <SettingsGroup>
              <button type="button" className="settings-list-row settings-hover flex w-full items-center gap-3 py-3 text-left"
                aria-current={connections.localActive || undefined} onClick={connections.selectLocal}>
                <Laptop className="h-[18px] w-[18px] shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1"><span className="block text-[14px] font-medium">{t("remote.local")}</span>
                  {directory.machine_name && <span className="mt-0.5 block truncate text-xs text-muted-foreground">{directory.machine_name}</span>}</span>
                {connections.localActive && <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><Check className="h-3.5 w-3.5" />{t("remote.current")}</span>}
              </button>
            </SettingsGroup>
            {directory.profiles.length > 0 && <SettingsGroup>
              {groups.map(({ id: groupId, profile, connections: entries }) => <div key={groupId} className="settings-list-row settings-hover flex items-center gap-2 transition-colors">
                <button type="button" aria-label={`${profile.name} ${profile.host}`} aria-describedby={`${statusId}-${profile.id}`}
                  aria-current={connections.activeHostId === profile.id || undefined}
                  className="flex min-h-[60px] min-w-0 flex-1 items-center gap-3 rounded-xl py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" disabled={!!busy} onClick={(event) => {
                  editorTrigger.current = event.currentTarget; void connect(profile.id);
                }}>
                  {busy === profile.id ? <Loader2 className="h-[18px] w-[18px] shrink-0 animate-spin text-muted-foreground" /> : <Server className="h-[18px] w-[18px] shrink-0 text-muted-foreground" />}
                  <span className="min-w-0 flex-1"><span className="block truncate text-[14px] font-medium">{profile.name}</span><span className="mt-0.5 block truncate text-xs text-muted-foreground">{profile.host}</span>
                    {groups.some((other) => other.id !== groupId && other.profile.name === profile.name && other.profile.host === profile.host) && <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={profile.config_path}>{profile.port ? `:${profile.port} · ` : ""}{profile.config_path}</span>}
                    <span id={`${statusId}-${profile.id}`} className="mt-1 block"><HostConnectionStatus state={connections.hostStates[profile.id] || "closed"} /></span>
                    {profile.compatibility && profile.compatibility.status !== "compatible" && <span className="mt-1 block text-xs text-muted-foreground">
                      {t(`remote.compatibility.${profile.compatibility.status}`)}
                    </span>}
                    {profile.paired && typeof profile.authorized_until === "number" && Number.isFinite(profile.authorized_until)
                      && profile.authorized_until * 1000 <= Date.now() + 7 * 86_400_000 && <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                        {t(profile.authorized_until * 1000 <= Date.now() ? "remote.pair.expiredDevice" : "remote.pair.expiringDevice", {
                          date: new Date(profile.authorized_until * 1000).toLocaleDateString(),
                        })}
                      </span>}
                  </span>
                  {connections.activeHostId === profile.id ? <Check aria-label={t("remote.current")} className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ArrowUpRight aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />}
                </button>
                <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" disabled={!!busy}
                  onPointerDown={(event) => { editorTrigger.current = event.currentTarget; }}
                  onKeyDown={(event) => { editorTrigger.current = event.currentTarget; }}
                  aria-label={t("remote.manage", { name: profile.name })}><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => { setRenaming(profile); setName(profile.name); setRenameError(""); }}>{t("remote.rename.action")}</DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setVersionId(profile.id)}>{t("remote.compatibility.title")}</DropdownMenuItem>
                    {entries.length > 1 ? <DropdownMenuItem onSelect={() => { setDetails(groupId); setDetailsOpen(true); }}>{t("remote.sameInstance.details")}</DropdownMenuItem> : connectionActions(profile)}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>)}
            </SettingsGroup>}
            {openingProfile && <div className="settings-list-inset flex items-center justify-between gap-3">
              <p role="status" className="min-w-0 truncate text-xs text-muted-foreground">{t("remote.preparing", { name: openingProfile.name })}</p>
              <Button variant="ghost" size="sm" className="shrink-0" onClick={closeEditor}>{t("remote.cancelSwitch")}</Button>
            </div>}
            <div className="settings-list-inset"><Button variant="ghost" className="remote-action gap-2" disabled={!!busy} onClick={(event) => {
              editorTrigger.current = event.currentTarget; setQuickReturn(null); setQuickOpen(true);
            }}><Plus className="h-4 w-4" />{t("remote.add")}</Button></div>
          </>}
          {!directory && !directoryError && <div role="status" className="settings-list-inset flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t("remote.loading")}</div>}
          {directory && !directory.available && <p className="settings-list-inset text-sm text-muted-foreground">{t("remote.unavailable")}</p>}
          {pageError && !editorOpen && !fingerprint && !removing && !disconnecting && <div className="settings-list-inset space-y-2">
            <p role="alert" className="remote-alert items-start gap-2 text-[13px] leading-5 text-foreground"><AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />{pageError}</p>
            {directoryError && <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => {
              setBusy("refresh"); setErrorCode(""); void refresh?.().catch((reason: unknown) => { if (mounted.current) showError(reason); }).finally(() => { if (mounted.current) setBusy(""); });
            }}>{t("remote.retry")}</Button>}
          </div>}
        </div>
      </div>
    </div>

    <HostCompatibilityDialog profile={directory?.profiles.find((profile) => profile.id === versionId)}
      clientVersion={directory?.client_version} onClose={() => setVersionId("")} />
    <Dialog open={!!renaming} onOpenChange={(open) => { if (!open && !busy) setRenaming(null); }}>
      <DialogContent className="remote-dialog max-h-[85dvh] max-w-sm overflow-y-auto" onOpenAutoFocus={(event) => {
        event.preventDefault(); nameInput.current?.focus(); nameInput.current?.select();
      }} onCloseAutoFocus={(event) => { event.preventDefault(); editorTrigger.current?.focus({ preventScroll: true }); }}>
        <DialogHeader className="pr-5 text-left">
          <DialogTitle>{t("remote.rename.title")}</DialogTitle>
          <DialogDescription>{t("remote.rename.hint")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void rename(); }}>
          <Input ref={nameInput} id={nameId} value={name} maxLength={64} required disabled={!!busy}
            aria-label={t("remote.rename.name")}
            aria-invalid={!!renameError} aria-describedby={renameError ? `${nameId}-error` : undefined}
            onChange={(event) => { setName(event.target.value); setRenameError(""); }} />
          {renameError && <p id={`${nameId}-error`} role="alert" className="text-[13px] leading-5 text-foreground">{renameError}</p>}
          <div className="remote-dialog-actions">
            <Button type="button" variant="ghost" disabled={!!busy} onClick={() => setRenaming(null)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={!!busy || !name.trim() || name.trim() === renaming?.name} aria-busy={!!busy}>
              {busy && <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />}{t(busy ? "remote.saving" : "remote.save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
    <Dialog open={detailsOpen && !!detailGroup} onOpenChange={(open) => { if (!open) setDetailsOpen(false); }}>
      <DialogContent className="remote-dialog flex max-h-[85dvh] max-w-md flex-col overflow-hidden">
        <DialogHeader className="pr-5 text-left"><DialogTitle>{t("remote.sameInstance.details")}</DialogTitle><DialogDescription>{t("remote.sameInstance.detailsHint")}</DialogDescription></DialogHeader>
        <div className="min-h-0 space-y-2 overflow-y-auto">
          {detailGroup?.connections.map((profile, index) => <div key={profile.id} className="flex items-center gap-2 rounded-2xl bg-muted/40 p-3">
            <button type="button" disabled={!!busy || (!!detailConnection && detailConnection.id !== profile.id)} aria-current={connections.activeHostId === profile.id || undefined}
              className="min-w-0 flex-1 rounded-xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => { setDetailsOpen(false); void connect(profile.id); }}>
              <span className="flex items-center gap-2 text-[13px] font-medium">{t("remote.sameInstance.connection", { count: index + 1 })}{connections.activeHostId === profile.id && <Check aria-label={t("remote.current")} className="h-3.5 w-3.5" />}</span>
              <span className="mt-1 block truncate text-xs text-muted-foreground">{profile.host}</span>
              <HostConnectionStatus state={connections.hostStates[profile.id] || "closed"} />
              {profile.authorized_until != null && <span className="mt-1 block text-xs text-muted-foreground">{t(profile.authorized_until * 1000 <= Date.now() ? "remote.pair.expiredDevice" : "remote.pair.expiringDevice", { date: new Date(profile.authorized_until * 1000).toLocaleString() })}</span>}
            </button>
            <DropdownMenu><DropdownMenuTrigger asChild><Button size="icon" variant="ghost" className="h-8 w-8 shrink-0" disabled={!!busy} aria-label={t("remote.sameInstance.manageConnection", { count: index + 1 })}><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">{connectionActions(profile, true)}</DropdownMenuContent>
            </DropdownMenu>
          </div>)}
        </div>
        {detailConnection && <p className="text-xs leading-5 text-muted-foreground">{t("remote.sameInstance.switchHint")}</p>}
      </DialogContent>
    </Dialog>

    <Dialog open={quickOpen} onOpenChange={(open) => { setQuickOpen(open); if (!open) clearPairReturn(); }}>
      <DialogContent className="remote-dialog flex max-h-[85dvh] max-w-md flex-col overflow-hidden">
        <QuickPairSetup key={quickReturn?.code || "new"} returned={quickReturn} active={quickOpen} onSSH={() => { clearPairReturn(); setQuickOpen(false); beginEditor(); }} onClose={() => { clearPairReturn(); setQuickOpen(false); }} />
      </DialogContent>
    </Dialog>
    <Dialog open={routeOpen} onOpenChange={setRouteOpen}>
      <DialogContent className="remote-dialog max-w-md overflow-y-auto"><DialogHeader className="pr-5 text-left"><DialogTitle>{t("remote.pair.route")}</DialogTitle><DialogDescription>{t("remote.pair.routeHint")}</DialogDescription></DialogHeader>
        {pairRoute && <PairRouteSettings key={pairRoute} id={pairRoute} showHint={false} onSaved={() => setRouteOpen(false)} />}
      </DialogContent>
    </Dialog>
    <Dialog open={editorOpen || !!fingerprint} onOpenChange={(open) => { if (!open) closeEditor(); }}>
      <DialogContent className="remote-dialog flex max-h-[85dvh] max-w-md flex-col overflow-hidden" onOpenAutoFocus={(event) => {
        if (!fingerprint) { event.preventDefault(); hostInput.current?.focus(); }
      }} onCloseAutoFocus={(event) => {
        event.preventDefault();
        if (!editorTrigger.current?.closest("[inert]")) editorTrigger.current?.focus({ preventScroll: true });
      }}>
        <DialogHeader className="shrink-0 pr-5 text-left">
          <DialogTitle>{t(fingerprint ? "remote.verifyTitle" : editing ? "remote.edit" : "remote.addTitle")}</DialogTitle>
          <DialogDescription>{t(fingerprint ? "remote.verifyDescription" : editing ? "remote.editDescription" : "remote.addDescription")}</DialogDescription>
        </DialogHeader>
        {fingerprint ? <>
          <div className="space-y-2 rounded-2xl bg-muted/40 p-3">
            <p className="break-all text-[13px] font-medium">{directory?.profiles.find((profile) => profile.id === fingerprint.id)?.host || form.host}</p>
            <code className="block select-text break-all text-xs text-muted-foreground">{fingerprint.fingerprint}</code>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">{t("remote.verifyHint")}</p>
          {error && <p role="alert" className="remote-alert items-start gap-2 text-[13px] leading-5 text-foreground"><AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /><span>{error}</span></p>}
          <div className="remote-dialog-actions">
            {editorOpen && <Button variant="ghost" disabled={!!busy} className="gap-1" onClick={() => { setFingerprint(null); setErrorCode(""); setInspection(null); setInspectBeforeConnect(true); }}><ChevronLeft className="h-4 w-4" />{t("remote.back")}</Button>}
            <Button variant="ghost" onClick={closeEditor}>{t("common.cancel")}</Button>
            <Button className="col-span-2 h-auto min-h-10 whitespace-normal" disabled={!!busy} aria-busy={!!busy} onClick={() => { void trustHost(); }}>{busy && <Loader2 aria-hidden className="mr-2 h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" />}{t("remote.verifyConnect")}</Button>
          </div>
        </> : <form onSubmit={(event) => { event.preventDefault(); if (!busy && form.host.trim() && (!locationStep || form.config_path.trim())) void save(); }} className="flex min-h-0 flex-col gap-4">
          <div className="-mx-1 min-h-0 space-y-4 overflow-y-auto overscroll-contain px-1">
          {!editing && <ol aria-label={t("remote.setup.progress")} className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <li aria-current={!locationStep ? "step" : undefined} className={cn("flex items-center gap-1.5", !locationStep && "text-foreground")}>
              {locationStep ? <Check className="h-3.5 w-3.5" /> : <span>1</span>}{t("remote.setup.server")}</li>
            <li aria-hidden="true" className="h-px w-5 bg-border" />
            <li aria-current={locationStep ? "step" : undefined} className={cn("flex items-center gap-1.5", locationStep && "text-foreground")}><span>2</span>{t("remote.setup.nanobot")}</li>
          </ol>}
          {locationStep && !editing ? <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 rounded-2xl bg-muted/40 px-3 py-2.5">
              <span className="min-w-0 text-[13px]"><span className="block font-medium">{t("remote.setup.signedIn")}</span><span className="block truncate text-xs text-muted-foreground">{form.host}</span></span>
              <Button type="button" size="sm" variant="ghost" className="remote-action" disabled={!!busy} onClick={editSSH}>{t("remote.setup.changeServer")}</Button>
            </div>
            {!!inspection?.candidates.length && <fieldset className="space-y-2">
              <legend className="mb-2 text-[13px] font-medium">{t("remote.setup.chooseNanobot")}</legend>
              {inspection.candidates.map((candidate) => <label key={candidate.config_path + candidate.runtime_user} className={cn("flex cursor-pointer items-start gap-3 rounded-2xl border p-3 transition-colors", !manualLocation && form.config_path === candidate.config_path && form.runtime_user === candidate.runtime_user ? "border-foreground/30 bg-muted/40" : "border-border hover:bg-muted/30")}>
                <input type="radio" name="nanobot-location" className="mt-1 accent-foreground" disabled={!!busy}
                  checked={!manualLocation && form.config_path === candidate.config_path && form.runtime_user === candidate.runtime_user}
                  onChange={() => { setManualLocation(false); setForm({ ...form, config_path: candidate.config_path, runtime_user: candidate.runtime_user }); setErrorCode(""); }} />
                <span className="min-w-0 text-[13px]"><span className="block font-medium [overflow-wrap:anywhere]">{candidate.service || t("remote.setup.yourNanobot")}</span>
                  <span className="block break-all text-xs leading-5 text-muted-foreground">{candidate.config_path}</span>
                  {candidate.runtime_user && <span className="mt-1 block text-xs leading-5 text-muted-foreground">{t("remote.setup.serviceAccount", { user: candidate.runtime_user })}</span>}
                </span>
              </label>)}
            </fieldset>}
            {inspection && !inspection.candidates.length && <div className="space-y-1">
              <p className="text-[13px] font-medium">{t("remote.setup.notFound")}</p>
              <p className="text-xs leading-5 text-muted-foreground">{t("remote.setup.notFoundHint")}</p>
            </div>}
            {inspection?.incomplete && <p className="text-xs leading-5 text-muted-foreground">{t("remote.setup.limitedSearch")}</p>}
            {!manualLocation && <Button type="button" variant="ghost" size="sm" className="remote-action" disabled={!!busy} onClick={() => setManualLocation(true)}>{t("remote.setup.manualLocation")}</Button>}
          </div> : <>
            <SSHHostPicker inputRef={hostInput} disabled={!!busy} value={form.host} configFile={form.ssh_config} imported={commandImported}
              suggestions={!editingProfile || form.host !== editingProfile.host || form.ssh_config !== editingProfile.ssh_config}
              onChange={(host) => { setForm({ ...form, host }); setCommandImported(false); setErrorCode(""); }} onBlur={importCommand} />
            <div>
            <button type="button" disabled={!!busy} aria-expanded={sshOptions} aria-controls={optionsId}
              className="flex min-h-9 items-center gap-2 rounded-xl text-[13px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => setSSHOptions(!sshOptions)}>
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", sshOptions && "rotate-180")} />{t("remote.connectionOptions")}
            </button>
            <DisclosureContent id={optionsId} open={sshOptions} className="space-y-3 pb-1 pt-3">
            <RemoteField label={t("remote.ssh_config")} value={form.ssh_config} placeholder="~/.ssh/config" disabled={!!busy} onChange={(ssh_config) => setForm({ ...form, ssh_config })} action={filePicker("ssh_config")} />
            <RemoteField label={t("remote.identity_file")} value={form.identity_file} disabled={!!busy} onChange={(identity_file) => setForm({ ...form, identity_file })} action={filePicker("identity_file")} />
            <p className="text-xs leading-5 text-muted-foreground">{t("remote.setup.keyHint")}</p>
            <RemoteField label={t("remote.sshPort")} value={form.port == null ? "" : String(form.port)} placeholder={t("remote.portPlaceholder")} type="number" min={1} max={65535} disabled={!!busy}
              onChange={(port) => setForm({ ...form, port: port === "" ? null : Number(port) })} />
            <RemoteField label={t("remote.name")} value={form.name} placeholder={form.host || t("remote.namePlaceholder")} disabled={!!busy} onChange={(name) => setForm({ ...form, name })} />
            </DisclosureContent>
            </div>
          </>}
          {(editing || manualLocation || nanobotError) && <div className="space-y-3">
            <RemoteField label={t("remote.config_path")} value={form.config_path} disabled={!!busy} onChange={(config_path) => setForm({ ...form, config_path })} />
            <RemoteField label={t("remote.runtime_user")} value={form.runtime_user} disabled={!!busy} onChange={(runtime_user) => setForm({ ...form, runtime_user })} />
            <p className="text-xs leading-5 text-muted-foreground">{t("remote.setup.locationHint")}</p>
          </div>}
          </div>
          <div className="shrink-0 space-y-3 pt-1">
          {error && <div className="space-y-1">
            <p role="alert" className="remote-alert items-start gap-2 text-[13px] leading-5 text-foreground"><AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /><span>{error}</span></p>
            {!sshOptions && /^(ssh_|local_file_not_found)/.test(errorCode) && <Button type="button" variant="ghost" size="sm" disabled={!!busy} onClick={editSSH}>{t("remote.setup.sshSettings")}</Button>}
          </div>}
          {busy.startsWith("pick-") && <p role="status" className="text-xs text-muted-foreground">{t("remote.setup.pickingFile")}</p>}
          <div className="remote-dialog-actions">
            <Button type="button" variant="ghost" onClick={closeEditor}>{t("common.cancel")}</Button>
            <Button type="submit" className="min-w-0" title={t(editorLabel)} aria-label={t(editorLabel)} aria-busy={!!busy} disabled={!!busy || !form.host.trim() || (locationStep && !form.config_path.trim())}>
              {busy && !busy.startsWith("pick-") && <Loader2 aria-hidden className="mr-2 h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" />}
              <span role={busy && !busy.startsWith("pick-") ? "status" : undefined} className="min-w-0">{t(editorLabel)}</span>
            </Button>
          </div>
          </div>
        </form>}
      </DialogContent>
    </Dialog>
    <Dialog open={!!disconnecting} onOpenChange={(value) => { if (!value && !busy) setDisconnecting(null); }}>
      <DialogContent className="remote-dialog max-h-[85dvh] max-w-sm overflow-y-auto"><DialogHeader className="pr-5 text-left"><DialogTitle className="leading-snug [overflow-wrap:anywhere]">{t("remote.disconnectTitle", { name: disconnectProfile?.name })}</DialogTitle><DialogDescription>{t("remote.disconnectDescription")}</DialogDescription></DialogHeader>
        {error && <p role="alert" className="remote-alert items-start gap-2 text-[13px] leading-5 text-foreground"><AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /><span>{error}</span></p>}
        <div className="remote-dialog-actions"><Button variant="ghost" disabled={!!busy} onClick={() => setDisconnecting(null)}>{t("common.cancel")}</Button><Button variant="outline" className="min-w-0" disabled={!!busy} aria-busy={!!busy} onClick={() => { if (disconnecting) void disconnect(disconnecting.id); }}>{busy && <Loader2 aria-hidden className="mr-2 h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" />}<span>{t("remote.disconnect")}</span></Button></div>
      </DialogContent>
    </Dialog>
    <Dialog open={!!removing} onOpenChange={(value) => { if (!value && !busy) setRemoving(null); }}>
      <DialogContent className="remote-dialog max-h-[85dvh] max-w-sm overflow-y-auto"><DialogHeader className="pr-5 text-left"><DialogTitle className="leading-snug [overflow-wrap:anywhere]">{t(removalIsShared ? "remote.sameInstance.forgetTitle" : "remote.forgetTitle", { name: removalProfile?.name })}</DialogTitle><DialogDescription>{t(removalIsShared ? "remote.sameInstance.forgetHint" : "remote.forgetDescription")}</DialogDescription></DialogHeader>
        {removalProfile && (removalProfile.connected || connections.openHostIds.includes(removalProfile.id)) && <p role="note" className="rounded-xl bg-muted/40 p-3 text-xs leading-5">{t("remote.activeForgetWarning")}</p>}
        {removalProfile?.paired && <div className="space-y-2 text-xs leading-5 text-muted-foreground"><p>{t("remote.pair.forgetHint")}</p>{removalProfile.revoke_command && <CodeBlock language="bash" code={removalProfile.revoke_command} highlight={false} className="min-w-0 [&_pre]:[overflow-wrap:anywhere]" />}</div>}
        {error && <p role="alert" className="remote-alert items-start gap-2 text-[13px] leading-5 text-foreground"><AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /><span>{error}</span></p>}
        <div className="remote-dialog-actions"><Button variant="ghost" disabled={!!busy} onClick={() => setRemoving(null)}>{t("common.cancel")}</Button><Button variant="destructive" className="h-auto min-h-10 min-w-0" disabled={!!busy} aria-busy={!!busy} onClick={() => { void remove(); }}>{busy && <Loader2 aria-hidden className="mr-2 h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" />}<span className="whitespace-normal break-words">{t(removalIsShared ? "remote.sameInstance.forgetAction" : "remote.forget")}</span></Button></div>
      </DialogContent>
    </Dialog>
  </div>;
}

function RemoteField({ label, onChange, action, ...props }: {
  label: string; value: string; onChange: (value: string) => void;
  action?: ReactNode;
  placeholder?: string; disabled?: boolean; type?: string; min?: number; max?: number;
}) {
  const id = useId();
  return <div className="space-y-1.5"><label htmlFor={id} className="block text-xs text-muted-foreground">{label}</label>
    <div className="flex items-center gap-1"><Input id={id} {...props} className="min-w-0" onChange={(event) => onChange(event.target.value)} autoComplete="off" spellCheck={false} />{action}</div>
  </div>;
}
