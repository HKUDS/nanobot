export function parsePublicHttpUrl(value: string): URL | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (url.username || url.password) return null;
    if (isPrivateHostname(url.hostname)) return null;
    return url;
  } catch {
    return null;
  }
}

/** Public URL normalized for timeline display, with credentials and request-specific noise removed. */
export function parseSafeActivityHttpUrl(value: string): URL | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (isPrivateHostname(url.hostname)) return null;
    url.username = "";
    url.password = "";
    url.search = "";
    url.hash = "";
    return url;
  } catch {
    return null;
  }
}

export function displayWebHost(hostname: string): string {
  return hostname.replace(/^www\./i, "").toLowerCase();
}

export function formatCompactWebUrl(url: URL): string {
  const host = displayWebHost(url.hostname);
  const path = url.pathname && url.pathname !== "/" ? url.pathname.replace(/\/$/, "") : "";
  return `${host}${path}`;
}

function isPrivateHostname(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (
    !host
    || host === "localhost"
    || [".local", ".localhost", ".internal", ".home", ".lan"].some((suffix) => host.endsWith(suffix))
  ) return true;
  if (!host.includes(".") && !host.includes(":")) return true;

  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (ipv4) {
    const [, aText, bText] = ipv4;
    const a = Number(aText);
    const b = Number(bText);
    return (
      a === 0 ||
      a === 10 ||
      a === 127 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168)
    );
  }

  return (
    host === "::"
    || host === "::1"
    || host.startsWith("::ffff:")
    || host.startsWith("fc")
    || host.startsWith("fd")
    || host.startsWith("fe80:")
  );
}
