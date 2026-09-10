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
  "WhatsApp QR request timed out. Check your network or proxy and retry.": "qrTimeout",
  "NapCat connection": "napcatConnection",
  "WhatsApp session database is still in use. Close any other nanobot process using WhatsApp, then try again.": "whatsappSessionBusy"
};

export function channelValidationMessage(message: string, t: TFunction): string {
  const key = messages[message]
    ?? (/^(Could not connect to NapCat at |Could not use this NapCat connection:)/.test(message)
      ? "napcatUnavailable"
      : /^WhatsApp session database could not be applied:/.test(message)
        ? "whatsappSessionBusy"
        : undefined);
  return key ? t(`settings.channels.validationMessages.${key}`, { defaultValue: message }) : message;
}
