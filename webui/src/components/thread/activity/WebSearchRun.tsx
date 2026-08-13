import { AlertCircle, Search } from "lucide-react";

import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import { WebActivityRow } from "@/components/thread/activity/WebActivityRow";
import {
  presentWebSearchAction,
  type WebSearchRunModel,
} from "@/components/thread/activity/web-search-model";

export function WebSearchRun({ run, turnActive }: { run: WebSearchRunModel; turnActive: boolean }) {
  const active = run.status === "running" && turnActive;
  const status = run.status === "running" && !turnActive ? "done" : run.status;
  const label = presentWebSearchAction(run.query, status, run.target);

  return (
    <>
      <ActivityStep
        icon={status === "error" ? AlertCircle : Search}
        active={active}
        tone={status === "error" ? "error" : status === "done" ? "success" : "active"}
        label={label}
      />
      {run.sources.map((source) => (
        <WebActivityRow
          key={source.href}
          title={source.title}
          href={source.href}
          host={source.host}
          displayUrl={source.displayUrl}
        />
      ))}
    </>
  );
}
