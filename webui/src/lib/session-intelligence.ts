import { displayTitle } from "@/lib/chat-groups";
import type { ChatSummary, SidebarDensity } from "@/lib/types";
import { normalizeWorkspacePath, projectNameFromPath, sameWorkspacePath } from "@/lib/workspace";

export type SessionAttentionState = "recovery" | "running" | "updated" | "idle";
export type CleanupReason = "stale" | "quick_chat";

export const STALE_CLEANUP_DAYS = 7;
export const QUICK_CHAT_IDLE_HOURS = 24;
export const QUICK_CHAT_SPAN_MINUTES = 5;

const STALE_THRESHOLD_MS = STALE_CLEANUP_DAYS * 24 * 60 * 60 * 1000;
const QUICK_CHAT_IDLE_MS = QUICK_CHAT_IDLE_HOURS * 60 * 60 * 1000;
const QUICK_CHAT_SPAN_MS = QUICK_CHAT_SPAN_MINUTES * 60 * 1000;

export const GENERAL_PROJECT_ID = "workspace:general";

/** Curated, distinct low-glare project identity dots (avoiding green/amber/orange status hues). */
const PROJECT_DOT_PALETTE = [
  "#64748b", // slate (general fallback)
  "#6366f1", // indigo
  "#0284c7", // ocean blue
  "#9333ea", // royal violet
  "#0d9488", // deep teal
  "#db2777", // berry rose
  "#4f46e5", // cobalt
  "#7c3aed", // amethyst
] as const;

export interface ProjectIdentity {
  id: string;
  key: string | null;
  name: string;
  path: string | null;
  isGeneral: boolean;
  dotColor: string;
}

export interface EnrichedSession {
  session: ChatSummary;
  title: string;
  preview: string;
  project: ProjectIdentity;
  attention: SessionAttentionState;
  pinned: boolean;
  archived: boolean;
  automationCount: number;
  updatedMs: number;
  createdMs: number;
  cleanupReason: CleanupReason | null;
  workbenchTabKey: string | null;
  workbenchTabTitle: string | null;
}

export interface ProjectWorkspaceGroup {
  project: ProjectIdentity;
  openSessions: EnrichedSession[];
  archivedSessions: EnrichedSession[];
  cleanupCandidates: EnrichedSession[];
  runningCount: number;
  recoveryCount: number;
  updatedCount: number;
  latestUpdatedMs: number;
}

export interface DecoupledWorkbenchGroup {
  tabKey: string;
  title: string;
  activePaneKey: string;
  panes: EnrichedSession[];
  runningCount: number;
  recoveryCount: number;
  updatedCount: number;
  latestUpdatedMs: number;
}

export interface SessionIntelligenceOptions {
  pinnedKeys: readonly string[];
  archivedKeys: readonly string[];
  runningChatIds: readonly string[];
  updatedChatIds: readonly string[];
  recoveryChatIds: readonly string[];
  titleOverrides: Record<string, string>;
  projectNameOverrides: Record<string, string>;
  automationCountsByKey: ReadonlyMap<string, number>;
  paneGroups: Readonly<Record<string, {
    tabKey: string;
    title: string;
    activePaneKey: string;
    visible?: boolean;
    panes: ReadonlyArray<{ key: string }>;
  }>>;
  activeKey: string | null;
  defaultWorkspacePath?: string | null;
  generalLabel: string;
  fallbackTitle: string;
  nowMs?: number;
  density?: SidebarDensity;
}

export interface SessionIntelligenceSnapshot {
  all: EnrichedSession[];
  open: EnrichedSession[];
  archived: EnrichedSession[];
  attention: EnrichedSession[];
  recovery: EnrichedSession[];
  running: EnrichedSession[];
  updated: EnrichedSession[];
  projects: ProjectWorkspaceGroup[];
  cleanupCandidates: EnrichedSession[];
  workbenchGroups: DecoupledWorkbenchGroup[];
  byKey: Map<string, EnrichedSession>;
}

