import { SkeletonStatus } from "@/components/settings/shared/SkeletonStatus";
import { cn } from "@/lib/utils";

export function CatalogSkeleton({ label, layout }: {
  label: string;
  layout: "apps" | "channels" | "skills";
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
      {Array.from({ length: 6 }, (_, index) => (
        <div key={index} className={cn(
          "flex min-w-0 items-center gap-3",
          channels ? "settings-list-row py-2.5" : skills ? "px-2 py-3" : "px-3 py-3",
        )}>
          <div className={cn(block, "shrink-0", skills
            ? "h-1.5 w-1.5 rounded-full" : "h-9 w-9 rounded-[10px]")} />
          <div className="min-w-0 flex-1 py-1">
            <div className={cn(block, "h-3.5", index % 2 ? "w-1/2" : "w-2/3")} />
            {!channels ? <div className={cn(block, "mt-2 h-3 w-4/5 opacity-60")} /> : null}
          </div>
          <div className={cn("flex shrink-0 items-center justify-center", channels && "w-16")}>
            <div className={cn(block, channels ? "h-[22px] w-[38px] rounded-full"
              : skills ? "hidden h-3 w-20 sm:block" : "h-7 w-7 rounded-full")} />
          </div>
        </div>
      ))}
    </SkeletonStatus>
  );
}
