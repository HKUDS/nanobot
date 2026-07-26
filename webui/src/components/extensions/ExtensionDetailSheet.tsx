import { useState } from "react";
import { ExternalLink, ShieldCheck, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import type { ExtensionAction } from "@/lib/api";
import type { ExtensionDiagnosticInfo, ExtensionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

import {
  DetailPill,
  DetailSection,
  ExtensionMark,
  MetaItem,
  NamedItems,
  RuntimeBadge,
  StatusBadge,
} from "./extension-ui";

interface ExtensionDetailSheetProps {
  extension: ExtensionInfo | null;
  diagnostics: ExtensionDiagnosticInfo[];
  busy: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAction: (
    action: ExtensionAction,
    values: Record<string, unknown>,
  ) => Promise<void>;
}

export function ExtensionDetailSheet({
  extension,
  diagnostics,
  busy,
  open,
  onOpenChange,
  onAction,
}: ExtensionDetailSheetProps) {
  const { t } = useTranslation();
  const [uninstallOpen, setUninstallOpen] = useState(false);
  if (!extension) return null;

  const configManaged =
    extension.scope !== "builtin" && !extension.managed_by_store;
  const requested = new Set(extension.requested_permissions);
  const granted = new Set(extension.granted_permissions);
  const allGranted = [...requested].every((permission) => granted.has(permission));

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="right"
          className="w-[min(36rem,calc(100vw-1rem))] max-w-none gap-0 overflow-hidden p-0 sm:max-w-none"
        >
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
            <div className="flex items-start gap-3 pr-8">
              <ExtensionMark runtime={extension.runtime} large />
              <div className="min-w-0 flex-1">
                <SheetTitle className="truncate text-[20px] font-semibold">
                  {extension.name}
                </SheetTitle>
                <SheetDescription className="mt-1 line-clamp-2 text-[13px]">
                  {extension.description || extension.id}
                </SheetDescription>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <RuntimeBadge runtime={extension.runtime} />
                  <DetailPill>{extension.version}</DetailPill>
                  <StatusBadge extension={extension} />
                </div>
              </div>
            </div>

            <div className="mt-7 space-y-6">
              <DetailSection title={t("extensions.details.identity")}>
                <dl className="grid grid-cols-2 gap-2">
                  <MetaItem label="ID" value={extension.id} />
                  <MetaItem
                    label={t("extensions.details.source")}
                    value={extension.source}
                  />
                  <MetaItem
                    label={t("extensions.details.scope")}
                    value={extension.scope}
                  />
                  <MetaItem
                    label={t("extensions.details.license")}
                    value={extension.license || "—"}
                  />
                </dl>
                {extension.homepage ? (
                  <a
                    href={extension.homepage}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-flex items-center gap-1 text-[12px] text-link hover:underline"
                  >
                    {t("extensions.details.homepage")}
                    <ExternalLink className="h-3 w-3" aria-hidden />
                  </a>
                ) : null}
              </DetailSection>

              <NamedItems
                title={t("extensions.details.contributions")}
                rows={extension.contributions.map((item) => ({
                  name: item.name,
                  meta: item.kind,
                }))}
              />
              <NamedItems
                title={t("extensions.details.dependencies")}
                rows={extension.dependencies.map((item) => ({
                  name: item.name,
                  meta: `${item.kind}${item.specifier ? ` ${item.specifier}` : ""}`,
                }))}
              />

              <DetailSection title={t("extensions.details.permissions")}>
                {extension.permissions.length ? (
                  <div className="space-y-2">
                    {extension.permissions.map((permission) => (
                      <div
                        key={permission.name}
                        className="flex items-start justify-between gap-3 rounded-[14px] bg-muted/35 px-3 py-2.5"
                      >
                        <div className="min-w-0">
                          <div className="text-[13px] font-medium text-foreground">
                            {permission.name === "runtime.node"
                              ? t("extensions.knownPermissions.runtimeNode.label")
                              : permission.name}
                          </div>
                          {permission.reason ? (
                            <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
                              {permission.name === "runtime.node"
                                ? t("extensions.knownPermissions.runtimeNode.reason")
                                : permission.reason}
                            </p>
                          ) : null}
                        </div>
                        <span
                          className={cn(
                            "shrink-0 text-[11px]",
                            granted.has(permission.name)
                              ? "text-emerald-600 dark:text-emerald-300"
                              : "text-muted-foreground",
                          )}
                        >
                          {granted.has(permission.name)
                            ? t("extensions.permissionGranted")
                            : t("extensions.permissionPending")}
                        </span>
                      </div>
                    ))}
                    {extension.managed_by_store ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy !== null}
                        onClick={() =>
                          void onAction("permissions", {
                            id: extension.id,
                            permissions: allGranted ? [] : [...requested],
                          })
                        }
                        className="rounded-full"
                      >
                        {allGranted
                          ? t("extensions.revokePermissions")
                          : t("extensions.grantPermissions")}
                      </Button>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-[13px] text-muted-foreground">
                    {t("extensions.noPermissions")}
                  </p>
                )}
              </DetailSection>

              {diagnostics.length ? (
                <DetailSection title={t("extensions.details.diagnostics")}>
                  <div className="space-y-2">
                    {diagnostics.map((diagnostic, index) => (
                      <div
                        key={`${diagnostic.code}:${index}`}
                        className="rounded-[14px] bg-amber-500/10 px-3 py-2.5"
                      >
                        <div className="text-[12px] font-medium text-amber-700 dark:text-amber-300">
                          {diagnostic.code}
                        </div>
                        <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
                          {diagnostic.message}
                        </p>
                      </div>
                    ))}
                  </div>
                </DetailSection>
              ) : null}
            </div>
          </div>

          {extension.managed_by_store ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-border/45 bg-background/95 px-5 py-4">
              <Button
                size="sm"
                variant={extension.trusted ? "outline" : "default"}
                disabled={busy !== null || (!extension.trusted && !allGranted)}
                onClick={() =>
                  void onAction(extension.trusted ? "untrust" : "trust", {
                    id: extension.id,
                  })
                }
                className="rounded-full"
              >
                <ShieldCheck className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                {extension.trusted
                  ? t("extensions.revokeTrust")
                  : t("extensions.trust")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null || !extension.trusted}
                onClick={() =>
                  void onAction(extension.enabled ? "disable" : "enable", {
                    id: extension.id,
                  })
                }
                className="rounded-full"
              >
                {extension.enabled
                  ? t("extensions.disable")
                  : t("extensions.enable")}
              </Button>
              <Button
                size="icon"
                variant="ghost"
                disabled={busy !== null}
                aria-label={t("extensions.uninstall")}
                title={t("extensions.uninstall")}
                onClick={() => setUninstallOpen(true)}
                className="ml-auto h-8 w-8 rounded-full text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          ) : configManaged ? (
            <div className="border-t border-border/45 bg-background/95 px-5 py-4 text-[12px] text-muted-foreground">
              {t("extensions.configManaged")}
            </div>
          ) : null}
        </SheetContent>
      </Sheet>

      <AlertDialog open={uninstallOpen} onOpenChange={setUninstallOpen}>
        <AlertDialogContent className="max-w-[26rem] rounded-[18px]">
          <AlertDialogHeader>
            <AlertDialogTitle>{t("extensions.uninstallTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("extensions.uninstallDescription", { name: extension.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("extensions.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void onAction("uninstall", { id: extension.id })}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t("extensions.uninstall")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
