// Gateway control actions carry this turn identity in both live and stored events.
const SYSTEM_COMMAND_PREFIX = "webui-system:"

export function systemCommandTurnId(): string {
  return SYSTEM_COMMAND_PREFIX + crypto.randomUUID()
}

export function isSystemCommandTurnId(id: string | undefined): boolean {
  return id?.startsWith(SYSTEM_COMMAND_PREFIX) === true
}
