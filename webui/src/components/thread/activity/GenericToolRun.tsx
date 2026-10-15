import {
  DelegationIcon,
  TaskInspectIcon,
  TaskMessageIcon,
  StopIcon,
  ImageGenerationIcon,
  ConversationIcon,
  AutomationsIcon,
  GoalIcon,
  FileReadIcon,
  FileListIcon,
  MemoryIcon,
  ToolRunIcon,
} from "@/components/icons/product-icons";
import { AlertCircle, FileSearch, type LucideIcon } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import {
  describeGenericToolRun,
  type GenericToolRunItem,
  type GenericToolStatus,
  type ToolFamily,
} from "@/components/thread/activity/generic-tool-model";
import { formatActivityTarget } from "@/components/thread/activity/activity-text";

interface GenericToolRunModel {
  status: GenericToolStatus;
  label: string;
  detail: string;
  aside: string;
  icon: LucideIcon;
}

export function GenericToolRun({ items }: { items: GenericToolRunItem[] }) {
  const { t } = useTranslation();
  const model = useMemo(() => buildModel(items, t), [items, t]);
  const action = formatActivityTarget(t, model.label, model.detail);

  return (
    <ActivityStep
      icon={model.status === "error" ? AlertCircle : model.icon}
      active={model.status === "running"}
      tone={model.status === "error" ? "error" : model.status === "done" ? "success" : "active"}
      label={action}
      detail={model.aside}
    />
  );
}

function buildModel(items: GenericToolRunItem[], t: ReturnType<typeof useTranslation>["t"]): GenericToolRunModel {
  const family = items[0]?.trace.family ?? "generic";
  const presentation = describeGenericToolRun(items, t);
  return {
    ...presentation,
    icon: activityIcon(family, items[0]),
  };
}

function activityIcon(family: ToolFamily, item: GenericToolRunItem | undefined): LucideIcon {
  const name = item?.trace.name;
  const action = item?.trace.fields.find((field) => field.key === "action")?.value.toLowerCase();
  if (name === "spawn") return DelegationIcon;
  if (name === "subagent") {
    if (action === "check") return TaskInspectIcon;
    if (action === "send") return TaskMessageIcon;
    if (action === "cancel") return StopIcon;
    return DelegationIcon;
  }
  if (name === "generate_image") return ImageGenerationIcon;
  if (name === "message") return ConversationIcon;
  if (name === "cron") return AutomationsIcon;
  if (name === "create_goal") return GoalIcon;
  if (family === "content-search" || family === "file-search") return FileSearch;
  if (family === "list") return FileListIcon;
  if (family === "read") return FileReadIcon;
  if (family === "memory") return MemoryIcon;
  return ToolRunIcon;
}
