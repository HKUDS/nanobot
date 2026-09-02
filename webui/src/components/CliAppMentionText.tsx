import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  INLINE_TOKEN_HIGHLIGHT_COLOR,
  InlineTokenHighlight,
} from "@/components/InlineTokenHighlight";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { logoFallbackUrls } from "@/lib/provider-brand";
import { sessionHandleColor } from "@/lib/session-handle";
import type { CliAppInfo, McpPresetInfo, SessionMention } from "@/lib/types";
import { cn } from "@/lib/utils";

type CliAppMentionSegment =
  | { kind: "text"; text: string }
  | { kind: "cli"; text: string; app: CliAppInfo };

export type CapabilityMentionSegment =
  | CliAppMentionSegment
  | { kind: "mcp"; text: string; preset: McpPresetInfo }
  | { kind: "session"; text: string; mention: SessionMention };

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
export function mcpPresetInitials(preset: Pick<McpPresetInfo, "name" | "display_name">): string {
  const value = preset.display_name || preset.name;
  return (
    value
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || preset.name.slice(0, 2).toUpperCase()
  );
}
export function splitCapabilityMentionSegments(
  value: string,
  cliApps: CliAppInfo[],
  mcpPresets: McpPresetInfo[] = [],
  sessionMentions: SessionMention[] = [],
): CapabilityMentionSegment[] {
  if (!value || (cliApps.length === 0 && mcpPresets.length === 0 && sessionMentions.length === 0)) {
    return value ? [{ kind: "text", text: value }] : [];
  }
  const cliAppsByName = new Map(
    cliApps
      .filter((app) => app.installed)
      .map((app) => [app.name.toLowerCase(), app]),
  );
  const mcpPresetsByName = new Map(
    mcpPresets
      .filter((preset) => preset.installed && preset.configured)
      .map((preset) => [preset.name.toLowerCase(), preset]),
  );
  const sessionsByName = new Map(
    sessionMentions.map((mention) => [mention.name.toLowerCase(), mention]),
  );
  if (cliAppsByName.size === 0 && mcpPresetsByName.size === 0 && sessionsByName.size === 0) {
    return [{ kind: "text", text: value }];
  }

  const segments: CapabilityMentionSegment[] = [];
  const mentionRe = /(^|[\s([{])@([\p{L}\p{N}_-]+)(?=$|[^\p{L}\p{N}_-])/giu;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = mentionRe.exec(value)) !== null) {
    const prefix = match[1] ?? "";
    const name = match[2] ?? "";
    const key = name.toLowerCase();
    const session = sessionsByName.get(key);
    const app = session ? null : cliAppsByName.get(key);
    const preset = session || app ? null : mcpPresetsByName.get(key);
    if (!app && !preset && !session) continue;

    const mentionStart = match.index + prefix.length;
    const mentionEnd = mentionStart + name.length + 1;
    if (mentionStart > cursor) {
      segments.push({ kind: "text", text: value.slice(cursor, mentionStart) });
    }
    if (app) {
      segments.push({ kind: "cli", text: value.slice(mentionStart, mentionEnd), app });
    } else if (preset) {
      segments.push({ kind: "mcp", text: value.slice(mentionStart, mentionEnd), preset });
    } else if (session) {
      segments.push({
        kind: "session",
        text: value.slice(mentionStart, mentionEnd),
        mention: session,
      });
    }
    cursor = mentionEnd;
  }
  if (cursor < value.length) {
    segments.push({ kind: "text", text: value.slice(cursor) });
  }
  return segments.length ? segments : [{ kind: "text", text: value }];
}

export function CapabilityMentionToken({
  segment,
  variant,
  isHero = false,
}: {
  segment: Exclude<CapabilityMentionSegment, { kind: "text" }>;
  variant: "composer" | "message";
  isHero?: boolean;
}) {
  if (segment.kind === "cli") {
    return (
      <CliAppMentionToken
        app={segment.app}
        label={segment.text}
        variant={variant}
        isHero={isHero}
      />
    );
  }
  if (segment.kind === "mcp") {
    return (
      <McpPresetMentionToken
        preset={segment.preset}
        label={segment.text}
        variant={variant}
        isHero={isHero}
      />
    );
  }
  return <SessionMentionToken mention={segment.mention} label={segment.text} variant={variant} />;
}

function SessionMentionToken({
  mention,
  label,
  variant,
}: {
  mention: SessionMention;
  label: string;
  variant: "composer" | "message";
}) {
  const testIdPrefix = variant === "composer" ? "composer" : "message";
  const color = mention.id
    ? sessionHandleColor(mention.id)
    : INLINE_TOKEN_HIGHLIGHT_COLOR;
  const token = (
    <InlineTokenHighlight
      testId={`${testIdPrefix}-session-mention-${mention.name}`}
      title={`Session: ${mention.title || mention.name}`}
      color={color}
      className={variant === "composer" ? "font-normal" : undefined}
    >
      {label}
    </InlineTokenHighlight>
  );
  if (variant === "composer") return token;
  return (
    <a
      href={`#/chat/${encodeURIComponent(mention.session_key)}`}
      className="rounded-sm underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      style={{ textDecorationColor: color }}
    >
      {token}
    </a>
  );
}

function CliAppMentionToken({
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
  const { t } = useTranslation();
  const color = app.brand_color || INLINE_TOKEN_HIGHLIGHT_COLOR;
  const mentionName = label.startsWith("@") ? label.slice(1) : label;
  const logoUrls = useMemo(() => logoFallbackUrls(app.logo_url), [app.logo_url]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const showLogo = Boolean(logoUrl);
  const testIdPrefix = variant === "composer" ? "composer" : "message";

  return (
    <InlineTokenHighlight
      testId={`${testIdPrefix}-cli-mention-${app.name}`}
      title={t("thread.composer.mentions.cliTitle", { name: app.display_name || app.name })}
      color={color}
      className={variant === "composer" ? "font-normal" : undefined}
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
              "absolute left-1/2 top-1/2 grid place-items-center overflow-hidden rounded-mark",
              "-translate-x-1/2 -translate-y-1/2",
              isHero ? "h-[0.74em] w-[0.74em]" : "h-[0.72em] w-[0.72em]",
            )}
          >
            <img
              src={logoUrl ?? ""}
              alt=""
              className="h-full w-full object-contain"
              decoding="async"
              loading="lazy"
              onLoad={onLogoLoad}
              onError={onLogoError}
            />
          </span>
        ) : null}
      </span>
      {mentionName}
    </InlineTokenHighlight>
  );
}

