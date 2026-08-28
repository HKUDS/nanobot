import type { TFunction } from "i18next";

export interface ModelRequestFailureDetails {
  errorKind?: string;
  attempts?: number;
}

export function resolveModelRequestFailureCopy(
  details: ModelRequestFailureDetails,
  t: TFunction,
): { title: string; body: string } {
  const titleKey = details.errorKind === "connection"
    ? "errors.modelRequestFailed.connectionTitle"
    : details.errorKind === "timeout"
      ? "errors.modelRequestFailed.timeoutTitle"
      : details.errorKind === "rate_limit"
        ? "errors.modelRequestFailed.rateLimitTitle"
        : details.errorKind === "server"
          ? "errors.modelRequestFailed.serverTitle"
          : "errors.modelRequestFailed.unknownTitle";
  const attempts = details.attempts;

  return {
    title: t(titleKey),
    body: typeof attempts === "number" && Number.isInteger(attempts) && attempts > 0
      ? t("errors.modelRequestFailed.bodyWithAttempt", { attempts })
      : t("errors.modelRequestFailed.body"),
  };
}
