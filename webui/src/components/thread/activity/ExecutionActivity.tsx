import { useTranslation } from "react-i18next";

import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import { redactShellCommand } from "@/components/thread/activity/activity-text";
import { ToolRunIcon } from "@/components/icons/product-icons";
import type { ExecutionProgressEvent } from "@/lib/types";

export function ExecutionActivity({ event, active }: {
  event: ExecutionProgressEvent;
  active: boolean;
}) {
  const { t } = useTranslation();
  const key = event.state === "control_failed" ? `control_${event.operation}` : event.state;
  const detail = [
    event.command ? redactShellCommand(event.command) : null,
    event.state === "failed" && typeof event.exit_code === "number"
      ? t("message.agentActivity.execution.exitCode", { code: event.exit_code }) : null,
    event.output_incomplete ? t("message.agentActivity.execution.incomplete") : null,
  ].filter(Boolean).join(" · ");
  const failed = ["failed", "timed_out", "control_failed"].includes(event.state);
  return <ActivityStep
    icon={ToolRunIcon}
    label={t(`message.agentActivity.execution.${key}`)}
    detail={detail || undefined}
    active={active && event.state === "starting"}
    tone={failed ? "error" : "neutral"}
  />;
}
