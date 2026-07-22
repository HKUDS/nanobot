import { canonicalToolTrace, formatToolCallTrace } from "@/lib/tool-traces";
import type { ToolProgressEvent } from "@/lib/types";

import { redactActivityText, safeActivityDetail } from "./activity-text";
import { displayWebHost, formatCompactWebUrl, parseSafeActivityHttpUrl } from "./web-url";

export type WebSearchStatus = "running" | "done" | "error";

export interface WebSearchSource {
  title: string;
  href: string;
  host: string;
  displayUrl: string;
}

export interface WebSearchRunModel {
  key: string;
  query: string;
  status: WebSearchStatus;
  sources: WebSearchSource[];
  error?: string;
}

interface WebSearchQueryPresentation {
  query: string;
  scope?: string;
}

const WEB_SEARCH_STATUS_RANK: Record<WebSearchStatus, number> = {
  running: 1,
  done: 2,
  error: 3,
};
const MAX_VISIBLE_SOURCES = 8;

export function webSearchRunsByTraceLine(
  events: ToolProgressEvent[],
): Map<string, WebSearchRunModel> {
  const runs = new Map<string, WebSearchRunModel>();
  for (const event of events) {
    const run = webSearchRunFromEvent(event);
    const line = run ? formatToolCallTrace(event) : null;
    if (!run || !line) continue;
    const key = canonicalToolTrace(line);
    runs.set(key, mergeWebSearchRun(runs.get(key), run));
  }
  return runs;
}

function webSearchRunFromEvent(event: ToolProgressEvent): WebSearchRunModel | null {
  const name = compactToolName(toolEventName(event));
  if (name !== "web_search") return null;

  const args = toolEventArguments(event);
  const query = stringField(args, ["query", "q", "text"]);
  const status: WebSearchStatus = event.phase === "error"
    ? "error"
    : event.phase === "end"
      ? "done"
      : "running";

  return {
    key: event.call_id ? `call:${event.call_id}` : formatToolCallTrace(event) ?? `web_search:${query}`,
    query,
    status,
    sources: status === "done" ? webSearchSources(event.result) : [],
    error: status === "error" ? readableError(event.error) : undefined,
  };
}

function presentWebSearchQuery(query: string): WebSearchQueryPresentation {
  const scopes: string[] = [];
  const safeQuery = redactActivityText(query);
  const cleanQuery = safeQuery
    .replace(/(?:^|\s)site:([^\s]+)/gi, (_match, rawSite: string) => {
      const scope = webSearchScope(rawSite);
      if (scope && !scopes.includes(scope)) scopes.push(scope);
      return " ";
    })
    .replace(/\s+/g, " ")
    .trim();

  return {
    query: cleanQuery || safeQuery.trim(),
    ...(scopes.length === 1 ? { scope: scopes[0] } : {}),
  };
}

export function presentWebSearchAction(
  query: string,
  status: WebSearchStatus,
): string {
  const presentation = presentWebSearchQuery(query);
  const verb = status === "error"
    ? "Could not search"
    : status === "running"
      ? "Searching"
      : "Searched";
  const target = [presentation.scope, presentation.query].filter(Boolean).join(" · ");
  return target ? `${verb} ${target}` : verb;
}

function mergeWebSearchRun(
  existing: WebSearchRunModel | undefined,
  incoming: WebSearchRunModel,
): WebSearchRunModel {
  if (!existing) return incoming;
  if (WEB_SEARCH_STATUS_RANK[incoming.status] < WEB_SEARCH_STATUS_RANK[existing.status]) {
    return existing;
  }
  return {
    ...existing,
    ...incoming,
    query: incoming.query || existing.query,
    sources: incoming.sources.length ? incoming.sources : existing.sources,
  };
}

function webSearchSources(result: unknown): WebSearchSource[] {
  const candidates = structuredCandidates(result);
  if (typeof result === "string") candidates.push(...textCandidates(result));
  if (result && typeof result === "object" && !Array.isArray(result)) {
    const record = result as Record<string, unknown>;
    for (const key of ["content", "text", "result"]) {
      if (typeof record[key] === "string") candidates.push(...textCandidates(record[key]));
    }
  }

  const seen = new Set<string>();
  const sources: WebSearchSource[] = [];
  for (const candidate of candidates) {
    const url = parseSafeActivityHttpUrl(candidate.url);
    if (!url || seen.has(url.href)) continue;
    seen.add(url.href);
    sources.push({
      title: cleanTitle(candidate.title) || displayWebHost(url.hostname),
      href: url.href,
      host: displayWebHost(url.hostname),
      displayUrl: formatCompactWebUrl(url),
    });
    if (sources.length >= MAX_VISIBLE_SOURCES) break;
  }
  return sources;
}

