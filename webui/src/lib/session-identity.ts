export function isChannelChatAlias(value: unknown): value is `channel.${string}` {
  return typeof value === "string" && /^channel\.[A-Za-z0-9_-]+$/.test(value);
}

export function isSessionKey(key: string): boolean {
  const separator = key.indexOf(":");
  return separator > 0 && separator < key.length - 1;
}
