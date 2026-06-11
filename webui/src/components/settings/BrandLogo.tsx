import { BLACKCAT_ICON_SRC, BLACKCAT_ICON_SRC_DARK } from "@/constants";
import { cn } from "@/lib/utils";

export function BlackcatBrandLogo({
  size = "sm",
  testId,
}: {
  size?: "sm" | "lg";
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className={cn(
        "grid shrink-0 place-items-center overflow-hidden border border-border/45 bg-background shadow-[inset_0_0_0_1px_rgba(0,0,0,0.025)]",
        size === "lg" ? "h-12 w-12 rounded-[16px]" : "h-9 w-9 rounded-[12px]",
      )}
      aria-hidden
    >
      <picture>
        <source
          media="(prefers-color-scheme: dark)"
          srcSet={BLACKCAT_ICON_SRC_DARK}
          type="image/png"
        />
        <source
          media="(prefers-color-scheme: light)"
          srcSet={BLACKCAT_ICON_SRC}
          type="image/png"
        />
        <img
          alt="Blackcat logo"
          className={cn("select-none object-contain", size === "lg" ? "h-10 w-10" : "h-7 w-7")}
          draggable={false}
        />
      </picture>
    </span>
  );
}