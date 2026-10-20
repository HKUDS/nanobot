import type { SlashCommand } from "@/lib/types";

type ResolvedSlashCommandLifecycle =
  | "side_channel"
  | "finalize_active_turn"
  | "stop_active_turn"
  | "agent_turn";

function slashCommandName(content: string): string {
  return content.split(/\s+/, 1)[0];
}

function slashCommandArgs(content: string, commandName: string): string {
  return content.slice(commandName.length).trim();
}

export function isRegisteredSlashCommand(content: string, slashCommands: SlashCommand[]): boolean {
  // Argument validation belongs to the gateway. Even invalid commands must not
  // wait behind the active response; paths and unknown names are ordinary text.
  const name = slashCommandName(content.trim()).replace(/@[A-Za-z0-9_]+$/, "").toLowerCase();
  return slashCommands.some((item) => item.command === name);
}

export function matchingSlashCommand(
  content: string,
  slashCommands: SlashCommand[],
): SlashCommand | null {
  const commandName = slashCommandName(content);
  if (!commandName.startsWith("/")) return null;
  const command = slashCommands.find((item) => item.command === commandName);
  if (!command) return null;
  if (slashCommandArgs(content, command.command).length > 0 && !command.acceptsArgs) return null;
  return command;
}

export function slashCommandLifecycle(
  content: string,
  slashCommands: SlashCommand[],
): ResolvedSlashCommandLifecycle | null {
  const normalized = content.trim();
  const enteredName = slashCommandName(normalized);
  const name = enteredName.replace(/@[A-Za-z0-9_]+$/, "").toLowerCase();
  const command = slashCommands.find((item) => item.command === name);
  if (!command) return null;
  const args = normalized.slice(enteredName.length).trim();
  // Registered argument errors are immediate command replies, not new agent
  // requests or the command's valid Stop/New effects. The gateway validates them.
  if (args && !command.acceptsArgs) return "side_channel";
  if (command.lifecycle === "agent_turn_with_args") {
    return args ? "agent_turn" : "side_channel";
  }
  return command.lifecycle;
}

export function isSideChannelLifecycle(
  lifecycle: ResolvedSlashCommandLifecycle | null,
): boolean {
  return (
    lifecycle === "side_channel"
    || lifecycle === "finalize_active_turn"
    || lifecycle === "stop_active_turn"
  );
}
