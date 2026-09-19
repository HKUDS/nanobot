import { useEffect, useState } from "react";
import { ArrowUpCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { fetchNanobotUpdate, updateNanobot, type NanobotUpdateStatus } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

export function NanobotUpdate({ onInstalled }: { onInstalled?: () => void }) {
  const { t } = useTranslation();
  const { client, token } = useClient();
  const [status, setStatus] = useState<NanobotUpdateStatus | null>(null);
  const [dev, setDev] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const running = submitting || status?.state === "running";

  useEffect(() => {
    if (status?.state === "succeeded") onInstalled?.();
  }, [status?.state, onInstalled]);

  useEffect(() => {
    let active = true;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      try {
        const next = await fetchNanobotUpdate(token);
        if (active) {
          setStatus(next);
          if (next.state !== "idle") setDev(next.mode === "dev");
          setError("");
          if (next.state === "running") timeout = setTimeout(() => void refresh(), 1500);
        }
      } catch (err) {
        if (active) {
          setError((err as Error).message);
          timeout = setTimeout(() => void refresh(), 3000);
        }
      }
    };
    void refresh();
    return () => { active = false; clearTimeout(timeout); };
  }, [token, revision]);

  const install = async () => {
    setSubmitting(true);
    setError("");
    try {
      setStatus(await updateNanobot(client, dev));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
      setRevision((value) => value + 1);
    }
  };

  return (
    <section className="rounded-panel bg-settings-surface p-5">
      <h2 className="text-[14px] font-medium">{t("settings.about.updateTitle", { defaultValue: "Update nanobot" })}</h2>
      <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
        {t("settings.about.updateDescription", { defaultValue: "Install the latest stable release. Restart nanobot after installation." })}
      </p>
      <details className="mt-4 text-[13px]">
        <summary className="cursor-pointer rounded-sm text-muted-foreground focus-visible:outline focus-visible:outline-2">
          {t("settings.about.updateAdvanced", { defaultValue: "Advanced options" })}
        </summary>
        <label className="mt-3 flex cursor-pointer items-start gap-2">
          <input type="checkbox" className="mt-1 accent-primary" checked={dev} disabled={running}
            onChange={(event) => setDev(event.target.checked)} aria-describedby="nanobot-update-dev-help" />
          <span>{t("settings.about.updateDev", { defaultValue: "Install from source" })}</span>
        </label>
        <p id="nanobot-update-dev-help" className="mt-1 pl-5 text-[12px] leading-5 text-muted-foreground">
          {t("settings.about.updateDevDescription", { defaultValue: "Use the development version. Requires Git; Bun is downloaded automatically when needed. Existing source checkouts keep their current branch." })}
        </p>
      </details>
      <Button className="mt-4" size="sm" onClick={() => void install()}
        disabled={!status?.can_update || running || status.state === "succeeded"}>
        {running ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" aria-hidden /> : <ArrowUpCircle className="mr-1.5 h-4 w-4" aria-hidden />}
        {t(dev ? "settings.about.updateDevAction" : "settings.about.updateAction", {
          defaultValue: dev ? "Install development version" : "Install latest release",
        })}
      </Button>
      <div role="status" className="mt-3 text-[12px] leading-5 text-muted-foreground">
        {status?.state === "succeeded"
          ? t("settings.about.updateSuccess", { defaultValue: "Installed v{{version}}. Restart nanobot to apply the update.", version: status.version })
          : status?.state === "running" ? status.message : null}
        {status && !status.can_update ? t("settings.about.updateLocalOnly", {
          defaultValue: "Open WebUI on the server's localhost, or enable remote package installation to update here.",
        }) : null}
      </div>
      {error || status?.state === "failed" ? (
        <p role="alert" className="mt-2 whitespace-pre-wrap break-words text-[12px] leading-5 text-destructive">
          {error || status?.message}
        </p>
      ) : null}
    </section>
  );
}