function structuredCandidates(value: unknown): Array<{ title: string; url: string }> {
  const items: unknown[] = [];
  if (Array.isArray(value)) items.push(...value);
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    for (const key of ["results", "items", "sources", "data"]) {
      if (Array.isArray(record[key])) items.push(...record[key]);
    }
  }

  return items.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const title = stringField(record, ["title", "name", "label"]);
    const url = stringField(record, ["url", "href", "link", "uri"]);
    return url ? [{ title, url }] : [];
  });
}

function textCandidates(text: string): Array<{ title: string; url: string }> {
  const lines = text.split(/\r?\n/).map((line) => line.trim());
  const candidates: Array<{ title: string; url: string }> = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line) continue;

    const markdownLink = /^\s*(?:\d+[.)]\s*)?\[([^\]]+)]\((https?:\/\/[^)]+)\)\s*$/.exec(line);
    if (markdownLink) {
      candidates.push({ title: markdownLink[1], url: markdownLink[2] });
      continue;
    }

    const numberedTitle = /^\d+[.)]\s+(.+)$/.exec(line);
    if (!numberedTitle) continue;

    const inlineUrl = firstHttpUrl(numberedTitle[1]);
    if (inlineUrl) {
      candidates.push({
        title: numberedTitle[1].replace(inlineUrl, "").replace(/[\s:|\-–—]+$/, ""),
        url: inlineUrl,
      });
      continue;
    }

    for (let next = index + 1; next < lines.length; next += 1) {
      if (/^\d+[.)]\s+/.test(lines[next])) break;
      const url = firstHttpUrl(lines[next]);
      if (!url) continue;
      candidates.push({ title: numberedTitle[1], url });
      break;
    }
  }

  return candidates;
}

function firstHttpUrl(value: string): string {
  return value.match(/https?:\/\/[^\s<>"']+/i)?.[0]?.replace(/[),.;\]}]+$/, "") ?? "";
}

function cleanTitle(value: string): string {
  return redactActivityText(value)
    .replace(/^#+\s*/, "")
    .replace(/^\*\*(.*)\*\*$/, "$1")
    .replace(/^__(.*)__$/, "$1")
    .trim();
}

function compactToolName(name: string): string {
  return name.toLowerCase().split(".").pop() || name.toLowerCase();
}

function webSearchScope(rawSite: string): string | undefined {
  const candidate = rawSite.replace(/^https?:\/\//i, "").replace(/^www\./i, "");
  let host = candidate.split("/")[0]?.toLowerCase();
  if (!host) return undefined;
  if (host.startsWith("www.")) host = host.slice(4);

  const knownScope = WEB_SEARCH_SCOPE_NAMES[host];
  return knownScope ?? displayWebHost(host);
}

const WEB_SEARCH_SCOPE_NAMES: Record<string, string> = {
  "anthropic.com": "Anthropic",
  "crunchbase.com": "Crunchbase",
  "github.com": "GitHub",
  "linkedin.com": "LinkedIn",
  "openai.com": "OpenAI",
  "reddit.com": "Reddit",
  "x.com": "X",
  "youtube.com": "YouTube",
};

function toolEventName(event: ToolProgressEvent): string {
  const functionName = (event as { function?: { name?: unknown } }).function?.name;
  if (typeof functionName === "string") return functionName;
  return typeof event.name === "string" ? event.name : "";
}

function toolEventArguments(event: ToolProgressEvent): unknown {
  const functionArgs = (event as { function?: { arguments?: unknown } }).function?.arguments;
  const raw = functionArgs ?? event.arguments;
  if (typeof raw !== "string") return raw ?? {};
  try {
    return raw.trim() ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function stringField(value: unknown, keys: string[]): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    const field = record[key];
    if (typeof field === "string" && field.trim()) return field.trim();
  }
  return "";
}

function readableError(error: unknown): string | undefined {
  if (typeof error === "string" && error.trim()) return safeErrorText(error);
  if (!error) return undefined;
  try {
    return safeErrorText(JSON.stringify(error));
  } catch {
    return "Web search failed";
  }
}

function safeErrorText(value: string): string {
  return safeActivityDetail(value, 240);
}
