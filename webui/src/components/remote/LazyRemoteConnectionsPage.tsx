import { lazy, Suspense, type ComponentProps } from "react";
import { useTranslation } from "react-i18next";
import { StartupShell } from "@/components/StartupShell";
import { SurfaceErrorBoundary } from "@/components/SurfaceErrorBoundary";
import { Button } from "@/components/ui/button";

const RemoteConnectionsPage = lazy(async () => {
  const module = await import("./RemoteConnectionsPage");
  return { default: module.RemoteConnectionsPage };
});

export function LazyRemoteConnectionsPage(props: ComponentProps<typeof RemoteConnectionsPage>) {
  const { t } = useTranslation();
  return <SurfaceErrorBoundary fallback={
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 bg-background p-6 text-center">
      <p role="alert" className="max-w-sm text-sm text-destructive">{t("app.loading.failed")}</p>
      <Button variant="ghost" onClick={props.onBackToChat}>{t("remote.back")}</Button>
    </div>
  }>
    <Suspense fallback={
      <div className="relative min-h-0 flex-1">
        <StartupShell embedded surface="remote" sidebarExpanded={props.mainNavigationExpanded ?? false} />
        <Button variant="ghost" className={`touch-target absolute left-4 z-10 ${props.hostChromeInset ? "top-20" : "top-4"}`}
          onClick={props.onBackToChat}>{t("remote.back")}</Button>
      </div>
    }>
      <RemoteConnectionsPage {...props} />
    </Suspense>
  </SurfaceErrorBoundary>;
}
