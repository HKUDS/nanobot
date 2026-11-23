import { normalizeCodeLanguage } from "./code-language";
import type { CodeLine } from "./code-tokens";

export interface CodeHighlight {
  read(): CodeLine[];
}

const MAX_CACHED_SOURCE_BYTES = 2 * 1024 * 1024;
const MAX_CACHE_ENTRIES = 16;
const cache = new Map<string, CodeHighlight>();
let sourceBytes = 0;

function cacheKey(source: string, language: string): string {
  return `${normalizeCodeLanguage(language)}\0${source}`;
}

export function cachedCodeHighlight(source: string, language: string): CodeHighlight | undefined {
  const key = cacheKey(source, language);
  const resource = cache.get(key);
  if (resource) {
    cache.delete(key);
    cache.set(key, resource);
  }
  return resource;
}

export function discardCodeHighlight(source: string, language: string): void {
  const key = cacheKey(source, language);
  if (cache.delete(key)) sourceBytes -= key.length * 2;
}

export function cacheCodeHighlight(source: string, language: string, resource: CodeHighlight): void {
  const key = cacheKey(source, language);
  const bytes = key.length * 2;
  if (bytes > MAX_CACHED_SOURCE_BYTES) return;
  discardCodeHighlight(source, language);
  while (cache.size >= MAX_CACHE_ENTRIES || sourceBytes + bytes > MAX_CACHED_SOURCE_BYTES) {
    const oldest = cache.keys().next().value!;
    cache.delete(oldest);
    sourceBytes -= oldest.length * 2;
  }
  cache.set(key, resource);
  sourceBytes += bytes;
}
