/** One-shot handoff from a trusted server console, held in memory, never storage. */
export interface PairReturn { id: string; code: string }

let pending: PairReturn | null = null;
const listeners = new Set<() => void>();

export function parsePairReturn(hash: string): PairReturn | null {
  const [path, query = ""] = hash.split("?", 2);
  if (path !== "#/remote") return null;
  const params = new URLSearchParams(query);
  if (!params.has("pairing")) return null;
  const invalid = { id: "", code: "" };
  const code = params.get("pairing") || "";
  if (params.getAll("pairing").length !== 1 || code.length > 32768 || !/^nbpc1\.[A-Za-z0-9_-]+$/.test(code)) return invalid;
  try {
    const encoded = code.slice(6).replace(/-/g, "+").replace(/_/g, "/");
    const envelope: unknown = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "=")));
    if (!envelope || typeof envelope !== "object" || !("id" in envelope)
      || typeof envelope.id !== "string" || !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(envelope.id)) return invalid;
    // The backend must decrypt and validate this. A parsed ID grants no access.
    return { id: envelope.id, code };
  } catch { return invalid; }
}

export function initializePairReturn(): void {
  const returned = parsePairReturn(window.location.hash);
  if (!returned) return;
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#/remote`);
  // A remote iframe must never become a local connection controller.
  if (window.top === window && window.location.protocol === "http:"
    && ["127.0.0.1", "localhost", "[::1]"].includes(window.location.hostname)) {
    pending = returned;
    listeners.forEach((listener) => listener());
  }
}

export function readPairReturn(): PairReturn | null { return pending; }
export function subscribePairReturn(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function clearPairReturn(): void {
  pending = null;
  listeners.forEach((listener) => listener());
}

export function pairingReturnOrigin(): string {
  return window.top === window && window.location.protocol === "http:"
    && ["127.0.0.1", "localhost", "[::1]"].includes(window.location.hostname)
    ? window.location.origin : "";
}
