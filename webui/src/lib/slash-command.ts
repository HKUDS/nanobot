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
  const command = matchingSlashCommand(content, slashCommands);
  if (!command) return null;
  if (command.lifecycle === "agent_turn_with_args") {
    return slashCommandArgs(content, command.command).length > 0
      ? "agent_turn"
      : "side_channel";
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
