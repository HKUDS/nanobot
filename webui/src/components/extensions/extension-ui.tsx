import type { ReactNode } from "react";
import { Box, Loader2, PackageOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ExtensionInfo, ExtensionMarketPackage } from "@/lib/types";
import { cn } from "@/lib/utils";

export type ExtensionTab = "installed" | "discover" | "builtin";
export type ExtensionEcosystem = "all" | "nanobot" | "pi" | "openclaw";

export function ExtensionMark({
  runtime,
  large = false,
}: {
  runtime: string;
  large?: boolean;
}) {
  const Icon = runtime === "pi" || runtime === "openclaw" ? Box : PackageOpen;
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-[13px] bg-muted/65 text-muted-foreground",
        large ? "h-12 w-12" : "h-10 w-10",
      )}
    >
      <Icon className={large ? "h-5 w-5" : "h-4 w-4"} strokeWidth={1.8} aria-hidden />
    </div>
  );
}

export function RuntimeBadge({ runtime }: { runtime: string }) {
  return (
    <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
      {runtime}
    </span>
  );
}

export function StatusBadge({ extension }: { extension: ExtensionInfo }) {
  const { t } = useTranslation();
  const [key, tone] = extension.active
    ? ["active", "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"]
    : !extension.enabled
      ? ["disabled", "bg-muted text-muted-foreground"]
      : !extension.trusted
        ? ["untrusted", "bg-amber-500/10 text-amber-700 dark:text-amber-300"]
        : ["inactive", "bg-muted text-muted-foreground"];
  return (
    <span className={cn("shrink-0 rounded-full px-2 py-1 text-[11px] font-medium", tone)}>
      {t(`extensions.status.${key}`)}
    </span>
  );
}

export function DetailSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-2 text-[12px] font-medium text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

export function NamedItems({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ name: string; meta: string }>;
}) {
  const { t } = useTranslation();
  return (
    <DetailSection title={title}>
      {rows.length ? (
        <div className="divide-y divide-border/35 overflow-hidden rounded-[14px] bg-muted/30">
          {rows.map((row, index) => (
            <div key={`${row.meta}:${row.name}:${index}`} className="flex gap-3 px-3 py-2.5">
              <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">
                {row.name}
              </span>
              <span className="shrink-0 text-[11px] text-muted-foreground">{row.meta}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">{t("extensions.none")}</p>
      )}
    </DetailSection>
  );
}

export function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[14px] bg-muted/35 px-3 py-2.5">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 truncate text-[13px] text-foreground">{value}</dd>
    </div>
  );
}

export function DetailPill({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full bg-muted px-2 py-1 text-[11px] text-muted-foreground">
      {children}
    </span>
  );
}

export function LoadingState() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-48 items-center justify-center gap-2 text-[13px] text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {t("extensions.loading")}
    </div>
  );
}

export function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center text-[13px] text-muted-foreground">
      {label}
    </div>
  );
}

export function filterExtensions(
  items: ExtensionInfo[],
  query: string,
): ExtensionInfo[] {
  const term = query.trim().toLowerCase();
  if (!term) return items;
  return items.filter((item) =>
    [item.name, item.id, item.description, item.runtime].some((value) =>
      value.toLowerCase().includes(term),
    ),
  );
}

export function filterPackages(
  items: ExtensionMarketPackage[],
  query: string,
): ExtensionMarketPackage[] {
  const term = query.trim().toLowerCase();
  if (!term) return items;
  return items.filter((item) =>
    [item.name, item.description, item.publisher].some((value) =>
      value.toLowerCase().includes(term),
    ),
  );
}
