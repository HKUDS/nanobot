import i18n from "i18next";

import { renderCommandResult } from "../../../packages/client-events/command-result";
import { switchedModelPreset } from "../../../packages/client-events/model-selection";
import type { NanobotClient } from "@/lib/nanobot-client";

export async function switchModelPreset(client: NanobotClient, chatId: string, name: string): Promise<string> {
  const reply = client.status === "open"
    ? await client.sendSystemCommand(chatId, `/model ${name}`).catch(() => undefined)
    : undefined;
  const preset = switchedModelPreset(reply?.command_result);
  if (preset) return preset;
  throw new Error(renderCommandResult(reply?.command_result, i18n.resolvedLanguage ?? i18n.language)
    ?? (reply?.text || i18n.t("thread.composer.modelSwitchUnconfirmed")));
}
