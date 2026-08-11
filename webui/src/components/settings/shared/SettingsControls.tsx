import type { ReactNode } from "react";
import { CircleAlert, Loader2, RotateCcw, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { isNativeRuntime } from "@/lib/runtime";
import type { NanobotFeatureInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export const SETTINGS_SEARCH_INPUT_CLASS = cn(
  "border-border/45 bg-settings-surface transition-colors hover:border-border/70",
  "focus-visible:border-border/70 focus-visible:bg-background",
);

export function CapabilityInstallNotice({
  title,
  description,
  installing = false,
}: {
  title: string;
  description: string;
  installing?: boolean;
}) {
  return (
    <div className="flex items-start gap-3 rounded-[14px] border border-border/55 bg-muted/22 px-3.5 py-3">
      {installing ? (
        <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
      ) : (
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      )}
      <div className="min-w-0">
        <p className="text-[12.5px] font-medium text-foreground">{title}</p>
        <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

export function NanobotFeatureInstallDialog({
  feature,
  installing,
  onOpenChange,
  onConfirm,
}: {
  feature: NanobotFeatureInfo | null;
  installing: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (feature: NanobotFeatureInfo) => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const name = feature?.display_name || feature?.name || "";
  return (
    <Dialog open={Boolean(feature)} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="w-[min(calc(100vw-2rem),24rem)] gap-0 p-5 text-center"
      >
        <DialogHeader className="items-center space-y-0 text-center">
          <DialogTitle className="text-center text-[20px] font-semibold leading-tight tracking-[-0.02em] text-foreground">
            {tx("settings.nanobotFeatures.installConfirmTitle", "Install support for {{name}}?", { name })}
          </DialogTitle>
          <DialogDescription className="mt-3 max-w-[20rem] text-center text-[14px] leading-6 text-muted-foreground">
            {tx(
              "settings.nanobotFeatures.installConfirmDescription",
              "nanobot will add what {{name}} needs, then turn it on. Continue?",
              { name },
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="mt-7 !grid grid-cols-1 gap-3 space-x-0 sm:grid-cols-2 sm:space-x-0">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={installing}
            className="h-11 w-full min-w-0 rounded-full bg-muted/70 px-5 text-[15px] font-semibold text-foreground shadow-none hover:bg-muted"
          >
            {tx("settings.automations.cancel", "Cancel")}
          </Button>
          <Button
            type="button"
            onClick={() => feature && void onConfirm(feature)}
            disabled={!feature || installing}
            className="h-11 w-full min-w-0 !whitespace-normal rounded-full px-5 text-center text-[15px] font-semibold"
          >
            {installing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : null}
            {tx("settings.nanobotFeatures.installConfirmAction", "Install and enable")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DismissibleStatusMessage({
  message,
  isError,
  onDismiss,
}: {
  message: string;
  isError: boolean;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-[12px] border py-2.5 pl-4 pr-2 text-[13px]",
        isError
          ? "border-destructive/20 bg-destructive/5 text-destructive"
          : "border-border/55 bg-muted/35 text-muted-foreground",
      )}
    >
      <span className="min-w-0">{message}</span>
      <button
        type="button"
        aria-label={tx("settings.actions.dismiss", "Dismiss")}
        title={tx("settings.actions.dismiss", "Dismiss")}
        onClick={onDismiss}
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors",
          isError
            ? "text-destructive/70 hover:bg-destructive/10 hover:text-destructive"
            : "text-muted-foreground/70 hover:bg-muted hover:text-foreground",
        )}
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}

export function RestartRequiredNotice({
  message,
  onRestart,
  isRestarting,
}: {
  message: string;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 rounded-[12px] border border-amber-500/20 bg-amber-500/8 px-4 py-3 text-[12.5px] text-amber-800 dark:text-amber-200 sm:flex-row sm:items-center sm:justify-between">
      <span>{message}</span>
      {onRestart ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onRestart}
          disabled={isRestarting}
          className="h-8 rounded-full bg-background/80 px-3 text-[12px] font-semibold"
        >
          {isRestarting ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {isRestarting ? t("app.system.restarting") : t("app.system.restart")}
        </Button>
      ) : null}
    </div>
  );
}

export function SettingsSectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-2 px-1 text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
      {children}
    </h2>
  );
}

export function SettingsGroup({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[22px] bg-settings-surface">
      <div className="divide-y divide-border/45">{children}</div>
    </div>
  );
}

export function SettingsRow({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex min-h-[62px] flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0">
        <div className="text-[14px] font-medium leading-5 text-foreground">{title}</div>
        {description ? (
          <div className="mt-0.5 max-w-[28rem] text-[12px] leading-5 text-muted-foreground">
            {description}
          </div>
        ) : null}
      </div>
      {children ? <div className="min-w-0 sm:ml-6 sm:shrink-0">{children}</div> : null}
    </div>
  );
}

export function ReadOnlyRow({
  title,
  value,
  description,
}: {
  title: string;
  value: string;
  description?: string;
}) {
  return (
    <SettingsRow title={title} description={description}>
      <span className="block max-w-full truncate text-left text-[13px] text-muted-foreground sm:max-w-[320px] sm:text-right">
        {value}
      </span>
    </SettingsRow>
  );
}

export function RestartSettingsFooter({
  dirty,
  saving,
  pendingRestart,
  disabled = false,
  message,
  dirtyMessage,
  pendingMessage,
  onSave,
  onRestart,
  onReset,
  isRestarting,
}: {
  dirty: boolean;
  saving: boolean;
  pendingRestart: boolean;
  disabled?: boolean;
  message?: string;
  dirtyMessage?: string;
  pendingMessage?: string;
  onSave: () => void;
  onRestart?: () => void;
  onReset?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const isNativeHost = isNativeRuntime();
  const restartLabel = isNativeHost
    ? tx("app.system.restartEngine", "Restart engine")
    : t("app.system.restart");
  const restartingLabel = isNativeHost
    ? tx("app.system.restartingEngine", "Restarting engine...")
    : t("app.system.restarting");
  const statusMessage =
    message ??
    (pendingRestart && !dirty
      ? pendingMessage ?? tx("settings.status.savedRestartApply", "Saved. Restart when ready.")
      : dirty
        ? dirtyMessage ?? t("settings.status.unsaved")
        : undefined);
  const statusTone = disabled ? "danger" : dirty || pendingRestart ? "accent" : undefined;

  return (
    <div className="flex min-h-[58px] flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0 text-[13px] leading-5 text-muted-foreground">
        <SettingsStatusMessage tone={statusTone}>{statusMessage}</SettingsStatusMessage>
      </div>
      <div className="flex w-full shrink-0 flex-wrap justify-end gap-2 sm:w-auto">
        {pendingRestart && !dirty && onRestart ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={onRestart}
            disabled={isRestarting}
            className="rounded-full"
          >
            {isRestarting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {isRestarting ? restartingLabel : restartLabel}
          </Button>
        ) : null}
        {onReset ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={onReset}
            disabled={!dirty || saving}
            className="rounded-full"
          >
            {t("settings.actions.cancel")}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          onClick={onSave}
          disabled={!dirty || disabled || saving}
          className="rounded-full"
        >
          {saving ? t("settings.actions.saving") : t("settings.actions.save")}
        </Button>
      </div>
    </div>
  );
}

export function SettingsStatusMessage({
  children,
  tone,
}: {
  children?: ReactNode;
  tone?: "accent" | "danger";
}) {
  if (!children) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2",
        tone === "accent" && "font-medium text-blue-600 dark:text-blue-300",
        tone === "danger" && "font-medium text-destructive",
      )}
    >
      {tone ? (
        <span
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            tone === "accent" &&
              "bg-blue-500 dark:bg-blue-400",
            tone === "danger" && "bg-destructive/70",
          )}
          aria-hidden
        />
      ) : null}
      <span>{children}</span>
    </span>
  );
}

export function StatusPill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning";
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-[260px] items-center rounded-full px-2.5 py-1 text-[12px] font-medium",
        tone === "success" && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
        tone === "warning" && "bg-amber-500/10 text-amber-700 dark:text-amber-300",
        tone === "neutral" && "bg-muted text-muted-foreground",
      )}
    >
      <span className="truncate">{children}</span>
    </span>
  );
}

export function NumberInput({
  value,
  min,
  max,
  onChange,
  suffix,
}: {
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
  suffix?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) => {
          const parsed = Number(event.target.value);
          if (Number.isFinite(parsed)) onChange(parsed);
        }}
        className="h-8 w-24 max-w-full rounded-full text-[13px]"
      />
      {suffix ? <span className="text-[12px] text-muted-foreground">{suffix}</span> : null}
    </div>
  );
}
