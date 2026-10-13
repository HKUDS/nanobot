import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import { ChannelInstancesPanel } from "@/components/settings/channels/ChannelInstancesPanel";
import { FeishuAssistantsPanelView } from "./FeishuAssistantsPanelView";
import { FeishuConnectFlow } from "./FeishuConnectFlow";

export function FeishuAssistantsPanel({
  token,
  feature,
  showBrandLogos,
  onFeaturesUpdate,
}: ChannelPluginPanelProps) {
  return <ChannelInstancesPanel
    feature={feature}
    showBrandLogos={showBrandLogos}
    onFeaturesUpdate={onFeaturesUpdate}
    renderView={(props) => <FeishuAssistantsPanelView
      {...props}
      renderConnectFlow={(options) => <FeishuConnectFlow
        {...options}
        token={token}
        onFeaturesUpdate={onFeaturesUpdate}
      />}
    />}
  />;
}
