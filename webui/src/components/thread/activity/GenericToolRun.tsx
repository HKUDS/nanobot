import {
  AlertCircle,
  FileSearch,
  FolderOpen,
  ListTree,
  MemoryStick,
  Play,
  type LucideIcon,
} from "lucide-react";
import { useMemo } from "react";

import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import {
  describeGenericToolRun,
  type GenericToolRunItem,
  type GenericToolStatus,
  type ToolFamily,
} from "@/components/thread/activity/generic-tool-model";

interface GenericToolRunModel {
  status: GenericToolStatus;
  label: string;
  detail: string;
  aside: string;
  icon: LucideIcon;
}

export function GenericToolRun({ items }: { items: GenericToolRunItem[] }) {
  const model = useMemo(() => buildModel(items), [items]);
  const action = [model.label, model.detail].filter(Boolean).join(" ");
  const label = model.aside ? `${action} · ${model.aside}` : action;

  return (
    <ActivityStep
      icon={model.status === "error" ? AlertCircle : model.icon}
      active={model.status === "running"}
      tone={model.status === "error" ? "error" : model.status === "done" ? "success" : "active"}
      label={label}
    />
  );
}

function buildModel(items: GenericToolRunItem[]): GenericToolRunModel {
  const family = items[0]?.trace.family ?? "generic";
  const presentation = describeGenericToolRun(items);
  return {
    ...presentation,
    icon: activityIcon(family),
  };
}

function activityIcon(family: ToolFamily): LucideIcon {
  if (family === "content-search" || family === "file-search") return FileSearch;
  if (family === "list") return ListTree;
  if (family === "read") return FolderOpen;
  if (family === "memory") return MemoryStick;
  return Play;
}