function McpPresetMentionToken({
  preset,
  label,
  variant,
  isHero = false,
}: {
  preset: McpPresetInfo;
  label: string;
  variant: "composer" | "message";
  isHero?: boolean;
}) {
  const { t } = useTranslation();
  const color = preset.brand_color || INLINE_TOKEN_HIGHLIGHT_COLOR;
  const mentionName = label.startsWith("@") ? label.slice(1) : label;
  const logoUrls = useMemo(() => logoFallbackUrls(preset.logo_url), [preset.logo_url]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const showLogo = Boolean(logoUrl);
  const testIdPrefix = variant === "composer" ? "composer" : "message";

  return (
    <InlineTokenHighlight
      testId={`${testIdPrefix}-mcp-mention-${preset.name}`}
      title={t("thread.composer.mentions.mcpTitle", { name: preset.display_name || preset.name })}
      color={color}
      className={variant === "composer" ? "font-normal" : undefined}
    >
      <span
        className={cn("relative inline-block", showLogo && "text-transparent")}
        style={{ lineHeight: "inherit" }}
      >
        @
        {showLogo ? (
          <span
            data-testid={`${testIdPrefix}-mcp-mention-logo-${preset.name}`}
            className={cn(
              "absolute left-1/2 top-1/2 grid place-items-center overflow-hidden rounded-mark",
              "-translate-x-1/2 -translate-y-1/2",
              isHero ? "h-[0.74em] w-[0.74em]" : "h-[0.72em] w-[0.72em]",
            )}
          >
            <img
              src={logoUrl ?? ""}
              alt=""
              className="h-full w-full object-contain"
              decoding="async"
              loading="lazy"
              onLoad={onLogoLoad}
              onError={onLogoError}
            />
          </span>
        ) : null}
      </span>
      {mentionName}
    </InlineTokenHighlight>
  );
}
