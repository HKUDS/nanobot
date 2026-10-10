import { FullAccessIcon, WorkspaceIcon, RestrictedAccessIcon } from "@/components/icons/product-icons";
import type { HTMLAttributes, ReactElement } from "react";
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, ChevronRight, FolderSearch, History, Search, Star } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { floatingItemClassName, floatingItemFocusClassName } from "@/components/ui/floating-surface";
import { HoverHint } from "@/components/ui/tooltip";
import { Input, SearchInput } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTrigger, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { SidebarSelectionHighlight, SIDEBAR_SELECTION_ITEM_CLASS } from "@/components/SidebarSelectionHighlight";
import type { WorkspaceScopePayload, ProjectDirectory, WorkspaceDirectoriesPayload, WorkspacesPayload } from "@/lib/types";
import { createWorkspaceDirectoryCache } from "@/lib/workspace-directory-cache";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";
import { isAbsoluteWorkspacePath, projectNameFromPath, sameWorkspacePath, scopeWithAccessMode, workspaceBreadcrumbs, workspacePathCompletionQuery, workspaceDirectoryPrefix, selectedProjectScope, type BrowseWorkspaceDirectories } from "@/lib/workspace";

function WorkspaceFavoriteButton({ path, pinned, busy, onToggle }: {
  path: string; pinned: boolean; busy: boolean; onToggle: () => void;
}) {
  const { t } = useTranslation();
  const label = t(pinned ? "workspace.picker.unpin" : "workspace.picker.pin", { name: projectNameFromPath(path) });
  return (
    <HoverHint content={label}>
      <button type="button" aria-label={label} aria-pressed={pinned} disabled={busy}
        onMouseDown={event => event.preventDefault()} onClick={onToggle}
        className="workspace-picker-favorite touch-target absolute right-1 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-control text-muted-foreground outline-none hover:bg-foreground/[0.055] hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none">
        <Star className={cn("h-3.5 w-3.5", pinned && "fill-current text-foreground")} />
      </button>
    </HoverHint>
  );
}

type PickerOption = ProjectDirectory & { kind: "directory" | "manual" };
type PickerColumn = { path: string; parent: string | null; options: PickerOption[]; selectedPath: string | null; hidden: boolean };
type PickerAncestor = Pick<PickerColumn, "path" | "parent" | "selectedPath">;
type PickerVisit = { path: string; ancestors: PickerAncestor[]; filter: string; scrollLeft: number | null; scrollTops: number[] };
type PickerHistory = { visits: PickerVisit[]; index: number; previous: PickerVisit | null; revision: number };

function directoryVisit(path: string, ancestors: PickerAncestor[] = [], scrollTops: number[] = []): PickerVisit {
  return { path, ancestors: ancestors.map(({ path, parent, selectedPath }) => ({ path, parent, selectedPath })), filter: "", scrollLeft: null, scrollTops };
}

function PickerToolButton({ label, disabled, onClick, children }: {
  label: string; disabled?: boolean; onClick: () => void; children: ReactElement;
}) {
  return <HoverHint content={label}>
    <Button type="button" variant="ghost" size="icon" aria-label={label} disabled={disabled} onClick={onClick}
      className="h-11 w-11 shrink-0 rounded-control text-muted-foreground sm:h-9 sm:w-9">{children}</Button>
  </HoverHint>;
}

const DIRECTORY_ROW_HEIGHT = 44;
const DIRECTORY_OVERSCAN = 4;

function WorkspaceDirectoryColumn({ options, activeIndex, selectedPath, initialScrollTop, visitRevision, renderOption, children, style, className, ...props }: {
  options: PickerOption[];
  activeIndex: number | null;
  selectedPath: string | null;
  initialScrollTop: number;
  visitRevision: number;
  renderOption: (option: PickerOption, index: number) => ReactElement;
} & HTMLAttributes<HTMLDivElement>) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [firstRow, setFirstRow] = useState(0);
  const [visibleRows, setVisibleRows] = useState(1);
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    // Measure the available slot so rounding the viewport cannot feed back into
    // its own measurement. Whole rows fit at both edges when scrolling settles.
    const slot = viewport.parentElement!;
    const measure = () => setVisibleRows(Math.floor(slot.clientHeight / DIRECTORY_ROW_HEIGHT));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(slot);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollTop = initialScrollTop;
    setFirstRow(Math.floor(viewport.scrollTop / DIRECTORY_ROW_HEIGHT));
  }, [options, initialScrollTop, visitRevision]);
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || activeIndex === null) return;
    const top = activeIndex * DIRECTORY_ROW_HEIGHT;
    const bottom = top + DIRECTORY_ROW_HEIGHT;
    if (top < viewport.scrollTop) viewport.scrollTop = top;
    else if (bottom > viewport.scrollTop + viewport.clientHeight) viewport.scrollTop = Math.max(0, bottom - viewport.clientHeight);
    setFirstRow(Math.floor(viewport.scrollTop / DIRECTORY_ROW_HEIGHT));
  }, [activeIndex, visibleRows, options]);
  const start = Math.max(0, firstRow - DIRECTORY_OVERSCAN);
  const end = Math.min(options.length, firstRow + visibleRows + DIRECTORY_OVERSCAN);
  // Proximity snapping allows jumps to rows before their virtual DOM mounts.
  return (
    <div className="flex h-full min-h-0 min-w-0 shrink-0 flex-col justify-center" style={style}>
    <div {...props} ref={viewportRef} className={cn("snap-y snap-proximity", className)} style={{ height: options.length ? visibleRows * DIRECTORY_ROW_HEIGHT : "100%" }} onScroll={event => setFirstRow(Math.floor(event.currentTarget.scrollTop / DIRECTORY_ROW_HEIGHT))}>
      <SidebarSelectionHighlight role="presentation" className="relative" style={{ height: options.length * DIRECTORY_ROW_HEIGHT }}
        scope="workspace-directory" activeId={activeIndex === null ? selectedPath : options[activeIndex]?.path ?? null}
        targetSelector={activeIndex === null ? '[aria-selected="true"]' : '[data-keyboard-active]'}>
        {options.slice(start, end).map((option, offset) => {
          const index = start + offset;
          return <div key={`${option.kind}-${option.path}`} role="presentation" className="absolute inset-x-0 snap-start" style={{ top: index * DIRECTORY_ROW_HEIGHT }}>
            {renderOption(option, index)}
          </div>;
        })}
      </SidebarSelectionHighlight>
      {children}
    </div>
    </div>
  );
}

