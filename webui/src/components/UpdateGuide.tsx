import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Disclosure } from "@/components/ui/disclosure";
import { fetchSettings, type UpdateGuide as Guide } from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";

function Command({ command, label, collapsed = false }: { command: string; label: string; collapsed?: boolean }) {
  const { t } = useTranslation();
  const [copy, setCopy] = useState<"idle" | "pending" | "copied" | "failed">("idle");
  const content = <div className="space-y-1.5">
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs font-medium">{label}</span>
      <Button size="sm" variant="ghost" disabled={copy === "pending"} aria-busy={copy === "pending"} className="h-7 px-2 text-xs" onClick={async () => {
        setCopy("pending");
        setCopy(await copyTextToClipboard(command) ? "copied" : "failed");
      }}>{t(copy === "copied" ? "remote.pair.copied" : "remote.pair.copy")}</Button>
    </div>
    <Textarea aria-label={label} readOnly value={command} rows={Math.min(5, command.split("\n").length + 1)}
      onFocus={event => event.currentTarget.select()} className="resize-none font-mono text-xs leading-5" />
    <p role="status" className="text-xs text-muted-foreground">{copy === "failed" ? t("remote.pair.copyFailed") : copy === "copied" ? t("remote.pair.copied") : ""}</p>
  </div>;
  return collapsed ? <Disclosure summaryClassName="flex min-h-9 items-center gap-2 rounded-control text-xs text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    summary={<><ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0 transition-transform group-data-[state=open]/disclosure:rotate-180 motion-reduce:transition-none" />{label}</>}>
    {content}
  </Disclosure> : content;
}

/** Display and copy only. The package manager/deployment remains the owner. */
export function UpdateGuide({ guide, token, targetVersion }: { guide: Guide; token: string; targetVersion: string }) {
  const { t } = useTranslation();
  const active = useRef(true);
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState("");
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const check = async () => {
    if (checking) return;
    setChecking(true);
    setResult("");
    const feedback = new Promise(resolve => setTimeout(resolve, 600));
    try {
      const settings = await fetchSettings(token).finally(() => feedback);
      const version = settings.version?.current;
      if (!version) throw new Error("No running version");
      if (active.current) setResult(t(version === targetVersion ? "updates.guide.verified" : "updates.guide.observed", { version, target: targetVersion }));
    } catch {
      if (active.current) setResult(t("updates.guide.checkFailed"));
    } finally { if (active.current) setChecking(false); }
  };
  return <div className="mt-4 space-y-4 text-sm leading-6">
    <div className="rounded-control bg-muted/50 p-3">
      <p className="break-words font-medium">{t("updates.guide.host", { host: guide.host })}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{t(guide.method === "container" ? "updates.guide.containerHost" : "updates.guide.where")}</p>
      <p className="mt-2 break-all font-mono text-xs text-muted-foreground">{guide.environment}</p>
    </div>
    <ol className="list-decimal space-y-4 ps-5 marker:text-muted-foreground">
      <li className="ps-1"><p className="font-medium">{t("updates.guide.beforeTitle")}</p>
        <p className="text-muted-foreground">{t("updates.guide.before")}</p></li>
      <li className="space-y-2 ps-1"><p className="font-medium">{t("updates.guide.installTitle", { shell: guide.shell === "powershell" ? "PowerShell" : "sh / bash / zsh" })}</p>
        <p className="text-muted-foreground">{t(`updates.guide.reasons.${guide.reason}`)}</p>
        {guide.inspect_command && <Command command={guide.inspect_command} label={t("updates.guide.inspectCommand")} collapsed />}
        {guide.update_command && <Command command={guide.update_command} label={t("updates.guide.updateCommand")} />}
      </li>
      <li className="space-y-2 ps-1"><p className="font-medium">{t("updates.guide.verifyTitle")}</p>
        <p className="text-muted-foreground">{t("updates.guide.verify", { version: targetVersion })}</p>
        {guide.verify_command && <Command command={guide.verify_command} label={t("updates.guide.versionCommand")} collapsed />}
        <Button size="sm" variant="outline" aria-disabled={checking} aria-busy={checking}
          className={checking ? "opacity-50" : undefined} onClick={() => void check()}>
          {t(checking ? "settings.about.checking" : "updates.guide.check")}
        </Button>
        <p role="status" className="text-xs text-muted-foreground">{result}</p>
      </li>
    </ol>
  </div>;
}
