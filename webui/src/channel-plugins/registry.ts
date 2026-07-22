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
const registrationsByChannel = new Map<string, RegisteredChannelUiContribution>();
const presentationsByChannel = new Map<string, ChannelUiContribution["presentation"]>();
const translationOwners = new Map<string, string>();

for (const [modulePath, module] of Object.entries(modules)) {
  const contribution = module.default;
  if (!contribution) continue;
  const match = modulePath.match(/nanobot\/channels\/([^/]+)\/(.+)$/);
  if (!match) {
    throw new Error(`Cannot derive channel UI identity from '${modulePath}'`);
  }
  const [, channel, webui] = match;
  const registration = { channel, webui, contribution };
  if (registrationsByChannel.has(channel)) {
    throw new Error(`Channel '${channel}' has more than one UI contribution`);
  }
  registrations.set(registrationKey(channel, webui), registration);
  registrationsByChannel.set(channel, registration);
  presentationsByChannel.set(channel, contribution.presentation);
  translationOwners.set(channel, channel);
  for (const [alias, aliasPresentation] of Object.entries(contribution.aliases ?? {})) {
    if (presentationsByChannel.has(alias)) {
      throw new Error(`Channel UI alias '${alias}' is registered more than once`);
    }
    presentationsByChannel.set(alias, {
      ...contribution.presentation,
      ...aliasPresentation,
    });
    translationOwners.set(alias, channel);
  }
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

export function channelUiOwner(channel: string): string {
  return translationOwners.get(channel) ?? channel;
}

export function channelUiPresentation(
  channel: string,
): ChannelUiContribution["presentation"] | undefined;
export function channelUiPresentation(
  channel: string,
  webui: string | undefined,
): ChannelUiContribution["presentation"] | undefined;
export function channelUiPresentation(
  channel: string,
  webui?: string,
): ChannelUiContribution["presentation"] | undefined {
  if (arguments.length > 1) return channelUiContribution(channel, webui)?.presentation;
  return presentationsByChannel.get(channel);
}

function registrationKey(channel: string, webui: string): string {
  return `${channel}:${webui.replaceAll("\\", "/")}`;
}
