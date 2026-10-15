import { channelFieldMessageKey } from "@/channel-plugins/i18n";
import { channelLocaleMessages } from "@/channel-plugins/locale-registry";
import type { ChannelConfigField } from "@/channel-plugins/catalog";
import { normalizeLocale } from "@/i18n/config";
import type { ChannelConnectPayload, ChannelSetupContractField, NanobotFeatureInfo } from "@/lib/types";

export const WEIXIN_AUTH_EXPIRED_MESSAGE =
  "WeChat login expired. Scan again to reconnect.";

export type WeixinVerificationPayload = ChannelConnectPayload & {
  challenge: "verify_code";
  verification_failed?: boolean;
};

export function isVerificationChallenge(
  payload: ChannelConnectPayload,
): payload is WeixinVerificationPayload {
  return (
    "challenge" in payload
    && payload.challenge === "verify_code"
    && (
      !("verification_failed" in payload)
      || typeof payload.verification_failed === "boolean"
    )
  );
}

export const WEIXIN_PRIMARY_FIELD_KEYS = [
  "channels.weixin.sendProgress",
  "channels.weixin.sendToolHints",
  "channels.weixin.streaming",
] as const;

export const WEIXIN_QR_TOKEN_FIELD_KEY = "channels.weixin.token";

export const WEIXIN_ADVANCED_FIELD_KEYS = [
  "channels.weixin.allowFrom",
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

export function weixinSetupFields(
  feature: NanobotFeatureInfo,
  locale: string,
): { primary: ChannelConfigField[]; advanced: ChannelConfigField[] } {
  const fields = (feature.setup?.fields ?? []).filter(
    (field) => field.key !== WEIXIN_QR_TOKEN_FIELD_KEY,
  );
  const fieldsByKey = new Map(fields.map((field) => [field.key, field]));
  const messages = channelLocaleMessages("weixin", normalizeLocale(locale))?.setup;
  const knownKeys = new Set<string>([
    ...WEIXIN_PRIMARY_FIELD_KEYS,
    ...WEIXIN_ADVANCED_FIELD_KEYS,
  ]);
  const extraKeys = fields
    .map((field) => field.key)
    .filter((key) => !knownKeys.has(key));
  const hydrate = (keys: readonly string[]) => keys.flatMap((key) => {
    const field = fieldsByKey.get(key);
    if (!field) return [];
    const copy = messages?.fields?.[channelFieldMessageKey("weixin", key)];
    return [weixinConfigField(field, copy)];
  });

  return {
    primary: hydrate(WEIXIN_PRIMARY_FIELD_KEYS),
    advanced: hydrate([...WEIXIN_ADVANCED_FIELD_KEYS, ...extraKeys]),
  };
}

function weixinConfigField(
  field: ChannelSetupContractField,
  copy: { label: string; placeholder?: string; choices?: Record<string, string> }
    | undefined,
): ChannelConfigField {
  const choices = field.kind === "bool" ? ["true", "false"] : field.choices;
  return {
    key: field.key,
    label: copy?.label ?? fieldLabel(field.field),
    placeholder: copy?.placeholder,
    secret: field.kind === "secret",
    optional: !field.required,
    inputType: field.kind === "int" ? "number" : undefined,
    defaultValue: field.default_value,
    options:
      field.kind === "enum" || field.kind === "bool"
        ? choices.map((choice) => ({
            value: choice,
            label: copy?.choices?.[choice] ?? fieldLabel(choice),
          }))
        : undefined,
  };
}

function fieldLabel(value: string): string {
  const spaced = value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : value;
}

export function weixinRuntimeError(
  error: string | undefined,
  tx: (key: string, fallback: string) => string,
): string | undefined {
  if (error === WEIXIN_AUTH_EXPIRED_MESSAGE) {
    return tx("custom.expired", error);
  }
  return error;
}

export function localizeBooleanFields(
  fields: ChannelConfigField[],
  onLabel: string,
  offLabel: string,
): ChannelConfigField[] {
  return fields.map((field) => {
    const values = new Set(field.options?.map((option) => option.value));
    if (values.size !== 2 || !values.has("true") || !values.has("false")) return field;
    return {
      ...field,
      options: field.options?.map((option) => ({
        ...option,
        label: option.value === "true" ? onLabel : offLabel,
      })),
    };
  });
}
