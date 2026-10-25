import { useTranslation } from "react-i18next";

import { readStartupLayout, StartupSkeleton, type StartupSurface } from "./StartupSkeleton";

export function StartupShell({ embedded = false, surface, sidebarExpanded }: {
  embedded?: boolean;
  surface?: StartupSurface;
  sidebarExpanded?: boolean;
}) {
  const { t } = useTranslation();
  const layout = readStartupLayout();
  return <StartupSkeleton {...layout} embedded={embedded} surface={surface ?? layout.surface}
    sidebarExpanded={sidebarExpanded ?? layout.sidebarExpanded} label={t("app.loading.boot")} />;
}