function WorkspaceDirectorySkeleton() {
  const { t } = useTranslation();
  const viewportRef = useRef<HTMLDivElement>(null);
  const [rows, setRows] = useState(1);
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const measure = () => setRows(Math.max(1, Math.ceil(viewport.clientHeight / DIRECTORY_ROW_HEIGHT)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);
  const widths = ["64%", "78%", "52%", "70%", "60%", "74%"];
  return (
    <div ref={viewportRef} role="status" aria-label={t("workspace.picker.loading")} className="workspace-directory-loading h-full">
      <span className="sr-only">{t("workspace.picker.loading")}</span>
      <div aria-hidden="true">
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="flex h-11 items-center px-3 py-2">
            <span className="h-3.5 rounded-control bg-foreground/[0.055]" style={{ width: widths[index % widths.length] }} />
          </div>
        ))}
      </div>
    </div>
  );
}

function WorkspacePickerPath({ path }: { path: string }) {
  const parts = workspacePathCompletionQuery(path);
  return (
    <span className="flex min-w-0 flex-1 text-[13px]">
      <span className="min-w-0 truncate">{parts?.path ?? path}</span>
      {parts?.query && <span className="max-w-[65%] shrink-0 truncate">{parts.query}</span>}
    </span>
  );
}

export function WorkspaceProjectPicker({ isHero, disabled, scope, defaultScope, controls, error, onLoadProjects, onResolveProject, onFavoriteProject, onBrowseDirectories, layoutAnchor, onChange }: {
  layoutAnchor?: HTMLElement | null;
  isHero: boolean;
  disabled?: boolean;
  scope: WorkspaceScopePayload | null;
  defaultScope: WorkspaceScopePayload | null;
  controls: WorkspacesPayload["controls"] | null;
  error?: string | null;
  onResolveProject?: (path: string) => Promise<ProjectDirectory>;
  onLoadProjects?: () => Promise<WorkspacesPayload>;
  onFavoriteProject?: (path: string, pinned: boolean) => Promise<ProjectDirectory[]>;
  onBrowseDirectories?: BrowseWorkspaceDirectories;
  onChange?: (scope: WorkspaceScopePayload) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [pathDraft, setPathDraft] = useState("");
  const [editingPath, setEditingPath] = useState(false);
  const [showLocations, setShowLocations] = useState(false);
  const [hoveredLocation, setHoveredLocation] = useState<string | null>(null);
  const [history, setHistory] = useState<PickerHistory>(() => ({
    visits: [directoryVisit(scope?.project_path ?? defaultScope?.project_path ?? "")], index: 0, previous: null, revision: 0,
  }));
  const currentVisit = history.visits[history.index];
  const basePath = currentVisit.path;
  const filterQuery = currentVisit.filter;
  const compact = useMediaQuery("(max-width: 639px)");
  const [catalog, setCatalog] = useState<WorkspacesPayload | null>(null);
  const [directory, setDirectory] = useState<WorkspaceDirectoriesPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const [ancestorData, setAncestorData] = useState<{ hidden: boolean; listings: WorkspaceDirectoriesPayload[] }>({ hidden: false, listings: [] });
  const [revision, setRevision] = useState(0);
  const [directoryError, setDirectoryError] = useState<string | null>(null);
  const [pathError, setPathError] = useState<string | null>(null);
  const [pickingFolder, setPickingFolder] = useState(false);
  const [favoriteBusy, setFavoriteBusy] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [activeColumn, setActiveColumn] = useState(0);
  const [highlightActive, setHighlightActive] = useState(false);
  const columnsRef = useRef<HTMLDivElement | null>(null);
  const breadcrumbRef = useRef<HTMLElement | null>(null);
  const attachBreadcrumb = useCallback((element: HTMLElement | null) => {
    breadcrumbRef.current = element;
    // Dialog portals mount after the parent's layout effect on first open.
    if (element) window.requestAnimationFrame(() => { if (element.isConnected) element.scrollLeft = element.scrollWidth; });
  }, []);
  const [columnsElement, setColumnsElement] = useState<HTMLDivElement | null>(null);
  const attachColumns = useCallback((element: HTMLDivElement | null) => {
    columnsRef.current = element;
    setColumnsElement(element);
  }, []);
  const [visibleColumns, setVisibleColumns] = useState(3);
  const pickerSession = useRef(0);
  const completionRequest = useRef(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [keyboardInteraction, setKeyboardInteraction] = useState(false);
  const openedWithKeyboard = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const optionsId = useId();
  const errorId = useId();
  const currentProjectScope = selectedProjectScope(scope, defaultScope);
  const displayedScope = scope ?? defaultScope;
  const projectLabel = displayedScope ? displayedScope.project_name || projectNameFromPath(displayedScope.project_path) : "";
  const visible = isHero && !!defaultScope && !!onChange && controls?.can_change_project !== false;
  const canBrowse = controls?.can_browse_directories === true && !!onBrowseDirectories;
  const directoryCache = useMemo(() => onBrowseDirectories ? createWorkspaceDirectoryCache(onBrowseDirectories) : null, [onBrowseDirectories]);
  const previousColumns = useMemo<PickerColumn[]>(() => currentVisit.ancestors.map(ancestor => {
    const listing = directoryCache?.peek(ancestor.path, "", showHidden, true)
      ?? (ancestorData.hidden === showHidden ? ancestorData.listings.find(listing => sameWorkspacePath(listing.path, ancestor.path)) : undefined);
    return { ...ancestor, hidden: showHidden, options: listing?.entries.map(entry => ({ ...entry, kind: "directory" as const })) ?? [] };
  }), [currentVisit.ancestors, directoryCache, showHidden, ancestorData]);
  const absoluteDraft = isAbsoluteWorkspacePath(pathDraft);
  const requestedPath = editingPath && absoluteDraft ? pathDraft.trim() : basePath;
  const previewingPath = editingPath && !sameWorkspacePath(pathDraft.trim(), basePath);
  const displayedAncestors = previewingPath ? [] : previousColumns;
  const currentColumnIndex = displayedAncestors.length;
  const columnCount = Math.min(visibleColumns, currentColumnIndex + 1);
  const folderQuery = editingPath ? "" : filterQuery.trim();

  useEffect(() => {
    pickerSession.current += 1;
    completionRequest.current += 1;
    if (!open) return;
    setActiveColumn(0);
    setHighlightActive(false);
    const initialPath = scope?.project_path ?? defaultScope?.project_path ?? "";
    setPathDraft(canBrowse ? workspaceDirectoryPrefix(initialPath) : currentProjectScope?.project_path ?? "");
    setHistory(current => ({ visits: [directoryVisit(initialPath)], index: 0, previous: null, revision: current.revision + 1 }));
    setEditingPath(false);
    setShowLocations(false);
    setHoveredLocation(null);
    setDirectory(null);
    setActiveIndex(0);
    setPathError(null);
  }, [scope?.project_path, defaultScope?.project_path, open, canBrowse]);

  useEffect(() => {
    if (!open || !onLoadProjects) return;
    let active = true;
    setCatalog(null);
    onLoadProjects().then(payload => { if (active) setCatalog(payload); }).catch((err: Error) => { if (active) setPathError(err.message); });
    return () => { active = false; };
  }, [onLoadProjects, open]);

  useEffect(() => {
    if (!open || !canBrowse || !directoryCache) return;
    if (editingPath && !absoluteDraft) { setDirectory(null); setLoading(false); return; }
    let active = true;
    const apply = (result: WorkspaceDirectoriesPayload) => {
      if (!active) return;
      setDirectory(result); setLoading(false);
    };
    setDirectoryError(null);
    const cached = directoryCache.peek(requestedPath, folderQuery, showHidden, true);
    if (cached) { apply(cached); return; }
    setLoading(true);
    setDirectory(null);
    const typing = !!folderQuery || editingPath && !/[\\/]$/.test(pathDraft);
    const timer = window.setTimeout(() => {
      directoryCache.load(requestedPath, folderQuery, showHidden, true).then(apply).catch((err: Error) => {
        if (active) { setDirectoryError(err.message); setLoading(false); }
      });
    }, typing ? 150 : 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [open, canBrowse, directoryCache, requestedPath, folderQuery, showHidden, revision, absoluteDraft, pathDraft, editingPath]);

  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  useEffect(() => {
    if (!error || !visible || disabled) return;
    const frame = window.requestAnimationFrame(() => triggerRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [disabled, error, visible]);
  useEffect(() => {
    if (!open || pickingFolder) return;
    const frame = window.requestAnimationFrame(() => {
      if (editingPath || !canBrowse) inputRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, pickingFolder, pathError, editingPath, canBrowse]);

  const ancestorPaths = JSON.stringify(currentVisit.ancestors.map(column => column.path));
  useEffect(() => {
    if (!open || !canBrowse || !directoryCache) return;
    const paths: string[] = JSON.parse(ancestorPaths);
    if (!paths.length) {
      setAncestorData(current => current.listings.length ? { hidden: showHidden, listings: [] } : current);
      return;
    }
    let active = true;
    Promise.all(paths.map(path => directoryCache.load(path, "", showHidden, true))).then(results => {
      if (!active) return;
      setAncestorData({ hidden: showHidden, listings: results });
    }).catch((err: Error) => { if (active) setPathError(err.message); });
    return () => { active = false; };
  }, [open, canBrowse, directoryCache, ancestorPaths, showHidden]);

  useLayoutEffect(() => {
    const viewport = columnsElement;
    if (!open || !viewport) return;
    const measure = () => setVisibleColumns(Math.max(1, Math.min(3, Math.floor(viewport.clientWidth / 240))));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [open, columnsElement]);

  useEffect(() => {
    const viewport = columnsElement;
    if (!open || !viewport) return;
    const onWheel = (event: WheelEvent) => {
      setKeyboardInteraction(false);
      if (!event.shiftKey || event.ctrlKey || event.metaKey || viewport.scrollWidth <= viewport.clientWidth) return;
      const delta = event.deltaX || event.deltaY;
      if (!delta) return;
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientWidth : 1;
      viewport.scrollLeft = Math.max(0, Math.min(viewport.scrollWidth - viewport.clientWidth, viewport.scrollLeft + delta * unit));
    };
    viewport.addEventListener("wheel", onWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", onWheel);
  }, [open, columnsElement]);

  useLayoutEffect(() => {
    const viewport = columnsRef.current;
    if (!viewport) return;
    viewport.scrollLeft = !previewingPath && currentVisit.scrollLeft !== null
      ? currentVisit.scrollLeft
      : viewport.clientWidth * Math.max(0, currentColumnIndex + 1 - columnCount) / columnCount;
  }, [history.revision, currentColumnIndex, columnCount, currentVisit.scrollLeft, previewingPath]);

  useLayoutEffect(() => {
    const viewport = columnsRef.current;
    if (!viewport || !highlightActive) return;
    const width = viewport.clientWidth / columnCount;
    const left = activeColumn * width;
    const right = left + width;
    if (left < viewport.scrollLeft) viewport.scrollLeft = left;
    else if (right > viewport.scrollLeft + viewport.clientWidth) viewport.scrollLeft = right - viewport.clientWidth;
  }, [activeColumn, highlightActive, columnCount]);

  function changeDraft(value: string, query = "") {
    setHighlightActive(false);
    setActiveColumn(sameWorkspacePath(value.trim(), basePath) ? previousColumns.length : 0);
    completionRequest.current += 1;
    setPathDraft(value);
    const absolute = isAbsoluteWorkspacePath(value);
    const cached = absolute ? directoryCache?.peek(value.trim(), query, showHidden, true) : null;
    setDirectory(cached ?? null);
    setLoading(canBrowse && absolute && !cached);
    setDirectoryError(null);
    setPathError(null);
    setActiveIndex(0);
  }
  function focusDirectory() {
    window.requestAnimationFrame(() => columnsRef.current?.querySelector<HTMLElement>("[data-current-directory]")?.focus());
  }
  function captureVisit(): PickerVisit {
    // A draft preview is not a committed navigation visit.
    if (previewingPath) return currentVisit;
    const viewport = columnsRef.current;
    const scrollTops = [...currentVisit.scrollTops];
    viewport?.querySelectorAll<HTMLElement>('[data-workspace-column]').forEach(column => {
      scrollTops[Number(column.dataset.workspaceColumn)] = column.scrollTop;
    });
    return { ...currentVisit, scrollLeft: viewport?.scrollLeft ?? null, scrollTops };
  }
  function visitDirectory(visit: PickerVisit, keepEditing = false, historyIndex?: number) {
    const departed = captureVisit();
    setShowLocations(false);
    setEditingPath(keepEditing);
    setHistory(current => {
      const visits = [...current.visits];
      visits[current.index] = departed;
      const previous = sameWorkspacePath(departed.path, visit.path) ? current.previous : departed;
      if (historyIndex !== undefined) return { visits, index: historyIndex, previous, revision: current.revision + 1 };
      if (sameWorkspacePath(departed.path, visit.path)) {
        visits[current.index] = visit;
        return { visits, index: current.index, previous, revision: current.revision + 1 };
      }
      return { visits: [...visits.slice(0, current.index + 1), visit], index: current.index + 1, previous, revision: current.revision + 1 };
    });
    changeDraft(workspaceDirectoryPrefix(visit.path), visit.filter);
    setActiveColumn(visit.ancestors.length);
    setRevision(value => value + 1);
    if (keepEditing) inputRef.current?.focus();
    else focusDirectory();
  }
  function navigate(path: string, columnIndex?: number, keepEditing = false) {
    const source = columnIndex === undefined ? undefined : columns[columnIndex];
    const ancestors = columnIndex === undefined ? [] : columns.slice(0, columnIndex);
    if (source?.options.length && !sameWorkspacePath(source.path, path)) ancestors.push({ ...source, selectedPath: path });
    visitDirectory(directoryVisit(path, ancestors, captureVisit().scrollTops.slice(0, ancestors.length)), keepEditing);
  }
  function setFilterQuery(filter: string) {
    setHistory(current => {
      const visits = [...current.visits];
      const visit = visits[current.index];
      visits[current.index] = { ...visit, filter, scrollTops: visit.scrollTops.slice(0, visit.ancestors.length) };
      return { ...current, visits };
    });
  }

  const applyProjectPath = useCallback((path: string, name?: string) => {
    const base = scope ?? defaultScope;
    const trimmed = path.trim();
    if (!base || !onChange) return;
    if (!trimmed || !isAbsoluteWorkspacePath(trimmed)) { setPathError(t("workspace.dialog.absolutePathRequired")); return; }
    const accessMode = controls?.can_use_full_access === false && !sameWorkspacePath(trimmed, base.project_path) ? "restricted" : base.access_mode;
    onChange({ ...base, project_path: trimmed, project_name: name || projectNameFromPath(trimmed), access_mode: accessMode, restrict_to_workspace: accessMode === "restricted" });
    setPathError(null);
    setOpen(false);
  }, [controls?.can_use_full_access, defaultScope, onChange, scope, t]);

  const chooseProject = useCallback(async (path: string, name?: string) => {
    const session = pickerSession.current;
    if (controls?.can_resolve_project !== true || !onResolveProject) { applyProjectPath(path, name); return; }
    setPickingFolder(true); setPathError(null);
    try {
      const project = await onResolveProject(path);
      if (session === pickerSession.current) applyProjectPath(project.path, project.name);
    } catch (err) {
      if (session === pickerSession.current) setPathError((err as Error).message);
    } finally { setPickingFolder(false); }
  }, [applyProjectPath, controls?.can_resolve_project, onResolveProject]);

  const favorites = catalog?.favorite_projects ?? [];
  const canFavorite = catalog?.controls.can_manage_favorites === true && !!onFavoriteProject;
  const isFavorite = (path: string) => favorites.some(item => sameWorkspacePath(item.path, path));
  function favoriteButton(path: string) {
    return canFavorite ? <WorkspaceFavoriteButton path={path} pinned={isFavorite(path)} busy={favoriteBusy || pickingFolder}
      onToggle={() => { void toggleFavorite(path); inputRef.current?.focus(); }} /> : null;
  }

  const toggleFavorite = async (path: string) => {
    if (!onFavoriteProject || favoriteBusy) return;
    const session = pickerSession.current;
    setFavoriteBusy(true); setPathError(null);
    try {
      const favorites = await onFavoriteProject(path, !isFavorite(path));
      if (session === pickerSession.current) setCatalog(current => current ? { ...current, favorite_projects: favorites } : current);
    } catch (err) {
      if (session === pickerSession.current) setPathError((err as Error).message);
    } finally { setFavoriteBusy(false); }
  };

  const recentProjects = [
    ...(catalog?.recent_projects ?? []),
    ...(defaultScope ? [{ name: projectNameFromPath(defaultScope.project_path), path: defaultScope.project_path }] : []),
    ...(currentProjectScope ? [{ name: projectLabel, path: currentProjectScope.project_path }] : []),
  ].filter((project, index, all) => all.findIndex(item => sameWorkspacePath(item.path, project.path)) === index && !isFavorite(project.path));
  const options = useMemo<PickerOption[]>(() => {
    if (directory && !loading) return directory.entries.map(entry => ({ ...entry, kind: "directory" }));
    return !canBrowse && absoluteDraft ? [{ name: projectNameFromPath(pathDraft.trim()), path: pathDraft.trim(), kind: "manual" }] : [];
  }, [directory, loading, canBrowse, absoluteDraft, pathDraft]);
  function openShortcut(project: ProjectDirectory) {
    if (!canBrowse) { void chooseProject(project.path, project.name); return; }
    navigate(project.path);
  }
  const columns: PickerColumn[] = [...displayedAncestors, { path: directory?.path ?? requestedPath, parent: directory?.parent ?? null, options, selectedPath: null, hidden: showHidden }];
  const activeOptions = columns[activeColumn]?.options ?? options;
  const activeOption = Math.min(activeIndex, Math.max(activeOptions.length - 1, 0));
  const browsedSelectionPath = directoryError || directory?.partial ? null : directory?.path ?? basePath;
  const resolvedDraftPath = !loading && directory && !directory.partial ? directory.path : null;
  const selectionPath = canBrowse
    ? editingPath ? resolvedDraftPath : browsedSelectionPath
    : (pathDraft.trim() ? absoluteDraft ? pathDraft.trim() : null : scope?.project_path ?? defaultScope?.project_path);
  const displayedError = pathError ?? error ?? directoryError;
  const currentPath = editingPath ? basePath : directory?.path ?? basePath;
  let savedSelectionJoin: "top" | "bottom" | null = null;
  for (const projects of [favorites, recentProjects]) {
    const selectedIndex = projects.findIndex(project => sameWorkspacePath(project.path, currentPath));
    if (selectedIndex < 0 || !hoveredLocation) continue;
    if (selectedIndex > 0 && sameWorkspacePath(projects[selectedIndex - 1].path, hoveredLocation)) savedSelectionJoin = "top";
    else if (selectedIndex + 1 < projects.length && sameWorkspacePath(projects[selectedIndex + 1].path, hoveredLocation)) savedSelectionJoin = "bottom";
  }
  const breadcrumbs = workspaceBreadcrumbs(currentPath);
  const hostName = catalog?.host?.name ?? directory?.host;

  useLayoutEffect(() => {
    if (breadcrumbRef.current) breadcrumbRef.current.scrollLeft = breadcrumbRef.current.scrollWidth;
  }, [currentPath, editingPath, open]);

  function editPath() {
    const visit = captureVisit();
    setHistory(current => {
      const visits = [...current.visits];
      visits[current.index] = visit;
      return { ...current, visits };
    });
    setEditingPath(true);
    changeDraft(workspaceDirectoryPrefix(currentPath));
    window.requestAnimationFrame(() => inputRef.current?.select());
  }
  function cancelPathEditing(focusColumns = true) {
    setEditingPath(false);
    changeDraft(workspaceDirectoryPrefix(basePath), filterQuery.trim());
    if (focusColumns) focusDirectory();
  }

  async function completePath(keepEditing = true) {
    if (!absoluteDraft) { setPathError(t("workspace.dialog.absolutePathRequired")); return; }
    const request = workspacePathCompletionQuery(pathDraft) ?? { path: basePath, query: "" };
    if (!directoryCache || !canBrowse) return;
    const id = ++completionRequest.current;
    const session = pickerSession.current;
    try {
      const result = await directoryCache.load(requestedPath, folderQuery, showHidden || request.query.startsWith("."), true);
      if (id !== completionRequest.current || session !== pickerSession.current) return;
      if (!result.partial) { navigate(result.path, undefined, keepEditing); return; }
      const prefix = request.query.toLocaleLowerCase();
      const first = result.entries.find(entry => entry.name.toLocaleLowerCase().startsWith(prefix));
      if (first) navigate(first.path, undefined, keepEditing);
      else setPathError(t("workspace.picker.pathNotFound"));
    } catch (err) {
      if (id === completionRequest.current && session === pickerSession.current) setPathError((err as Error).message);
    }
  }
  function activate(option: PickerOption, columnIndex = activeColumn) {
    if (pickingFolder) return;
    if (canBrowse && option.kind !== "manual") navigate(option.path, columnIndex);
    else void chooseProject(option.path, option.kind === "manual" ? undefined : option.name);
  }

  function moveHistory(offset: number) {
    const index = history.index + offset;
    if (index >= 0 && index < history.visits.length) visitDirectory(history.visits[index], false, index);
  }

  const filterToolbar = canBrowse && !(compact && editingPath) && <div className={cn("flex shrink-0 items-center gap-2", compact ? "bg-[#fcfcfc] px-3 py-2 dark:bg-muted" : "w-56 max-w-[40%]")}>
    {compact && <Button variant="ghost" size="sm" aria-expanded={showLocations} onClick={() => setShowLocations(value => !value)} className="h-11 shrink-0 gap-1.5 rounded-control px-2 text-[13px] leading-5"><Star className="h-3.5 w-3.5" />{t("workspace.picker.shortcuts")}</Button>}
    <div className="relative min-w-0 flex-1">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
      <SearchInput aria-label={t("workspace.picker.filter")} placeholder={t("workspace.picker.filter")} value={filterQuery} disabled={pickingFolder || editingPath || compact && showLocations} onChange={event => { setFilterQuery(event.target.value); setActiveIndex(0); setActiveColumn(currentColumnIndex); setHighlightActive(false); }} className={cn("h-11 rounded-[var(--picker-field-radius)] border-transparent pl-8 text-[16px] leading-5 shadow-none sm:h-9 sm:text-[13px]", compact ? "bg-muted/60" : "bg-background/80")} />
    </div>
  </div>;

  if (!visible || !defaultScope || !onChange) return null;
  return (
    <div className="inline-flex min-w-0 max-w-[11rem] shrink items-center">
      <Dialog open={open} onOpenChange={setOpen}>
        <HoverHint content={`${t("workspace.picker.switchDirectory")}\n${displayedScope?.project_path ?? ""}`}>
          <DialogTrigger asChild>
            <button ref={triggerRef} onClick={event => { openedWithKeyboard.current = event.detail === 0; }} onPointerDown={() => setKeyboardInteraction(false)} onKeyDown={() => setKeyboardInteraction(true)} type="button" disabled={disabled} aria-label={t("workspace.picker.switchDirectory")} className="thread-composer-workspace touch-target inline-flex h-8 min-w-0 max-w-full items-center gap-1.5 rounded-control px-2 text-[12px] font-medium text-muted-foreground outline-none transition-colors hover:bg-foreground/[0.055] hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-55">
              <WorkspaceIcon className="h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 truncate">{projectLabel}</span>
            </button>
          </DialogTrigger>
        </HoverHint>
        <DialogContent showCloseButton={false} layoutAnchor={layoutAnchor} centerInLayoutAnchor className="flex h-[min(37rem,calc(100%-2rem))] max-w-5xl flex-col gap-0 overflow-hidden p-0 text-[13px] leading-5 [--picker-sidebar-width:11rem] [--picker-toolbar-inset:0.75rem] [--picker-field-radius:calc(var(--radius-modal)_-_var(--picker-toolbar-inset))] sm:[--picker-toolbar-inset:1rem] dark:bg-background"
          onOpenAutoFocus={event => { event.preventDefault(); if (canBrowse) focusDirectory(); else inputRef.current?.focus(); }}
          onPointerDownCapture={() => setKeyboardInteraction(false)}
          onKeyDownCapture={event => {
            if (!["Alt", "Control", "Meta", "Shift"].includes(event.key)) setKeyboardInteraction(true);
            if (!canBrowse || pickingFolder || event.nativeEvent.isComposing) return;
            if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "g") { event.preventDefault(); editPath(); }
          }}
          onEscapeKeyDown={event => { if (editingPath) { event.preventDefault(); cancelPathEditing(); } }}
          onCloseAutoFocus={event => { if (!openedWithKeyboard.current) event.preventDefault(); }}>
          <DialogTitle className="sr-only">{t("workspace.picker.title")}</DialogTitle>
          <DialogDescription className="sr-only">{t("workspace.picker.description")}</DialogDescription>
          <div className="flex shrink-0 items-center gap-1 bg-muted px-[var(--picker-toolbar-inset)] pt-[var(--picker-toolbar-inset)] pb-3">
            {canBrowse && <div className={cn("flex shrink-0 items-center", !compact && "w-[calc(var(--picker-sidebar-width)-var(--picker-toolbar-inset)-0.25rem)]")}>
              <PickerToolButton label={t("workspace.picker.back")} disabled={pickingFolder || history.index === 0} onClick={() => moveHistory(-1)}><ArrowLeft className="h-4 w-4" /></PickerToolButton>
              {!compact && <PickerToolButton label={t("workspace.picker.forward")} disabled={pickingFolder || history.index >= history.visits.length - 1} onClick={() => moveHistory(1)}><ArrowRight className="h-4 w-4" /></PickerToolButton>}
              <PickerToolButton label={t("workspace.picker.history")} disabled={pickingFolder || !history.previous}
                onClick={() => history.previous && visitDirectory(history.previous)}><History className="h-4 w-4" /></PickerToolButton>
            </div>}
            <div className="flex min-w-0 flex-1 items-center rounded-[var(--picker-field-radius)] bg-background/80">
            {editingPath || !canBrowse ? <Input ref={inputRef} role="combobox" aria-expanded={open} aria-controls={`${optionsId}-${activeColumn}`} aria-activedescendant={highlightActive && activeOptions.length ? `${optionsId}-${activeColumn}-${activeOption}` : undefined} aria-autocomplete="list" aria-busy={loading} value={pathDraft} disabled={disabled || pickingFolder} onChange={event => changeDraft(event.target.value)} onBlur={event => { if (canBrowse && !keyboardInteraction && event.relatedTarget !== confirmRef.current) cancelPathEditing(false); }} placeholder={t("workspace.dialog.manual")} aria-label={t("workspace.dialog.manual")} aria-invalid={displayedError ? true : undefined} aria-describedby={displayedError ? errorId : undefined} className="h-9 min-w-0 flex-1 rounded-[var(--picker-field-radius)] border-transparent shadow-none focus-visible:ring-0 text-[16px] leading-5 sm:text-[13px]" onKeyDown={event => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Tab" && !event.shiftKey && canBrowse && absoluteDraft && !/[\\/]$/.test(pathDraft)) {
                event.preventDefault(); void completePath();
              } else if (event.key === "Enter") {
                event.preventDefault();
                if (!canBrowse) void chooseProject(pathDraft);
                else if ((event.ctrlKey || event.metaKey) && selectionPath) void chooseProject(selectionPath);
                else void completePath(false);
              }
            }} /> : <nav ref={attachBreadcrumb} aria-label={t("workspace.picker.location")}
              onClick={event => { if (!pickingFolder && !(event.target as HTMLElement).closest("button")) editPath(); }}
              className="flex h-11 min-w-0 flex-1 cursor-text items-center overflow-x-auto rounded-[var(--picker-field-radius)] sm:h-9 [scrollbar-width:none]">
              {breadcrumbs.map((crumb, index) => <span key={crumb.path} className="flex shrink-0 items-center">
                {index > 0 && <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/60" />}
                  <button type="button" disabled={pickingFolder} aria-current={index === breadcrumbs.length - 1 ? "location" : undefined} onClick={() => navigate(crumb.path)}
                    className="h-11 max-w-48 cursor-pointer truncate rounded-[var(--picker-field-radius)] px-2 text-muted-foreground outline-none hover:bg-foreground/[0.055] focus-visible:ring-2 focus-visible:ring-ring aria-[current=location]:font-medium aria-[current=location]:text-foreground sm:h-9">{crumb.name}</button>
              </span>)}
              <HoverHint content={t("workspace.picker.editPath")}>
                <button type="button" disabled={pickingFolder} aria-label={`${t("workspace.picker.editPath")}: ${currentPath}`} onClick={editPath}
                  className="min-w-8 flex-1 cursor-text self-stretch rounded-[var(--picker-field-radius)] outline-none focus-visible:ring-2 focus-visible:ring-ring" />
              </HoverHint>
            </nav>}
            </div>
            {!compact && filterToolbar}
          </div>
          {compact && filterToolbar}
          <div className="flex min-h-0 flex-1 bg-muted">
            {(!compact || showLocations || !canBrowse) && <nav aria-label={t("workspace.picker.shortcuts")}
              className={cn("sidebar-scrollbar flex shrink-0 flex-col overflow-auto bg-muted p-2", compact && canBrowse ? "w-full" : "w-[var(--picker-sidebar-width)]", compact && !canBrowse && "w-40")}>
              {hostName && <p className="shrink-0 truncate px-3 py-2 text-xs leading-4 text-muted-foreground">{hostName}</p>}
              <SidebarSelectionHighlight scope="workspace-saved-location" activeId={currentPath} targetSelector='button[aria-current="location"]' className="relative flex shrink-0 flex-col gap-3"
                highlightClassName={savedSelectionJoin === "top" ? "rounded-t-none" : savedSelectionJoin === "bottom" ? "rounded-b-none" : undefined}>
              {[{ label: t("workspace.picker.favorites"), projects: favorites, favorite: true }, { label: t("workspace.picker.recent"), projects: recentProjects, favorite: false }].map(section => (
                <section key={section.label} className="min-w-0 shrink-0">
                  <h3 className="px-3 py-2 text-xs font-medium leading-4 text-muted-foreground">{section.label}</h3>
                  {section.projects.map(project => <div key={project.path} className={cn("workspace-picker-row group/workspace-saved-row", SIDEBAR_SELECTION_ITEM_CLASS)}
                    onPointerEnter={() => setHoveredLocation(project.path)} onPointerLeave={() => setHoveredLocation(null)}>
                      <button type="button" aria-label={project.path} aria-current={sameWorkspacePath(currentPath, project.path) ? "location" : undefined}
                        disabled={pickingFolder} onMouseDown={event => event.preventDefault()} onClick={() => openShortcut(project)}
                        className={cn(floatingItemClassName, "flex h-11 min-h-11 w-full min-w-0 items-center gap-2 px-3 py-2 text-left group-hover/workspace-saved-row:bg-foreground/[0.055] dark:group-hover/workspace-saved-row:bg-white/[0.08] focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring", canFavorite && "pr-12",
                          sameWorkspacePath(currentPath, project.path) && "font-medium text-foreground group-hover/workspace-saved-row:bg-transparent dark:group-hover/workspace-saved-row:bg-transparent",
                          sameWorkspacePath(hoveredLocation, project.path) && (savedSelectionJoin === "top" ? "rounded-b-none" : savedSelectionJoin === "bottom" ? "rounded-t-none" : undefined))}>
                        <span className="min-w-0 flex-1 truncate">{projectNameFromPath(project.path)}</span>
                      </button>
                    {favoriteButton(project.path)}
                  </div>)}
                  {section.favorite && !favorites.length && canFavorite && <p className="px-3 text-xs leading-5 text-muted-foreground">{t("workspace.picker.favoriteHint")}</p>}
                </section>
              ))}
              </SidebarSelectionHighlight>
            </nav>}
            <div className={cn("mr-[var(--picker-toolbar-inset)] flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[var(--picker-field-radius)] bg-[#fcfcfc] dark:bg-muted", compact && showLocations && canBrowse && "hidden")}>
            <div ref={attachColumns} data-workspace-columns className="sidebar-scrollbar flex flex-1 min-h-0 min-w-0 overflow-x-auto overscroll-x-contain">
              {columns.map((column, columnIndex) => (!compact || columnIndex === currentColumnIndex) && <WorkspaceDirectoryColumn key={columnIndex} options={column.options} selectedPath={column.selectedPath} initialScrollTop={previewingPath ? 0 : currentVisit.scrollTops[columnIndex] ?? 0} visitRevision={history.revision} activeIndex={highlightActive && columnIndex === activeColumn ? activeOption : null}
                id={`${optionsId}-${columnIndex}`} data-workspace-column={columnIndex} data-current-directory={columnIndex === currentColumnIndex ? "" : undefined} role="listbox" tabIndex={0} aria-activedescendant={highlightActive && columnIndex === activeColumn && column.options.length ? `${optionsId}-${columnIndex}-${activeOption}` : undefined} aria-label={column.path || t("thread.composer.workspace.projectAria")} aria-busy={columnIndex === currentColumnIndex && loading} style={{ width: `${compact ? 100 : 100 / columnCount}%` }} className="sidebar-scrollbar relative min-w-0 shrink-0 overflow-x-hidden overflow-y-auto px-2 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50"
                onFocus={event => { if (event.target === event.currentTarget) { setActiveColumn(columnIndex); setActiveIndex(0); } }}
                onKeyDown={event => {
                  if (event.target !== event.currentTarget || event.altKey || event.metaKey || event.ctrlKey || pickingFolder) return;
                  const count = column.options.length;
                  if (count && (event.key === "Home" || event.key === "End")) {
                    event.preventDefault(); setHighlightActive(true); setActiveColumn(columnIndex);
                    setActiveIndex(event.key === "Home" ? 0 : count - 1);
                  } else if (count && event.key === "Enter") {
                    event.preventDefault(); activate(column.options[Math.min(activeIndex, count - 1)], columnIndex);
                  }
                }}
                renderOption={(option, index) => <div role="presentation" className={cn("workspace-picker-row", SIDEBAR_SELECTION_ITEM_CLASS)} data-keyboard-active={highlightActive && columnIndex === activeColumn && index === activeOption ? "" : undefined}>
                  <button id={`${optionsId}-${columnIndex}-${index}`} type="button" role="option" tabIndex={-1} aria-label={option.path} aria-selected={sameWorkspacePath(column.selectedPath, option.path)} aria-posinset={index + 1} aria-setsize={column.options.length} disabled={pickingFolder}
                    onPointerMove={() => { setHighlightActive(false); setActiveColumn(columnIndex); setActiveIndex(index); }}
                    onMouseDown={event => event.preventDefault()} onClick={() => activate(option, columnIndex)}
                    className={cn(floatingItemClassName, floatingItemFocusClassName, "flex min-h-11 w-full min-w-0 items-center gap-2 px-3 py-2 text-left hover:bg-foreground/[0.055] dark:hover:bg-white/[0.08] disabled:opacity-50", canFavorite && "pr-12",
                      sameWorkspacePath(column.selectedPath, option.path) && "font-medium text-foreground hover:bg-transparent dark:hover:bg-transparent focus:bg-transparent dark:focus:bg-transparent")}>
                    {option.kind === "directory" ? <span className="min-w-0 flex-1 truncate">{option.name}</span> : <WorkspacePickerPath path={option.path} />}
                    {sameWorkspacePath(option.path, scope?.project_path ?? defaultScope.project_path) && <Check className="h-4 w-4 shrink-0 text-muted-foreground" />}
                  </button>
                  {favoriteButton(option.path)}
              </div>}>
              {columnIndex === currentColumnIndex && loading && <WorkspaceDirectorySkeleton />}
              {columnIndex === currentColumnIndex && canBrowse && !loading && directory && !column.options.length && !displayedError && <div role="status" className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 py-10 text-center text-xs leading-4 text-muted-foreground"><FolderSearch className="h-6 w-6 opacity-50" /><p>{t(folderQuery || directory.partial ? "workspace.picker.noMatches" : "workspace.picker.empty")}</p></div>}
              {columnIndex === currentColumnIndex && directory?.truncated && <p className="px-3 py-2 text-xs leading-4 text-muted-foreground">{t("workspace.picker.truncated")}</p>}
              {columnIndex === currentColumnIndex && displayedError && <div className="px-3 py-3"><p id={errorId} role="alert" className="text-xs leading-5 text-destructive">{displayedError}</p>{directoryError && <Button variant="ghost" size="sm" onClick={() => setRevision(value => value + 1)} className="mt-2 text-[13px] leading-5">{t("workspace.picker.retry")}</Button>}</div>}
              </WorkspaceDirectoryColumn>)}
            </div>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-x-3 gap-y-3 bg-muted px-4 py-3">
            {canBrowse && <label className="mr-auto flex w-full items-center gap-2 text-muted-foreground sm:w-auto"><ToggleButton checked={showHidden} onChange={setShowHidden} label={t("workspace.picker.hidden")} />{t("workspace.picker.hidden")}</label>}
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)} className="h-11 rounded-control px-4 text-[13px] leading-5 sm:h-10">{t("workspace.picker.cancel")}</Button>
            <Button ref={confirmRef} size="sm" className="h-11 rounded-control px-4 text-[13px] leading-5 sm:h-10" disabled={!selectionPath || pickingFolder || (editingPath && !absoluteDraft)} onClick={() => selectionPath && void chooseProject(selectionPath)}>{t("workspace.picker.select")}</Button>
          </div>
        </DialogContent>
      </Dialog>
      {error && !open && <span role="alert" className="ml-2 min-w-0 truncate text-[11.5px] font-medium text-destructive">{error}</span>}
    </div>
  );
}

export function WorkspaceAccessToggle({
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

  return (
    <HoverHint side="top" contentClassName="w-max max-w-[calc(100vw-2rem)] text-left leading-relaxed"
      content={t(isFull ? "thread.composer.workspace.fullDescription" : "thread.composer.workspace.defaultDescription")}>
          <Button
            type="button"
            variant={null}
            aria-label={accessAriaLabel}
            aria-pressed={isFull}
            disabled={disabled || !onChange || (!isFull && !canUseFullAccess)}
            onClick={() => onChange?.(scopeWithAccessMode(scope, isFull ? "restricted" : "full"))}
            className={cn(
              "settings-hover thread-composer-access touch-target min-w-0 max-w-[min(12.5rem,42vw)] whitespace-nowrap rounded-control border border-transparent font-semibold shadow-none",
              isHero ? "h-8 px-2.5 text-[12px]" : "h-9 px-3 text-[12.5px]",
              isFull
                ? "bg-transparent text-orange-600 hover:text-orange-600 dark:text-orange-300 dark:hover:text-orange-300"
                : "bg-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {isFull ? (
              <FullAccessIcon className={cn("thread-composer-access-icon mr-1.5 shrink-0", isHero ? "h-3.5 w-3.5" : "h-3.5 w-3.5")} />
            ) : (
              <RestrictedAccessIcon className={cn("thread-composer-access-icon mr-1.5 shrink-0", isHero ? "h-3.5 w-3.5" : "h-3.5 w-3.5")} />
            )}
            <span aria-hidden className="thread-composer-access-label-full min-w-0 truncate">
              {accessLabel}
            </span>
            <span aria-hidden className="thread-composer-access-label-short hidden min-w-0 truncate">
              {shortAccessLabel}
            </span>
          </Button>
    </HoverHint>
  );
}
