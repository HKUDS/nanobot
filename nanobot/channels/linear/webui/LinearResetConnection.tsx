import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelConfigField } from "@/channel-plugins/catalog";
import { defaultChannelFieldValues } from "@/components/settings/channels/CredentialForm";
import { configureChannel, disableNanobotFeature } from "@/lib/api";
import type { NanobotFeaturesPayload } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

import { manageLinearWorkspace } from "./api";
import type { LinearInstallationSummary } from "./types";
import { LinearResetConnectionView } from "./LinearResetConnectionView";

/** Keep credentials until every workspace has been revoked and the channel has stopped. */
export function LinearResetConnection({
  fields, disabled, onBusyChange, onWorkspacesChange, onWorkspaceRemoved, onFeaturesUpdate, onComplete,
}: {
  fields: ChannelConfigField[];
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onWorkspacesChange: (workspaces: LinearInstallationSummary[]) => void;
  onWorkspaceRemoved: (organizationId: string) => void;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  onComplete?: () => void;
}) {
  const { client } = useClient();
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const reset = async () => {
    onBusyChange(true);
    try {
      // Inspect even when the channel is stopped or the display cache is empty/stale.
      const current = await manageLinearWorkspace(client, { operation: "inspect" });
      if (!current.installations) throw new Error(tx("custom.resetInspectFailed", "Could not verify connected workspaces. App settings were kept."));
      onWorkspacesChange(current.installations);
      for (const workspace of current.installations) {
        const result = await manageLinearWorkspace(client, {
          operation: "disconnect", organization_id: workspace.organization_id,
        });
        if (!result.installations || result.installations.some(item => item.organization_id === workspace.organization_id)) {
          throw new Error(tx("custom.resetInspectFailed", "Could not verify connected workspaces. App settings were kept."));
        }
        onWorkspaceRemoved(workspace.organization_id);
        onWorkspacesChange(result.installations);
      }
      const remaining = await manageLinearWorkspace(client, { operation: "inspect" });
      if (!remaining.installations) throw new Error(tx("custom.resetInspectFailed", "Could not verify connected workspaces. App settings were kept."));
      onWorkspacesChange(remaining.installations);
      if (remaining.installations.length) {
        throw new Error(tx("custom.resetChanged", "Another workspace was connected. Review the connections and try again."));
      }
      const stopped = await disableNanobotFeature(client, "linear");
      onFeaturesUpdate(stopped);
      const linear = stopped.features.find(item => item.name === "linear");
      if (!linear || linear.enabled || linear.runtime_status === "running"
        || stopped.requires_restart || stopped.last_action?.ok === false) {
        throw new Error(tx("custom.resetStopFailed", "The Linear channel could not be stopped. App settings were kept."));
      }
      const defaults = defaultChannelFieldValues(fields);
      const result = await configureChannel(client, "linear", Object.fromEntries(
        fields.map(field => [field.key, field.secret ? null : defaults[field.key]]),
      ));
      if (!result.saved) throw new Error(tx("custom.resetSaveFailed", "Could not clear the app settings. Please retry."));
      if (result.nanobot_features) onFeaturesUpdate(result.nanobot_features);
      onComplete?.();
    } finally {
      onBusyChange(false);
    }
  };

  return <LinearResetConnectionView disabled={disabled} onReset={reset} />;
}
