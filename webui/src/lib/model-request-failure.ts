import type { TFunction } from "i18next";

export interface ModelRequestFailureDetails {
  errorKind?: string;
  attempts?: number;
}

export function resolveModelRequestFailureCopy(
  details: ModelRequestFailureDetails,
  t: TFunction,
): { title: string; body: string } {
  let titleKey = "errors.modelRequestFailed.unknownTitle";
  if (details.errorKind === "billing") {
    titleKey = "errors.modelRequestFailed.billingTitle";
  } else if (details.errorKind === "connection") {
    titleKey = "errors.modelRequestFailed.connectionTitle";
  } else if (details.errorKind === "timeout") {
    titleKey = "errors.modelRequestFailed.timeoutTitle";
  } else if (details.errorKind === "rate_limit") {
    titleKey = "errors.modelRequestFailed.rateLimitTitle";
  } else if (details.errorKind === "server") {
    titleKey = "errors.modelRequestFailed.serverTitle";
  }
  const attempts = details.attempts;
  let bodyKey = "errors.modelRequestFailed.body";
  if (details.errorKind === "billing") {
    bodyKey = "errors.modelRequestFailed.billingBody";
  } else if (typeof attempts === "number" && Number.isInteger(attempts) && attempts > 0) {
    bodyKey = "errors.modelRequestFailed.bodyWithAttempt";
  }

  return {
    title: t(titleKey),
    body: t(bodyKey, { attempts }),
  };
}
