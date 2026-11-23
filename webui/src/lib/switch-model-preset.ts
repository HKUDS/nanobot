import i18n from "i18next";

import { renderCommandResult } from "../../../packages/client-events/command-result";
import type { NanobotClient } from "@/lib/nanobot-client";

/** Only a successful switch changes the badge; never infer a preset from displayed text. */
function switchedModelPreset(result: unknown): string | undefined {
  if (!result || typeof result !== "object" || !("command" in result) || result.command !== "/model"
    || !("parts" in result) || !Array.isArray(result.parts)) return undefined
  for (const part of result.parts as unknown[]) {
    if (part && typeof part === "object" && "key" in part && part.key === "model.switched"
      && "values" in part && part.values && typeof part.values === "object" && "preset" in part.values
      && typeof part.values.preset === "string" && part.values.preset) return part.values.preset
  }
  return undefined
}

export async function switchModelPreset(client: NanobotClient, chatId: string, name: string): Promise<string> {
  if (client.status !== "open") throw new Error(i18n.t("connection.closed"));
  const reply = await client.sendSystemCommand(chatId, `/model ${name}`);
  const preset = switchedModelPreset(reply?.command_result);
  if (preset) return preset;
  throw new Error(renderCommandResult(reply?.command_result, i18n.resolvedLanguage ?? i18n.language)
    ?? (reply?.text || i18n.t("message.agentActivity.commandFailed")));
}
