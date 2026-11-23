import type { TFunction } from "i18next";

const messages: Record<string, string> = {
  "Connection verified.": "connected",
  "Configuration is present, but full verification was not possible.": "unverified",
  "Required setup is missing.": "missing",
  "Configuration was checked and looks invalid.": "invalid",
  "This channel is not supported by the WebUI setup checker.": "unsupported",
  "Configured.": "present",
  "Required.": "required",
  "This channel can be checked from saved fields, but not fully verified in-browser.": "manual",
};

export function channelValidationMessage(message: string, t: TFunction): string {
  const key = messages[message];
  return key ? t(`settings.channels.validationMessages.${key}`, { defaultValue: message }) : message;
}