function hashString(input: string): number {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function projectDotColor(key: string | null): string {
  if (!key) return PROJECT_DOT_PALETTE[0];
  return PROJECT_DOT_PALETTE[hashString(key) % PROJECT_DOT_PALETTE.length];
}

export function resolveProjectIdentity(
  session: Pick<ChatSummary, "workspaceScope">,
  projectNameOverrides: Record<string, string>,
  defaultWorkspacePath: string | null | undefined,
  generalLabel: string,
): ProjectIdentity {
  const scope = session.workspaceScope;
  const rawPath = scope?.project_path?.trim() || "";
  if (!rawPath || sameWorkspacePath(rawPath, defaultWorkspacePath)) {
    return {
      id: GENERAL_PROJECT_ID,
      key: null,
      name: generalLabel,
      path: defaultWorkspacePath ?? null,
      isGeneral: true,
      dotColor: PROJECT_DOT_PALETTE[0],
    };
  }
  const normalized = normalizeWorkspacePath(rawPath);
  const name = projectNameOverrides[normalized]?.trim()
    || scope?.project_name?.trim()
    || projectNameFromPath(rawPath);
  return {
    id: `project:${normalized}`,
    key: normalized,
    name,
    path: rawPath,
    isGeneral: false,
    dotColor: projectDotColor(normalized),
  };
}

function parseTimestampMs(value: string | null | undefined): number {
  if (!value) return 0;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : 0;
}

export function classifyCleanupReason(params: {
  archived: boolean;
  pinned: boolean;
  attention: SessionAttentionState;
  automationCount: number;
  projectLocked?: boolean;
  createdMs: number;
  updatedMs: number;
  nowMs: number;
}): CleanupReason | null {
  const {
    archived,
    pinned,
    attention,
    automationCount,
    projectLocked,
    createdMs,
    updatedMs,
    nowMs,
  } = params;
  if (
    archived
    || pinned
    || attention !== "idle"
    || automationCount > 0
    || projectLocked === false
  ) {
    return null;
  }
  const referenceMs = updatedMs || createdMs;
  if (!referenceMs) return null;
  const idleMs = nowMs - referenceMs;
  if (idleMs >= STALE_THRESHOLD_MS) return "stale";
  if (
    createdMs > 0
    && updatedMs > 0
    && Math.abs(updatedMs - createdMs) <= QUICK_CHAT_SPAN_MS
    && idleMs >= QUICK_CHAT_IDLE_MS
  ) {
    return "quick_chat";
  }
  return null;
}

const ATTENTION_PRIORITY: Record<SessionAttentionState, number> = {
  recovery: 0,
  running: 1,
  updated: 2,
  idle: 3,
};

export function compareByAttentionAndRecency(a: EnrichedSession, b: EnrichedSession): number {
  const attentionDelta = ATTENTION_PRIORITY[a.attention] - ATTENTION_PRIORITY[b.attention];
  if (attentionDelta !== 0) return attentionDelta;
  const pinDelta = Number(b.pinned) - Number(a.pinned);
  if (pinDelta !== 0) return pinDelta;
  return b.updatedMs - a.updatedMs;
}

export function buildSessionIntelligence(
  sessions: readonly ChatSummary[],
  options: SessionIntelligenceOptions,
): SessionIntelligenceSnapshot {
  const nowMs = options.nowMs ?? Date.now();
  const pinnedSet = new Set(options.pinnedKeys);
  const archivedSet = new Set(options.archivedKeys);
  const runningSet = new Set(options.runningChatIds);
  const updatedSet = new Set(options.updatedChatIds);
  const recoverySet = new Set(options.recoveryChatIds);

  // Build pane -> workbench tab lookup without swallowing sessions from their native projects.
  const workbenchMembership = new Map<string, { tabKey: string; title: string }>();
  const visibleTabEntries: Array<{
    tabKey: string;
    title: string;
    activePaneKey: string;
    paneKeys: string[];
  }> = [];
  const seenTabs = new Set<string>();
  for (const group of Object.values(options.paneGroups)) {
    const visible = group.visible ?? group.panes.length > 1;
    if (!visible || seenTabs.has(group.tabKey)) continue;
    seenTabs.add(group.tabKey);
    const paneKeys = group.panes.map((pane) => pane.key);
    visibleTabEntries.push({
      tabKey: group.tabKey,
      title: group.title,
      activePaneKey: group.activePaneKey,
      paneKeys,
    });
    for (const paneKey of paneKeys) {
      workbenchMembership.set(paneKey, { tabKey: group.tabKey, title: group.title });
    }
  }

  const all: EnrichedSession[] = [];
  const byKey = new Map<string, EnrichedSession>();

  for (const session of sessions) {
    const pinned = pinnedSet.has(session.key);
    const archived = archivedSet.has(session.key);
    const isActive = session.key === options.activeKey;
    const attention: SessionAttentionState = recoverySet.has(session.chatId)
      ? "recovery"
      : runningSet.has(session.chatId)
        ? "running"
        : updatedSet.has(session.chatId) && !isActive
          ? "updated"
          : "idle";
    const updatedMs = parseTimestampMs(session.updatedAt ?? session.createdAt);
    const createdMs = parseTimestampMs(session.createdAt ?? session.updatedAt);
    const automationCount = options.automationCountsByKey.get(session.key) ?? 0;
    const cleanupReason = classifyCleanupReason({
      archived,
      pinned,
      attention,
      automationCount,
      projectLocked: session.projectLocked,
      createdMs,
      updatedMs,
      nowMs,
    });
    const project = resolveProjectIdentity(
      session,
      options.projectNameOverrides,
      options.defaultWorkspacePath,
      options.generalLabel,
    );
    const wb = workbenchMembership.get(session.key);
    const enriched: EnrichedSession = {
      session,
      title: displayTitle(session, options.titleOverrides, options.fallbackTitle),
      preview: session.preview?.trim() ?? "",
      project,
      attention,
      pinned,
      archived,
      automationCount,
      updatedMs,
      createdMs,
      cleanupReason,
      workbenchTabKey: wb?.tabKey ?? null,
      workbenchTabTitle: wb?.title ?? null,
    };
    all.push(enriched);
    byKey.set(session.key, enriched);
  }

  const open = all.filter((item) => !item.archived).sort(compareByAttentionAndRecency);
  const archived = all
    .filter((item) => item.archived)
    .sort((a, b) => b.updatedMs - a.updatedMs);

  const recovery = open.filter((item) => item.attention === "recovery");
  const running = open.filter((item) => item.attention === "running");
  const updated = open.filter((item) => item.attention === "updated");
  const attention = [...recovery, ...running, ...updated];
  const cleanupCandidates = open
    .filter((item) => item.cleanupReason !== null)
    .sort((a, b) => a.updatedMs - b.updatedMs);

  const projectMap = new Map<string, ProjectWorkspaceGroup>();
  for (const item of all) {
    let group = projectMap.get(item.project.id);
    if (!group) {
      group = {
        project: item.project,
        openSessions: [],
        archivedSessions: [],
        cleanupCandidates: [],
        runningCount: 0,
        recoveryCount: 0,
        updatedCount: 0,
        latestUpdatedMs: 0,
      };
      projectMap.set(item.project.id, group);
    }
    if (item.archived) {
      group.archivedSessions.push(item);
    } else {
      group.openSessions.push(item);
      if (item.attention === "running") group.runningCount += 1;
      if (item.attention === "recovery") group.recoveryCount += 1;
      if (item.attention === "updated") group.updatedCount += 1;
      if (item.cleanupReason !== null) group.cleanupCandidates.push(item);
      if (item.updatedMs > group.latestUpdatedMs) {
        group.latestUpdatedMs = item.updatedMs;
      }
    }
  }

  const projects = Array.from(projectMap.values())
    .map((group) => ({
      ...group,
      openSessions: group.openSessions.sort(compareByAttentionAndRecency),
      archivedSessions: group.archivedSessions.sort((a, b) => b.updatedMs - a.updatedMs),
      cleanupCandidates: group.cleanupCandidates.sort((a, b) => a.updatedMs - b.updatedMs),
    }))
    .sort((a, b) => {
      // Keep explicit projects ahead of the catch-all general bucket unless general has urgent activity.
      const aUrgent = a.recoveryCount * 100 + a.runningCount * 10 + a.updatedCount;
      const bUrgent = b.recoveryCount * 100 + b.runningCount * 10 + b.updatedCount;
      if (aUrgent !== bUrgent) return bUrgent - aUrgent;
      if (a.project.isGeneral !== b.project.isGeneral) {
        return a.project.isGeneral ? 1 : -1;
      }
      if (a.latestUpdatedMs !== b.latestUpdatedMs) {
        return b.latestUpdatedMs - a.latestUpdatedMs;
      }
      return a.project.name.localeCompare(b.project.name, undefined, {
        numeric: true,
        sensitivity: "base",
      });
    });

  const workbenchGroups: DecoupledWorkbenchGroup[] = visibleTabEntries
    .map((entry) => {
      const panes = entry.paneKeys
        .map((key) => byKey.get(key))
        .filter((item): item is EnrichedSession => item !== undefined);
      return {
        tabKey: entry.tabKey,
        title: entry.title,
        activePaneKey: entry.activePaneKey,
        panes,
        runningCount: panes.filter((pane) => pane.attention === "running").length,
        recoveryCount: panes.filter((pane) => pane.attention === "recovery").length,
        updatedCount: panes.filter((pane) => pane.attention === "updated").length,
        latestUpdatedMs: panes.reduce((max, pane) => Math.max(max, pane.updatedMs), 0),
      };
    })
    .filter((group) => group.panes.length > 0 && group.panes.some((pane) => !pane.archived))
    .sort((a, b) => {
      const aScore = a.recoveryCount * 100 + a.runningCount * 10 + a.updatedCount;
      const bScore = b.recoveryCount * 100 + b.runningCount * 10 + b.updatedCount;
      if (aScore !== bScore) return bScore - aScore;
      return b.latestUpdatedMs - a.latestUpdatedMs;
    });

  return {
    all,
    open,
    archived,
    attention,
    recovery,
    running,
    updated,
    projects,
    cleanupCandidates,
    workbenchGroups,
    byKey,
  };
}

export function formatElapsedDuration(startedAtSec: number | null | undefined, nowMs = Date.now()): string {
  if (typeof startedAtSec !== "number" || !Number.isFinite(startedAtSec)) return "";
  const totalSeconds = Math.max(0, Math.floor((nowMs - startedAtSec * 1000) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

export function formatCompactRelativeTime(
  updatedMs: number,
  locale: string | undefined,
  nowMs = Date.now(),
): string {
  if (!updatedMs) return "";
  const isZh = Boolean(locale?.toLowerCase().startsWith("zh"));
  const deltaSec = Math.max(0, Math.floor((nowMs - updatedMs) / 1000));
  if (deltaSec < 60) return isZh ? "刚刚" : "now";
  const mins = Math.floor(deltaSec / 60);
  if (mins < 60) return isZh ? `${mins}分钟前` : `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return isZh ? `${hours}小时前` : `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return isZh ? `${days}天前` : `${days}d`;
  const months = Math.floor(days / 30);
  if (months < 12) return isZh ? `${months}个月前` : `${months}mo`;
  const years = Math.floor(days / 365);
  return isZh ? `${years}年前` : `${years}y`;
}
