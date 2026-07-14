import type {
  ChannelUiContribution,
  RegisteredChannelUiContribution,
} from "@/channel-plugins/types";

type ChannelUiContributionModule = {
  default?: ChannelUiContribution;
};

const modules = import.meta.glob<ChannelUiContributionModule>(
  "../../../nanobot/channels/*/webui/**/*.{ts,tsx}",
  {
    eager: true,
  },
);

const registrations = new Map<string, RegisteredChannelUiContribution>();

for (const [modulePath, module] of Object.entries(modules)) {
  const contribution = module.default;
  if (!contribution) continue;
  const match = modulePath.match(/nanobot\/channels\/([^/]+)\/(.+)$/);
  if (!match) {
    throw new Error(`Cannot derive channel UI identity from '${modulePath}'`);
  }
  const [, channel, webui] = match;
  registrations.set(registrationKey(channel, webui), { channel, webui, contribution });
}

export function channelUiContribution(
  channel: string,
  webui: string | undefined,
): ChannelUiContribution | undefined {
  if (!webui) return undefined;
  return registrations.get(registrationKey(channel, webui))?.contribution;
}

export function registeredChannelUiContributions(): readonly RegisteredChannelUiContribution[] {
  return [...registrations.values()];
}

function registrationKey(channel: string, webui: string): string {
  return `${channel}:${webui.replaceAll("\\", "/")}`;
}
