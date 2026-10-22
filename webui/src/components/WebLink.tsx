import type { ComponentPropsWithoutRef } from "react";

function parseWebLink(value: string): URL | null {
  if (value.length > 8192 || value.includes("\\")
    || Array.from(value).some((char) => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127)) return null;
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

export function WebLink({ href = "", children, ...props }: ComponentPropsWithoutRef<"a">) {
  const url = parseWebLink(href);
  // Keep the renderer's relative media/document and mail links unchanged.
  const relative = !/^[a-z][a-z\d+.-]*:/i.test(href)
    && !href.includes("\\") && !Array.from(href).some((char) => char.charCodeAt(0) < 32);
  return url || relative || /^(mailto:|tel:|#)/i.test(href)
    ? <a {...props} href={href} target="_blank" rel="noreferrer noopener">{children}</a> : <>{children}</>;
}
