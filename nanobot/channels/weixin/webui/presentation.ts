export const WEIXIN_PRIMARY_FIELD_KEYS = [
  "channels.weixin.sendProgress",
  "channels.weixin.sendToolHints",
  "channels.weixin.streaming",
] as const;

export const WEIXIN_ADVANCED_FIELD_KEYS = [
  "channels.weixin.allowFrom",
  "channels.weixin.token",
  "channels.weixin.replyProgressMessages",
  "channels.weixin.replyProgressMaxMessages",
  "channels.weixin.contextMessageBudget",
  "channels.weixin.blockStreaming",
  "channels.weixin.blockStreamingMinChars",
  "channels.weixin.blockStreamingMaxMessages",
  "channels.weixin.baseUrl",
  "channels.weixin.cdnBaseUrl",
  "channels.weixin.routeTag",
  "channels.weixin.stateDir",
  "channels.weixin.pollTimeout",
] as const;
