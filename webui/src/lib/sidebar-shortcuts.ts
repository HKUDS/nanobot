export const SIDEBAR_SHORTCUTS = {
  newChat: { key: "O", shift: true },
  search: { key: "K", shift: false },
  apps: { key: "1", shift: true },
  skills: { key: "2", shift: true },
  automations: { key: "3", shift: true },
  channels: { key: "4", shift: true },
  settings: { key: ",", shift: false },
} as const;

export type SidebarShortcut = keyof typeof SIDEBAR_SHORTCUTS;

export function sidebarShortcutLabel(action: SidebarShortcut, apple: boolean): string {
  const { key, shift } = SIDEBAR_SHORTCUTS[action];
  return apple ? `⌘${shift ? "⇧" : ""}${key}` : `Ctrl+${shift ? "Shift+" : ""}${key}`;
}

export function sidebarShortcutAria(action: SidebarShortcut): string {
  const { key, shift } = SIDEBAR_SHORTCUTS[action];
  const suffix = `${shift ? "Shift+" : ""}${key}`;
  return `Meta+${suffix} Control+${suffix}`;
}

export function matchSidebarShortcut(event: KeyboardEvent): SidebarShortcut | undefined {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.altKey ||
      !(event.metaKey || event.ctrlKey)) return undefined;
  return (Object.keys(SIDEBAR_SHORTCUTS) as SidebarShortcut[]).find((action) => {
    const { key, shift } = SIDEBAR_SHORTCUTS[action];
    return event.shiftKey === shift && (event.key.toUpperCase() === key ||
      (/^[0-9]$/.test(key) && event.code === `Digit${key}`));
  });
}
