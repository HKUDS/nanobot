import { useState } from "react";

import type { CliAppInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export type CliAppMentionSegment =
  | { kind: "text"; text: string }
  | { kind: "cli"; text: string; app: CliAppInfo };

export function cliAppInitials(app: CliAppInfo): string {
  const value = app.display_name || app.name;
  return (
    value
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || app.name.slice(0, 2).toUpperCase()
  );
}

export function splitCliAppMentionSegments(
  value: string,
  cliApps: CliAppInfo[],
): CliAppMentionSegment[] {
  if (!value || cliApps.length === 0) return value ? [{ kind: "text", text: value }] : [];
  const appsByName = new Map(
    cliApps
      .filter((app) => app.installed)
      .map((app) => [app.name.toLowerCase(), app]),
  );
  if (appsByName.size === 0) return [{ kind: "text", text: value }];

  const segments: CliAppMentionSegment[] = [];
  const mentionRe = /(^|[\s([{])@([a-z0-9_-]+)\b/gi;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = mentionRe.exec(value)) !== null) {
    const prefix = match[1] ?? "";
    const name = match[2] ?? "";
    const app = appsByName.get(name.toLowerCase());
    if (!app) continue;

    const mentionStart = match.index + prefix.length;
    const mentionEnd = mentionStart + name.length + 1;
    if (mentionStart > cursor) {
      segments.push({ kind: "text", text: value.slice(cursor, mentionStart) });
    }
    segments.push({ kind: "cli", text: value.slice(mentionStart, mentionEnd), app });
    cursor = mentionEnd;
  }
  if (cursor < value.length) {
    segments.push({ kind: "text", text: value.slice(cursor) });
  }
  return segments.length ? segments : [{ kind: "text", text: value }];
}

export function CliAppMentionText({
  text,
  cliApps,
}: {
  text: string;
  cliApps: CliAppInfo[];
}) {
  const segments = splitCliAppMentionSegments(text, cliApps);
  if (!segments.some((segment) => segment.kind === "cli")) return <>{text}</>;
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <span key={`text-${index}`}>{segment.text}</span>;
        }
        return (
          <CliAppMentionToken
            key={`cli-${segment.app.name}-${index}`}
            app={segment.app}
            label={segment.text}
            variant="message"
          />
        );
      })}
    </>
  );
}

export function CliAppMentionToken({
  app,
  label,
  variant,
  isHero = false,
}: {
  app: CliAppInfo;
  label: string;
  variant: "composer" | "message";
  isHero?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const color = app.brand_color || "hsl(var(--primary))";
  const mentionName = label.startsWith("@") ? label.slice(1) : label;
  const showLogo = Boolean(app.logo_url) && !failed;
  const testIdPrefix = variant === "composer" ? "composer" : "message";

  return (
    <span
      data-testid={`${testIdPrefix}-cli-mention-${app.name}`}
      className="relative inline transition-[color,text-shadow] duration-150"
      style={{
        color,
        textShadow: `0 0 10px ${alphaColor(color, 24)}`,
      }}
    >
      <span
        className={cn("relative inline-block", showLogo && "text-transparent")}
        style={{ lineHeight: "inherit" }}
      >
        @
        {showLogo ? (
          <span
            data-testid={`${testIdPrefix}-cli-mention-logo-${app.name}`}
            className={cn(
              "absolute left-1/2 top-1/2 grid place-items-center overflow-hidden rounded-[3px]",
              "-translate-x-1/2 -translate-y-1/2",
              isHero ? "h-[0.74em] w-[0.74em]" : "h-[0.72em] w-[0.72em]",
            )}
          >
            <img
              src={app.logo_url ?? ""}
              alt=""
              className="h-full w-full object-contain"
              onError={() => setFailed(true)}
            />
          </span>
        ) : null}
      </span>
      {mentionName}
    </span>
  );
}

function alphaColor(color: string, percent: number): string {
  if (/^#[0-9a-f]{6}$/i.test(color)) {
    const alpha = Math.round((percent / 100) * 255)
      .toString(16)
      .padStart(2, "0");
    return `${color}${alpha}`;
  }
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`;
}
