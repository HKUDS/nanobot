import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  INLINE_TOKEN_HIGHLIGHT_COLOR,
  InlineTokenHighlight,
} from "@/components/InlineTokenHighlight";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { logoFallbackUrls } from "@/lib/provider-brand";
import type {
  CliAppInfo,
  McpPresetInfo,
  SessionHandle,
  SessionMention,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type CliAppMentionSegment =
  | { kind: "text"; text: string }
  | { kind: "cli"; text: string; app: CliAppInfo };

export type CapabilityMentionSegment =
  | CliAppMentionSegment
  | { kind: "mcp"; text: string; preset: McpPresetInfo }
  | { kind: "handle"; text: string; handle: SessionHandle };

export type SessionReferenceSegment =
  | { kind: "text"; text: string }
  | { kind: "session"; text: string; mention: SessionMention };

export interface TokenSelection<T> {
  mention: T;
  start: number;
  end: number;
}

export type SessionHandleSelection = TokenSelection<SessionHandle>;
export type SessionMentionSelection = TokenSelection<SessionMention>;

const SESSION_HANDLE_COLOR_COUNT = 8;

export function sessionHandleColor(colorSlot: number): string {
  const slot = Number.isFinite(colorSlot)
    ? Math.abs(Math.trunc(colorSlot)) % SESSION_HANDLE_COLOR_COUNT
    : 0;
  return `var(--session-handle-${slot})`;
}

export function SessionHandleHighlight({
  handle,
  children,
  className,
  testId,
}: {
  handle: Pick<SessionHandle, "color_slot" | "name">;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <span
      className="inline border-b-2"
      style={{ borderBottomColor: sessionHandleColor(handle.color_slot) }}
    >
      <InlineTokenHighlight
        testId={testId}
        className={cn("text-foreground", className)}
      >
        {children}
      </InlineTokenHighlight>
    </span>
  );
}

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
  sessionHandles: SessionHandle[] = [],
  handleSelections?: SessionHandleSelection[],
): CapabilityMentionSegment[] {
  if (!value || (cliApps.length === 0 && mcpPresets.length === 0 && sessionHandles.length === 0)) {
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
  const handlesByName = new Map(
    sessionHandles.map((handle) => [handle.name.toLowerCase(), handle]),
  );
  const selectedSessionNames = new Set(
    (handleSelections ?? []).map((selection) => selection.mention.name.toLowerCase()),
  );
  if (cliAppsByName.size === 0 && mcpPresetsByName.size === 0 && handlesByName.size === 0) {
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
    const mentionStart = match.index + prefix.length;
    const mentionEnd = mentionStart + name.length + 1;
    const handle = handleSelections
      ? selectedSessionNames.has(key) ? handlesByName.get(key) : undefined
      : handlesByName.get(key);
    const app = handle ? null : cliAppsByName.get(key);
    const preset = handle || app ? null : mcpPresetsByName.get(key);
    if (!app && !preset && !handle) continue;

    if (mentionStart > cursor) {
      segments.push({ kind: "text", text: value.slice(cursor, mentionStart) });
    }
    if (app) {
      segments.push({ kind: "cli", text: value.slice(mentionStart, mentionEnd), app });
    } else if (preset) {
      segments.push({ kind: "mcp", text: value.slice(mentionStart, mentionEnd), preset });
    } else if (handle) {
      segments.push({ kind: "handle", text: value.slice(mentionStart, mentionEnd), handle });
    }
    cursor = mentionEnd;
  }
  if (cursor < value.length) segments.push({ kind: "text", text: value.slice(cursor) });
  return segments.length ? segments : [{ kind: "text", text: value }];
}

export function splitSessionReferenceSegments(
  value: string,
  sessionMentions: SessionMention[] = [],
  sessionSelections?: SessionMentionSelection[],
  allowLegacyAt = false,
): SessionReferenceSegment[] {
  if (!value || sessionMentions.length === 0) return value ? [{ kind: "text", text: value }] : [];
  const sessionsByName = new Map(
    sessionMentions.map((mention) => [mention.name.toLowerCase(), mention]),
  );
  const selectedSessionByStart = new Map(
    (sessionSelections ?? []).map((selection) => [selection.start, selection]),
  );
  const segments: SessionReferenceSegment[] = [];
  const referenceRe = allowLegacyAt
    ? /(^|[\s([{])([#@])([\p{L}\p{N}_-]+)(?=$|[^\p{L}\p{N}_-])/giu
    : /(^|[\s([{])(#)([\p{L}\p{N}_-]+)(?=$|[^\p{L}\p{N}_-])/giu;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = referenceRe.exec(value)) !== null) {
    const prefix = match[1] ?? "";
    const name = match[3] ?? "";
    const start = match.index + prefix.length;
    const end = start + name.length + 1;
    const selected = selectedSessionByStart.get(start);
    const mention = sessionSelections
      ? selected?.end === end && selected.mention.name.toLowerCase() === name.toLowerCase()
        ? selected.mention
        : undefined
      : sessionsByName.get(name.toLowerCase());
    if (!mention) continue;
    if (start > cursor) segments.push({ kind: "text", text: value.slice(cursor, start) });
    segments.push({ kind: "session", text: value.slice(start, end), mention });
    cursor = end;
  }
  if (cursor < value.length) segments.push({ kind: "text", text: value.slice(cursor) });
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
  return <SessionHandleToken handle={segment.handle} label={segment.text} variant={variant} />;
}

export function SessionHandleToken({
  handle,
  label,
  variant,
}: {
  handle: SessionHandle;
  label: string;
  variant: "composer" | "message";
}) {
  const testIdPrefix = variant === "composer" ? "composer" : "message";
  const color = sessionHandleColor(handle.color_slot);
  const token = (
    <SessionHandleHighlight
      handle={handle}
      testId={`${testIdPrefix}-handle-mention-${handle.name}`}
      className={variant === "composer" ? "font-normal" : undefined}
    >
      {label}
    </SessionHandleHighlight>
  );
  if (variant === "composer" || !handle.session_key) return token;
  return (
    <a
      href={`#/chat/${encodeURIComponent(handle.session_key)}`}
      className="rounded-sm underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      style={{ textDecorationColor: color }}
    >
      {token}
    </a>
  );
}

export function SessionReferenceToken({
  mention,
  label,
  variant,
}: {
  mention: SessionMention;
  label: string;
  variant: "composer" | "message";
}) {
  const testIdPrefix = variant === "composer" ? "composer" : "message";
  const token = (
    <InlineTokenHighlight
      testId={`${testIdPrefix}-session-reference-${mention.name}`}
      title={`Session: ${mention.title || mention.name}`}
      color={INLINE_TOKEN_HIGHLIGHT_COLOR}
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
      style={{ textDecorationColor: INLINE_TOKEN_HIGHLIGHT_COLOR }}
    >
      {token}
    </a>
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

export function McpPresetMentionToken({
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
