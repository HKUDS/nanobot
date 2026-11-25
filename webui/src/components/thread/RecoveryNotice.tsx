import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { PersistentToast } from "@/components/ui/toast";
import { emptyFinalMessageKey, isImageRequestFailure, resolveModelRequestFailureCopy } from "@/lib/model-request-failure";
import type { RecoveryState } from "@/lib/types";

interface RecoveryNoticeProps {
  state: RecoveryState;
  onContinue: () => Promise<void>;
  onDismiss: () => Promise<void>;
  onOpenSettings?: () => void;
  onInspectImagePreset?: () => void;
  imageInputBlocked?: boolean;
}

export function RecoveryNotice(props: RecoveryNoticeProps) {
  const { status, recovery_id } = props.state;
  // A resuming or resolved task is no longer a decision. If it is interrupted
  // again, even with the same ID, start with a fresh pair of actions.
  if (status !== "awaiting_user" && status !== "failed") return null;
  return <RecoveryDecision key={`${recovery_id}:${status}`} {...props} />;
}

function RecoveryDecision({ state, onContinue, onDismiss, onOpenSettings, onInspectImagePreset, imageInputBlocked }: RecoveryNoticeProps) {
  const { t } = useTranslation();
  const [submitted, setSubmitted] = useState(false);
  const [actionFailed, setActionFailed] = useState(false);
  if (submitted) return null;

  const emptyFinalKey = state.reason === "model_request_failed" && emptyFinalMessageKey(state.failure_error_kind);
  const modelFailure = state.reason === "model_request_failed" && !emptyFinalKey
    ? resolveModelRequestFailureCopy({ errorKind: state.failure_error_kind }, t) : null;
  const imageFailure = modelFailure !== null && isImageRequestFailure(state.failure_error_kind);
  const openSettings = modelFailure && (imageFailure ? onInspectImagePreset : onOpenSettings);
  const canContinue = state.can_continue !== false && !(state.failure_error_kind === "unsupported_image" && imageInputBlocked);
  const reasonKey = state.reason === "restart_requires_confirmation" ? "recovery.restart"
    : state.reason === "tool_state_unknown" ? "recovery.uncertainTool"
    : state.reason === "loop_guard" ? "recovery.interruptedAgain"
    : state.status === "failed" || state.reason === "checkpoint_invalid" ? "recovery.failed" : "recovery.interrupted";
  const title = emptyFinalKey ? t(emptyFinalKey) : modelFailure?.title ?? t(reasonKey);
  const detail = state.can_continue === false || state.status === "failed" ? t("recovery.failedHelp")
    : modelFailure && !imageFailure && state.reply_preserved ? t("recovery.replyPreserved")
    : emptyFinalKey ? null : modelFailure?.body ?? t("recovery.review");

  const run = (operation: () => Promise<void>) => {
    setSubmitted(true);
    void operation().catch(() => {
      setSubmitted(false);
      setActionFailed(true);
    });
  };
  return <PersistentToast tone="error" message={actionFailed ? t("recovery.actionFailed") : title}
    action={canContinue ? { label: t("recovery.continue"), run: () => run(onContinue) } : undefined}
    secondaryAction={{ label: t("recovery.dismiss"), run: () => run(onDismiss) }}
    details={detail || openSettings || actionFailed ? { label: t("recovery.details"), content: <div className="space-y-2 p-3 text-sm">
      {actionFailed && <p>{title}</p>}
      {detail && <p>{detail}</p>}
      {openSettings && <Button variant="link" size="sm" className="h-auto p-0" onClick={openSettings}>
        {t(imageFailure ? "settings.models.viewPreset" : "thread.composer.reauthSettings")}
      </Button>}
    </div> } : undefined} />;
}
