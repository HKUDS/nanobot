import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Check, ChevronDown, Folder, Hand } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  floatingItemClassName,
  floatingItemFocusClassName,
} from "@/components/ui/floating-surface";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type {
  WorkspaceAccessMode,
  WorkspaceScopePayload,
  WorkspacesPayload,
} from "@/lib/types";
import { getRuntimeHost } from "@/lib/runtime";
import { cn } from "@/lib/utils";
import {
  isAbsoluteWorkspacePath,
  projectNameFromPath,
  scopeWithAccessMode,
  selectedProjectScope,
  shortWorkspacePath,
} from "@/lib/workspace";

function workspacePathPlaceholder(defaultWorkspacePath: string, macPlaceholder: string): string {
  const normalized = defaultWorkspacePath.trim().replace(/\\/g, "/");
  const windowsDrive = normalized.match(/^([A-Za-z]):\//)?.[1];
  if (windowsDrive) return `${windowsDrive.toUpperCase()}:\\path\\to\\project`;
  if (normalized.startsWith("/Users/")) return macPlaceholder;
  return "/home/name/project";
}

export function WorkspaceProjectPicker({
  isHero,
  compact = false,
  connected = false,
  disabled,
  scope,
  defaultScope,
  controls,
  error,
  onPickFolder,
  onChange,
}: {
  isHero: boolean;
  compact?: boolean;
  connected?: boolean;
  disabled?: boolean;
  scope: WorkspaceScopePayload | null;
  defaultScope: WorkspaceScopePayload | null;
  controls: WorkspacesPayload["controls"] | null;
  error?: string | null;
  onPickFolder?: () => Promise<string | null>;
  onChange?: (scope: WorkspaceScopePayload) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [pathDraft, setPathDraft] = useState("");
  const [pathError, setPathError] = useState<string | null>(null);
  const [pickingFolder, setPickingFolder] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const pathInputRef = useRef<HTMLInputElement>(null);
  const pathErrorId = useId();
  const currentProjectScope = selectedProjectScope(scope, defaultScope);
  const projectLabel = currentProjectScope
    ? currentProjectScope.project_name || projectNameFromPath(currentProjectScope.project_path)
    : t("thread.composer.workspace.projectPlaceholder");
  const visible = isHero
    && !!defaultScope
    && !!onChange
    && controls?.can_change_project !== false;
  const pickFolder = getRuntimeHost().pickFolder ?? onPickFolder;
  const nativeProjectPicker = !!pickFolder;

  useEffect(() => {
    if (!open) return;
    setPathDraft(currentProjectScope?.project_path ?? "");
    setPathError(null);
  }, [currentProjectScope?.project_path, open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (!error || !visible || disabled) return;
    const frame = window.requestAnimationFrame(() => triggerRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [disabled, error, visible]);

  useEffect(() => {
    if (!open || !error) return;
    const frame = window.requestAnimationFrame(() => pathInputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [error, open]);

  const applyProjectPath = useCallback(
    (projectPath: string, projectName?: string) => {
      const base = scope ?? defaultScope;
      const trimmed = projectPath.trim();
      if (!base || !onChange) return;
      if (!trimmed || !isAbsoluteWorkspacePath(trimmed)) {
        setPathError(t("workspace.dialog.absolutePathRequired"));
        return;
      }
      onChange({
        ...base,
        project_path: trimmed,
        project_name: projectName || projectNameFromPath(trimmed),
        restrict_to_workspace: base.access_mode === "restricted",
      });
      setPathError(null);
      setOpen(false);
    },
    [defaultScope, onChange, scope, t],
  );

  const pickNativeFolder = useCallback(async () => {
    if (!pickFolder || disabled) return;
    setPickingFolder(true);
    try {
      const picked = await pickFolder();
      if (picked) applyProjectPath(picked);
    } catch (err) {
      setPathError((err as Error).message);
    } finally {
      setPickingFolder(false);
    }
  }, [applyProjectPath, disabled, pickFolder]);

  if (!visible || !defaultScope || !onChange) return null;

  if (nativeProjectPicker) {
    return (
      <div className={cn(
        compact
          ? "inline-flex"
          : "flex min-w-0 items-center rounded-b-[28px] bg-muted/45 px-3 py-1.5 dark:bg-white/[0.045] sm:px-4",
      )}>
        <button
          ref={triggerRef}
          type="button"
          disabled={disabled || pickingFolder}
          aria-label={t("thread.composer.workspace.projectAria")}
          title={currentProjectScope?.project_path}
          onClick={() => void pickNativeFolder()}
          className={cn(
            compact
              ? "thread-composer-action touch-target inline-flex h-8 w-8 items-center justify-center rounded-full border border-transparent"
              : "inline-flex h-7 max-w-full items-center gap-2 rounded-full px-2.5 sm:max-w-[18rem]",
            "text-[12px] font-medium text-muted-foreground/90 transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-55",
            compact ? "hover:bg-muted/65" : "hover:bg-background/70",
            (connected || currentProjectScope) && "text-primary",
          )}
        >
          <Folder className={cn("shrink-0", compact ? "h-4 w-4" : "h-3.5 w-3.5")} />
          <span className={compact ? "sr-only" : "truncate"}>{projectLabel}</span>
        </button>
        {!compact && (pathError || error) ? (
          <span role="alert" className="ml-2 min-w-0 truncate text-[11.5px] font-medium text-destructive">
            {pathError ?? error}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div className={cn(
      compact
        ? "inline-flex"
        : "flex min-w-0 items-center rounded-b-[28px] bg-muted/45 px-3 py-1.5 dark:bg-white/[0.045] sm:px-4",
    )}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            ref={triggerRef}
            type="button"
            disabled={disabled}
            aria-label={t("thread.composer.workspace.projectAria")}
            className={cn(
              compact
                ? "thread-composer-action touch-target inline-flex h-8 w-8 items-center justify-center rounded-full border border-transparent"
                : "inline-flex h-7 max-w-full items-center gap-2 rounded-full px-2.5 sm:max-w-[18rem]",
              "text-[12px] font-medium text-muted-foreground/90 transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-55",
              compact ? "hover:bg-muted/65" : "hover:bg-background/70",
              (connected || currentProjectScope) && "text-primary",
            )}
          >
            <Folder className={cn("shrink-0", compact ? "h-4 w-4" : "h-3.5 w-3.5")} />
            <span className={compact ? "sr-only" : "truncate"}>{projectLabel}</span>
            {!compact ? (
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            ) : null}
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          side="bottom"
          sideOffset={8}
          className="w-[min(25rem,calc(100vw-2rem))]"
        >
          <button
            type="button"
            onClick={() => applyProjectPath(defaultScope.project_path, defaultScope.project_name)}
            className={cn(
              floatingItemClassName,
              floatingItemFocusClassName,
              "flex min-h-[48px] w-full cursor-default gap-3 px-3 py-2.5 focus:bg-muted/55",
            )}
          >
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-control bg-muted text-foreground/80">
              <Folder className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold text-foreground">
                {t("workspace.dialog.defaultProject")}
              </span>
              <span className="block truncate text-[11.5px] text-muted-foreground">
                {shortWorkspacePath(defaultScope.project_path)}
              </span>
            </span>
            {!currentProjectScope ? <Check className="h-4 w-4 text-foreground/80" /> : null}
          </button>
          <div className="my-1 h-px bg-border/45" />
          <div className="space-y-1.5 px-1.5 py-1.5">
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                applyProjectPath(pathDraft);
              }}
            >
              <Input
                ref={pathInputRef}
                value={pathDraft}
                disabled={disabled}
                onChange={(event) => {
                  setPathDraft(event.target.value);
                  setPathError(null);
                }}
                placeholder={workspacePathPlaceholder(
                  defaultScope.project_path,
                  t("workspace.dialog.manualPlaceholder"),
                )}
                aria-label={t("workspace.dialog.manual")}
                aria-invalid={pathError || error ? true : undefined}
                aria-describedby={pathError || error ? pathErrorId : undefined}
                className="h-9 rounded-full border-border/55 bg-background/80 px-3 text-[12.5px]"
              />
              <Button
                type="submit"
                disabled={disabled || !pathDraft.trim()}
                className="h-9 shrink-0 rounded-full px-3 text-[12px]"
              >
                {t("workspace.dialog.usePath")}
              </Button>
            </form>
            {pathError || error ? (
              <p
                id={pathErrorId}
                role="alert"
                className="px-1 text-[11.5px] font-medium text-destructive"
              >
                {pathError ?? error}
              </p>
            ) : null}
          </div>
        </PopoverContent>
      </Popover>
      {!compact && error && !open ? (
        <span role="alert" className="ml-2 min-w-0 truncate text-[11.5px] font-medium text-destructive">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export function WorkspaceAccessMenu({
  scope,
  disabled,
  canUseFullAccess,
  isHero,
  onChange,
}: {
  scope: WorkspaceScopePayload;
  disabled?: boolean;
  canUseFullAccess: boolean;
  isHero: boolean;
  onChange?: (scope: WorkspaceScopePayload) => void;
}) {
  const { t } = useTranslation();
  const mode = scope.access_mode;
  const isFull = mode === "full";
  const accessLabel = t(
    isFull ? "thread.composer.workspace.full" : "thread.composer.workspace.default",
  );
  const shortAccessLabel = t(
    isFull ? "thread.composer.workspace.fullShort" : "thread.composer.workspace.defaultShort",
  );
  const accessAriaLabel = `${t("thread.composer.workspace.accessAria")}: ${accessLabel}`;

  const setMode = (value: WorkspaceAccessMode) => {
    if (value === "full" && !canUseFullAccess) return;
    if (value === mode) return;
    onChange?.(scopeWithAccessMode(scope, value));
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled || !onChange}>
        <Button
          type="button"
          variant="ghost"
          aria-label={accessAriaLabel}
          title={accessLabel}
          className={cn(
            "thread-composer-access touch-target min-w-0 max-w-[min(12.5rem,42vw)] whitespace-nowrap rounded-control border border-transparent font-semibold shadow-none",
            isHero ? "h-8 px-2.5 text-[12px]" : "h-9 px-3 text-[12.5px]",
            isFull
              ? "bg-transparent text-orange-600 hover:bg-orange-500/8 dark:text-orange-300 dark:hover:bg-orange-400/10"
              : "bg-transparent text-muted-foreground hover:bg-foreground/[0.045] hover:text-foreground dark:hover:bg-white/[0.06]",
          )}
        >
          {isFull ? (
            <AlertTriangle className={cn("thread-composer-access-icon mr-1.5 shrink-0", isHero ? "h-3.5 w-3.5" : "h-3.5 w-3.5")} />
          ) : (
            <Hand className={cn("thread-composer-access-icon mr-1.5 shrink-0", isHero ? "h-3.5 w-3.5" : "h-3.5 w-3.5")} />
          )}
          <span aria-hidden className="thread-composer-access-label-full min-w-0 truncate">
            {accessLabel}
          </span>
          <span aria-hidden className="thread-composer-access-label-short hidden min-w-0 truncate">
            {shortAccessLabel}
          </span>
          <ChevronDown className={cn("thread-composer-access-chevron ml-1.5 shrink-0", isHero ? "h-3 w-3" : "h-3 w-3")} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <AccessMenuItem
          icon={<Hand className="h-4 w-4" />}
          label={t("thread.composer.workspace.default")}
          selected={mode === "restricted"}
          onSelect={() => setMode("restricted")}
        />
        <AccessMenuItem
          icon={<AlertTriangle className="h-4 w-4" />}
          label={t("thread.composer.workspace.full")}
          selected={mode === "full"}
          disabled={!canUseFullAccess}
          warning
          onSelect={() => setMode("full")}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function AccessMenuItem({
  icon,
  label,
  selected,
  disabled,
  warning,
  onSelect,
}: {
  icon: ReactNode;
  label: string;
  selected: boolean;
  disabled?: boolean;
  warning?: boolean;
  onSelect: () => void;
}) {
  return (
    <DropdownMenuItem
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        "flex h-10 items-center gap-3 px-3 text-[13.5px] font-semibold",
        warning && "text-orange-600 focus:text-orange-600 dark:text-orange-300 dark:focus:text-orange-300",
      )}
    >
      <span className="grid h-5 w-5 shrink-0 place-items-center text-current" aria-hidden>
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {selected ? <Check className="h-4 w-4 shrink-0" aria-hidden /> : null}
    </DropdownMenuItem>
  );
}
