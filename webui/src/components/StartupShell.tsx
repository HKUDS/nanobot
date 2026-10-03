import { useTranslation } from "react-i18next";

/** Quiet layout placeholders while the authenticated application starts. */
export function StartupShell({ embedded = false }: { embedded?: boolean }) {
  const { t } = useTranslation();
  const Root = embedded ? "section" : "main";
  return (
    <Root className="startup-shell" aria-busy="true">
      <div className="startup-header" aria-hidden="true">
        <span className="startup-control-shadow" />
        <span className="startup-control-shadow" />
      </div>
      <div className="startup-composer" aria-hidden="true" />
      <span className="startup-status" role="status">{t("app.loading.connecting")}</span>
    </Root>
  );
}
