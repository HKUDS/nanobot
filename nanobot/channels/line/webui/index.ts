/** LINE channel WebUI plugin.
 *
 * Registers LINE in the channel setup panel with localization keys.
 */
import type { ChannelUiPlugin } from "../../../../channel-plugins/types";

const plugin: ChannelUiPlugin = {
  channel: "line",
  setupComponent: null, // uses built-in credential form
};

export default plugin;
