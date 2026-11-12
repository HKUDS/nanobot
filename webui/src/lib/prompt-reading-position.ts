export const PROMPT_READING_PAGE_LIMIT = 3;
const POSITION_LIMIT = 128;

export interface PromptPageQuery {
  cursor: string;
  direction: "before" | "after";
}

export interface PromptReadingPosition {
  queries: PromptPageQuery[];
  generation?: string;
}

function parsePosition(value: unknown): PromptReadingPosition | undefined {
  if (!value || typeof value !== "object" || !("queries" in value) || !Array.isArray(value.queries)
    || !value.queries.length || value.queries.length > PROMPT_READING_PAGE_LIMIT) return;
  const queries: PromptPageQuery[] = [];
  for (const query of value.queries) {
    if (!query || typeof query !== "object" || typeof query.cursor !== "string" || !query.cursor.length
      || query.cursor.length > 8192 || (query.direction !== "before" && query.direction !== "after")) return;
    queries.push({ cursor: query.cursor, direction: query.direction });
  }
  if ("generation" in value && value.generation !== undefined
    && (typeof value.generation !== "string" || value.generation.length > 1024)) return;
  return { queries, ...("generation" in value && typeof value.generation === "string" ? { generation: value.generation } : {}) };
}

function copyPosition(position: PromptReadingPosition): PromptReadingPosition {
  return { queries: position.queries.map(({ cursor, direction }) => ({ cursor, direction })),
    ...(position.generation === undefined ? {} : { generation: position.generation }) };
}

/** Client-scoped, reload-safe window descriptors; never retains message bodies or credentials. */
export class PromptReadingPositionStore {
  private readonly positions = new Map<string, PromptReadingPosition>();
  private readonly listeners = new Set<() => void>();

  constructor(saved?: unknown) {
    if (!Array.isArray(saved)) return;
    for (const entry of saved) {
      if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string" || !entry[0].length) continue;
      const position = parsePosition(entry[1]);
      if (position) this.set(entry[0], position);
    }
  }

  get(key: string): PromptReadingPosition | undefined {
    const position = this.positions.get(key);
    if (!position) return;
    this.positions.delete(key);
    this.positions.set(key, position);
    return copyPosition(position);
  }

  set(key: string, position: PromptReadingPosition): void {
    const parsed = parsePosition(position);
    if (!key || !parsed) return;
    this.positions.delete(key);
    this.positions.set(key, parsed);
    while (this.positions.size > POSITION_LIMIT) this.positions.delete(this.positions.keys().next().value!);
    this.notify();
  }

  delete(key: string): void {
    if (this.positions.delete(key)) this.notify();
  }

  clear(): void {
    if (!this.positions.size) return;
    this.positions.clear();
    this.notify();
  }

  entries(): [string, PromptReadingPosition][] {
    return Array.from(this.positions, ([key, position]) => [key, copyPosition(position)]);
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}
