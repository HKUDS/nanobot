import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { SettingsGroup, SettingsRow } from "@/components/settings/shared/SettingsControls";

export function SettingsAdvancedOptions({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <details className="group/advanced">
      <summary className="settings-list-inset flex min-h-12 cursor-pointer list-none items-center justify-between gap-4 rounded-xl text-[13px] leading-5 text-muted-foreground hover:bg-sidebar-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        {t("settings.runtimeConfig.advancedOptions")}
        <ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0 group-open/advanced:rotate-180" />
      </summary>
      <div className="space-y-1">{children}</div>
    </details>
  );
}

export function SettingsFeature({
  title, enabled, onChange, disabled, initialOpen = false, error, children,
}: {
  title: string;
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
  initialOpen?: boolean;
  error?: string;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(initialOpen);
  const id = useId();
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    if (initialOpen) {
      setOpen(true);
      section.current?.scrollIntoView?.({ block: "nearest" });
    }
  }, [initialOpen]);
  const expanded = Boolean(children) && enabled && open;
  return (
    <section ref={section} aria-label={title}>
      <SettingsGroup>
        <SettingsRow title={children && enabled ? (
          <button type="button" aria-expanded={expanded} aria-controls={id}
            className="flex min-h-9 w-full items-center gap-2 rounded-lg text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => setOpen((value) => !value)}>
            {title}
            <ChevronDown aria-hidden className={`h-3.5 w-3.5 shrink-0 text-muted-foreground ${expanded ? "rotate-180" : ""}`} />
          </button>
        ) : title}>
          <ToggleButton checked={enabled} disabled={disabled} ariaLabel={title} label={title}
            onChange={(next) => { setOpen(next); onChange(next); }} />
        </SettingsRow>
        {children ? <div id={id} hidden={!expanded}>{children}</div> : null}
      </SettingsGroup>
      {error && !expanded ? <p role="alert" className="settings-list-inset pt-2 text-[13px] leading-5 text-destructive">{error}</p> : null}
    </section>
  );
}
