import type { ComponentType } from "react";

import type { ChannelPresentation } from "@/components/settings/channels/catalog";
import type {
  NanobotFeatureInfo,
  NanobotFeaturesPayload,
} from "@/lib/types";

export type ChannelFeatureActionOptions = {
  installOnly?: boolean;
};

export type ChannelFeatureAction = (
  action: "enable" | "disable",
  name: string,
  options?: ChannelFeatureActionOptions,
) => void;

export type ChannelPluginPanelProps = {
  token: string;
  feature: NanobotFeatureInfo;
  actionKey: string | null;
  chatAppsDocsUrl?: string;
  showBrandLogos: boolean;
  onAction: ChannelFeatureAction;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
};

export type ChannelPluginConnectFlowProps = {
  token: string;
  feature: NanobotFeatureInfo;
  idleLabel?: string;
  connectRequestId?: number;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
};

export type ChannelUiContribution = {
  presentation: ChannelPresentation;
  aliases?: Record<string, Partial<ChannelPresentation>>;
  Panel?: ComponentType<ChannelPluginPanelProps>;
  ConnectFlow?: ComponentType<ChannelPluginConnectFlowProps>;
  canConnectBeforeConfigured?: boolean;
};

export type RegisteredChannelUiContribution = {
  channel: string;
  webui: string;
  contribution: ChannelUiContribution;
};
