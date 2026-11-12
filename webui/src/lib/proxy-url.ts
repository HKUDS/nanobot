const environmentReference = /\$\{[A-Za-z_][A-Za-z0-9_]*\}/;

function decodeCredential(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function encodeCredential(value: string): string {
  return value.split(/(\$\{[A-Za-z_][A-Za-z0-9_]*\})/).map((part) =>
    environmentReference.test(part) ? part : encodeURIComponent(part),
  ).join("");
}

export function splitProxyUrl(value: string) {
  const schemeEnd = value.indexOf("://");
  const start = schemeEnd < 0 ? 0 : schemeEnd + 3;
  const authorityEnd = value.slice(start).search(/[/?#]/);
  const end = authorityEnd < 0 ? value.length : start + authorityEnd;
  const at = value.lastIndexOf("@", end - 1);
  const userinfo = at >= start ? value.slice(start, at) : null;
  const colon = userinfo?.indexOf(":") ?? -1;
  const rawUsername = userinfo === null ? "" : colon < 0 ? userinfo : userinfo.slice(0, colon);
  const rawPassword = userinfo === null || colon < 0 ? "" : userinfo.slice(colon + 1);
  return {
    address: userinfo === null ? value : value.slice(0, start) + value.slice(at + 1),
    username: decodeCredential(rawUsername),
    password: decodeCredential(rawPassword),
    rawUsername,
    rawPassword,
    userinfo,
    hasColon: colon >= 0,
  };
}

function insertUserinfo(address: string, userinfo: string | null): string {
  if (userinfo === null) return address;
  const schemeEnd = address.indexOf("://");
  const start = schemeEnd < 0 ? 0 : schemeEnd + 3;
  return address.slice(0, start) + userinfo + "@" + address.slice(start);
}

export function changeProxyAddress(value: string, address: string): string {
  if (!address.trim() || isProxyUrlReference(address)) return address;
  const pasted = splitProxyUrl(address);
  if (pasted.userinfo !== null) return address;
  return insertUserinfo(address, splitProxyUrl(value).userinfo);
}

export function changeProxyAuthentication(value: string, username: string, password: string): string {
  const current = splitProxyUrl(value);
  if (!username && !password) return current.address;
  const user = username === current.username ? current.rawUsername : encodeCredential(username);
  const pass = password === current.password ? current.rawPassword : encodeCredential(password);
  const separator = current.hasColon || password ? ":" : "";
  return insertUserinfo(current.address, user + separator + pass);
}

export function isProxyUrlReference(address: string): boolean {
  return /^\$\{[A-Za-z_][A-Za-z0-9_]*\}$/.test(address.trim());
}
