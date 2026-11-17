import { ExternalLink, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import type { McpPresetInfo } from "@/lib/types";

export function AgentPluginDialog({
  plugin,
  open,
  actionKey,
  onOpenChange,
  onAction,
}: {
  plugin: McpPresetInfo;
  open: boolean;
  actionKey: string | null;
  onOpenChange: (open: boolean) => void;
  onAction: (action: "enable" | "disable", name: string) => void;
}) {
  const { t } = useTranslation();
  const enabled = Boolean(plugin.enabled);
  const action = enabled ? "disable" : "enable";
  const busy = actionKey === `${action}:${plugin.name}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <div className="space-y-1 pr-8">
          <DialogTitle>{plugin.display_name}</DialogTitle>
          <DialogDescription>{plugin.description}</DialogDescription>
        </div>
        <div className="space-y-4 text-sm">
          <p className="font-medium">{t(enabled ? "settings.values.enabled" : "settings.values.disabled")}</p>
          {plugin.requires ? (
            <div>
              <p className="font-medium">{t("settings.apps.pluginPermissions")}</p>
              <p className="mt-1 text-muted-foreground">{plugin.requires}</p>
            </div>
          ) : null}
          {plugin.connection_summary ? (
            <div>
              <p className="font-medium">{t("settings.apps.pluginServers")}</p>
              <p className="mt-1 break-words text-muted-foreground">{plugin.connection_summary}</p>
            </div>
          ) : null}
          <p className="text-muted-foreground">{t("settings.apps.pluginTrustNotice")}</p>
          {plugin.docs_url ? (
            <a href={plugin.docs_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-medium text-foreground/75 hover:text-foreground">
              {t("settings.mcp.openDocs")} <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          ) : null}
        </div>
        <div className="flex justify-end">
          <Button type="button" disabled={busy} onClick={() => { onOpenChange(false); onAction(action, plugin.name); }}>
            {busy ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
            {t(enabled ? "settings.nanobotFeatures.disable" : "settings.nanobotFeatures.enable")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
