import { useEffect, useMemo, useRef, useState } from "react";
import { ShieldCheck, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelUiPresentation } from "@/channel-plugins/registry";
import { Button } from "@/components/ui/button";
import { floatingSurfaceElevationClassName } from "@/components/ui/floating-surface";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { logoFallbackUrls } from "@/lib/provider-brand";
import type { PairingRequestInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export function PairingCodePopup({
  requests,
  total,
  busyCode,
  error,
  onApprove,
  onDismiss,
}: {
  requests: PairingRequestInfo[];
  total: number;
  busyCode: string | null;
  error: string | null;
  onApprove: (code: string) => void;
  onDismiss: (request: PairingRequestInfo) => void;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const attemptedCode = useRef<string | null>(null);
  const normalizedCode = normalizePairingCode(value);
  const matchedRequest = useMemo(
    () => requests.find((request) => request.code === normalizedCode) ?? null,
    [normalizedCode, requests],
  );
  // Keep delivered and legacy requests usable even when another bot cannot reply.
  const firstRequest = requests.find((request) => (
    !request.delivery_status || request.delivery_status === "sent"
  )) ?? requests[0] ?? null;
  const displayRequest = matchedRequest ?? firstRequest;
  const deliveryBlocked = displayRequest?.delivery_status === "failed"
    || displayRequest?.delivery_status === "sending";
  const expires = formatPairingExpiry(displayRequest?.expires_in_seconds);
  const isCompleteCode = normalizedCode.length === 9;
  const showNoMatch = isCompleteCode && !matchedRequest && !busyCode;

  useEffect(() => {
    if (!matchedRequest || busyCode || attemptedCode.current === matchedRequest.code) return;
    attemptedCode.current = matchedRequest.code;
    onApprove(matchedRequest.code);
  }, [busyCode, matchedRequest, onApprove]);

  useEffect(() => {
    if (!requests.length) {
      setValue("");
      attemptedCode.current = null;
    }
  }, [requests.length]);

  if (!firstRequest) return null;

  const codeInput = (
    <PairingCodeSlots
      value={value}
      disabled={Boolean(busyCode)}
      matched={Boolean(matchedRequest)}
      invalid={showNoMatch}
      ariaLabel={t("app.pairing.code", { defaultValue: "Pairing code" })}
      onChange={(next) => {
        attemptedCode.current = null;
        setValue(formatPairingCodeInput(next));
      }}
    />
  );

  return (
    <div
      role="dialog"
      aria-live="polite"
      aria-label={t("app.pairing.title", { defaultValue: "Pair a chat user" })}
      className={cn(
        "fixed right-4 top-[calc(0.75rem+env(safe-area-inset-top))] z-[70]",
        "w-[min(calc(100vw-2rem),24rem)] rounded-modal",
        floatingSurfaceElevationClassName,
        "p-4",
        "animate-in fade-in-0 slide-in-from-top-2 duration-200",
      )}
    >
      <div className="flex items-start gap-3">
        <PairingChannelBadge channel={displayRequest.channel} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[15px] font-semibold tracking-[-0.01em]">
                {t("app.pairing.title", { defaultValue: "Pair a chat user" })}
              </p>
              <p
                className="mt-1 text-pretty text-[13px] leading-5 text-muted-foreground"
                role={displayRequest.delivery_status === "failed" ? "alert" : undefined}
              >
                {displayRequest.delivery_status === "failed" ? t("app.pairing.deliveryFailed", {
                  defaultValue: "Couldn't send the pairing code. Check this bot's send-message permissions and gateway logs, then send it another private message to retry.",
                }) : displayRequest.delivery_status === "sending" ? t("app.pairing.deliverySending", {
                  defaultValue: "Sending a pairing code to your chat. If it doesn't arrive, send the bot another private message to retry.",
                }) : t("app.pairing.description", {
                  defaultValue: "Enter the pairing code shown in the chat.",
                })}
              </p>
            </div>
            <button
              type="button"
              aria-label={t("common.close", { defaultValue: "Close" })}
              onClick={() => onDismiss(displayRequest)}
              className="rounded-full p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>

          {deliveryBlocked ? (
            <details className="mt-3 text-[12.5px] text-muted-foreground">
              <summary className="cursor-pointer">
                {t("app.pairing.haveCode", { defaultValue: "Already received a code?" })}
              </summary>
              {codeInput}
            </details>
          ) : (
            <>
              <label className="mt-4 block text-[12.5px] font-medium text-foreground">
                {t("app.pairing.code", { defaultValue: "Pairing code" })}
              </label>
              {codeInput}
            </>
          )}

          {!deliveryBlocked || total > 1 ? (
            <div className="mt-3 flex items-center justify-between gap-3 text-[12.5px] text-muted-foreground">
              <span>
                {matchedRequest && busyCode === matchedRequest.code
                  ? t("app.pairing.matched", {
                      defaultValue: "Matched {{channel}}. Connecting...",
                      channel: channelLabel(matchedRequest.channel),
                    })
                  : deliveryBlocked ? null : t("app.pairing.expiresInline", {
                      defaultValue: "Code expires {{expires}}.",
                      expires,
                    })}
              </span>
              {total > 1 ? (
                <span className="shrink-0">
                  {t("app.pairing.queueCount", {
                    defaultValue: "{{count}} pending",
                    count: total,
                  })}
                </span>
              ) : null}
            </div>
          ) : null}

          {showNoMatch ? (
            <p className="mt-2 text-[12px] leading-5 text-destructive">
              {t("app.pairing.noMatch", {
                defaultValue: "No pending request matches this code.",
              })}
            </p>
          ) : null}

          {error ? (
            <div className="mt-2 space-y-2">
              <p role="alert" className="text-[12px] leading-5 text-destructive">{error}</p>
              {matchedRequest ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={Boolean(busyCode)}
                  onClick={() => onApprove(matchedRequest.code)}
                >
                  {t("common.retry", { defaultValue: "Retry" })}
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function PairingChannelBadge({ channel }: { channel: string }) {
  const presentation = pairingChannelPresentation(channel);
  const initials = presentation.initials;
  const color = presentation.color;
  const logoUrls = useMemo(
    () => logoFallbackUrls(presentation?.logoUrl),
    [presentation?.logoUrl],
  );
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);

  return (
    <div
      className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-2xl border bg-background shadow-sm"
      style={{
        borderColor: `${color}30`,
        boxShadow: `inset 0 0 0 1px ${color}14, 0 1px 2px rgba(15,23,42,0.06)`,
      }}
      aria-hidden
    >
      {logoUrl ? (
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-6 w-6 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      ) : presentation ? (
        <span className="text-[11px] font-bold tracking-[-0.02em]" style={{ color }}>
          {initials}
        </span>
      ) : (
        <ShieldCheck className="h-5 w-5" style={{ color }} />
      )}
    </div>
  );
}

function PairingCodeSlots({
  value,
  disabled,
  matched,
  invalid,
  ariaLabel,
  onChange,
}: {
  value: string;
  disabled: boolean;
  matched: boolean;
  invalid: boolean;
  ariaLabel: string;
  onChange: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(false);
  const compact = compactPairingCode(value);
  const activeIndex = Math.min(compact.length, 7);
  const slots = Array.from({ length: 8 }, (_, index) => compact[index] ?? "");
  const renderSlot = (char: string, index: number) => {
    const highlighted = focused && index === activeIndex && !matched && !invalid;
    return (
      <div
        key={index}
        className={cn(
          "grid h-10 w-7 place-items-center rounded-xl border",
          "bg-background/80 font-mono text-[16px] font-semibold uppercase",
          "text-foreground shadow-[0_1px_1px_rgba(15,23,42,0.04)] transition",
          matched
            ? "border-emerald-500/45 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            : invalid
              ? "border-destructive/55 bg-destructive/5 text-destructive"
              : highlighted
                ? "border-foreground/30 bg-background text-foreground"
                : char
                  ? "border-border/80 bg-background text-foreground"
                  : "border-border/55 bg-muted/35 text-muted-foreground",
        )}
      >
        {char || " "}
      </div>
    );
  };

  return (
    <div
      className={cn(
        "relative mt-2 rounded-2xl border border-transparent p-1",
        "transition duration-150",
        focused && !disabled ? "border-ring/20 bg-muted/35" : "bg-transparent",
      )}
      onClick={() => inputRef.current?.focus()}
    >
      <input
        ref={inputRef}
        value={value}
        aria-label={ariaLabel}
        inputMode="text"
        autoCapitalize="characters"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        maxLength={9}
        disabled={disabled}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(event) => onChange(event.target.value)}
        className="absolute inset-0 z-10 h-full w-full cursor-text opacity-0 disabled:cursor-default"
      />
      <div className="pointer-events-none flex items-center gap-1.5">
        {slots.slice(0, 4).map((char, index) => renderSlot(char, index))}
        <div className="mx-0.5 h-px w-2.5 rounded-full bg-muted-foreground/35" />
        {slots.slice(4).map((char, index) => renderSlot(char, index + 4))}
      </div>
    </div>
  );
}

function compactPairingCode(raw: string): string {
  return raw.replace(/[^a-zA-Z0-9]/g, "").slice(0, 8).toUpperCase();
}

function formatPairingCodeInput(raw: string): string {
  const compact = compactPairingCode(raw);
  if (compact.length <= 4) return compact;
  return `${compact.slice(0, 4)}-${compact.slice(4)}`;
}

function normalizePairingCode(raw: string): string {
  return formatPairingCodeInput(raw);
}

function pairingChannelKey(channel: string): string {
  const raw = channel.trim().toLowerCase();
  if (!raw) return "";
  return raw.split(/[.:]/)[0] ?? raw;
}

function channelLabel(channel: string): string {
  return pairingChannelPresentation(channel).label;
}

function pairingChannelPresentation(channel: string) {
  const key = pairingChannelKey(channel);
  const plugin = channelUiPresentation(key);
  return {
    label: plugin?.displayName ?? channel,
    initials: plugin?.initials ?? channel.slice(0, 2).toUpperCase(),
    color: plugin?.color ?? "#10B981",
    logoUrl: plugin?.logoUrl,
  };
}

function formatPairingExpiry(seconds: number | null | undefined): string {
  if (seconds == null) return "soon";
  if (seconds <= 0) return "expired";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.ceil(seconds / 60)} min`;
}
