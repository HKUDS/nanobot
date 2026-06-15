export function getBasePath(): string {
  if (typeof window === "undefined") return "";
  const pathname = window.location.pathname || "/";
  const dir = pathname.endsWith("/")
    ? pathname
    : pathname.slice(0, pathname.lastIndexOf("/") + 1);
  return dir.replace(/\/+$/, "");
}
