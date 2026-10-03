/** Only explicit web URLs belong in the web-link menu; file/session links have other owners. */
export function parseWebLink(value: string): URL | null {
  if (value.length > 8192 || value.includes("\\")
    || Array.from(value).some((char) => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127)) return null;
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

export function webPreviewRestriction(
  url: URL,
  pageUrl: URL,
  native: boolean,
  credentialless: boolean,
): "native" | "unsupported" | "sameOrigin" | "mixedContent" | null {
  if (native) return "native";
  if (!credentialless) return "unsupported";
  if (url.origin === pageUrl.origin) return "sameOrigin";
  if (pageUrl.protocol === "https:" && url.protocol === "http:") return "mixedContent";
  return null;
}
