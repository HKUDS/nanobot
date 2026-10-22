import { SkeletonStatus } from "@/components/settings/shared/SkeletonStatus";
import { cn } from "@/lib/utils";

export function CatalogSkeleton({ label, layout, appActionLabel }: {
  label: string;
  layout: "apps" | "channels" | "skills";
  appActionLabel?: string;
}) {
  const channels = layout === "channels";
  const skills = layout === "skills";
  const block = "rounded bg-muted-foreground/20";

  return (
    <SkeletonStatus
      label={label}
      className={cn(
        skills ? "space-y-1 px-3 pb-3 pt-2 sm:px-4" : "grid grid-cols-1 gap-y-1",
        layout === "apps" && "gap-x-10 py-3 xl:grid-cols-2",
        channels && "gap-x-4 min-[640px]:grid-cols-2",
      )}
    >
      {skills ? (
        <div className="flex h-8 items-center gap-2 px-2 py-1.5">
          <div className={cn(block, "h-3 w-16")} />
          <div className={cn(block, "h-3 w-3 opacity-60")} />
        </div>
      ) : null}
      {Array.from({ length: 6 }, (_, index) => (
        <div key={index} className={cn(
          "flex min-w-0 items-center gap-3",
          channels ? "settings-list-row py-2.5" : skills ? "px-2 py-3" : "px-3 py-3",
          appActionLabel && "flex-wrap gap-x-3 gap-y-2",
        )}>
          <div className={cn(block, "shrink-0", skills
            ? "h-1.5 w-1.5 rounded-full" : channels ? "h-8 w-8 rounded-[9px]" : "h-9 w-9 rounded-[10px]")} />
          <div className={cn("min-w-0 flex-1", appActionLabel && "min-w-[8rem] flex-[1_1_8rem]")}>
            <div className="flex h-5 items-center">
              <div className={cn(block, "h-3.5", index % 2 ? "w-1/2" : "w-2/3")} />
            </div>
            {!channels ? <div className="mt-0.5 flex h-5 items-center">
              <div className={cn(block, "h-3 w-4/5 opacity-60")} />
            </div> : null}
          </div>
          <div className={cn("flex shrink-0 items-center justify-center",
            channels && "w-16", skills && "hidden h-[16.5px] w-[92px] justify-end sm:flex",
            appActionLabel && "ml-auto")}>
            {appActionLabel ? <div className={cn(block, "flex h-8 items-center gap-1.5 rounded-full px-3 text-[12px] font-semibold")}>
              <span className="h-4 w-4 shrink-0" />
              <span className="invisible">{appActionLabel}</span>
            </div> : <div className={cn(block, channels ? "h-5 w-[38px] rounded-full"
              : skills ? "h-3 w-20" : "h-9 w-9 rounded-full")} />}
          </div>
        </div>
      ))}
    </SkeletonStatus>
  );
}
