import i18n from "i18next";

import type { NanobotClient } from "@/lib/nanobot-client";

export async function switchModelPreset(client: NanobotClient, chatId: string, name: string): Promise<string> {
  if (client.status !== "open") throw new Error(i18n.t("connection.closed"));
  const reply = await client.sendSystemCommand(chatId, `/model ${name}`);
  const result = reply?.command_result;
  if (result?.command === "/model" && typeof result.switched_preset === "string" && result.switched_preset) return result.switched_preset;
  if (result?.command === "/model" && result.switched_preset === null && reply?.text) throw new Error(reply.text);
  throw new Error(i18n.t("thread.composer.modelSwitchUnconfirmed"));
}
