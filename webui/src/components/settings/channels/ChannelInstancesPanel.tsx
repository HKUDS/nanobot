import type { ReactNode } from "react";

import {
  configureChannel,
  disableNanobotFeature,
  enableNanobotFeature,
} from "@/lib/api";
import type { NanobotChannelInstanceInfo, NanobotFeatureInfo, NanobotFeaturesPayload } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";
import {
  ChannelInstancesPanelView,
  type ChannelInstancesPanelCustomization,
  type ChannelInstancesPanelViewProps,
} from "./ChannelInstancesPanelView";

export type { ChannelInstancesPanelCustomization } from "./ChannelInstancesPanelView";

export function ChannelInstancesPanel({
  feature,
  showBrandLogos,
  instances,
  onFeaturesUpdate,
  customization,
  renderView,
}: {
  feature: NanobotFeatureInfo;
  showBrandLogos: boolean;
  instances?: NanobotChannelInstanceInfo[];
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  customization?: ChannelInstancesPanelCustomization;
  renderView?: (props: ChannelInstancesPanelViewProps) => ReactNode;
}) {
  const { client } = useClient();
  const viewProps: ChannelInstancesPanelViewProps = {
    feature,
    showBrandLogos,
    instances,
    customization,
    onToggleInstance: async (instance, checked) => {
      const payload = checked
        ? await enableNanobotFeature(client, feature.name, { instanceId: instance.id })
        : await disableNanobotFeature(client, feature.name, { instanceId: instance.id });
      onFeaturesUpdate(payload);
    },
    onSaveInstance: async (instance, values) => {
      const payload = await configureChannel(client, feature.name, values, {
        enable: instance.enabled,
        instanceId: instance.id,
      });
      if (payload.nanobot_features) onFeaturesUpdate(payload.nanobot_features);
    },
  };
  return renderView ? renderView(viewProps) : <ChannelInstancesPanelView {...viewProps} />;
}
