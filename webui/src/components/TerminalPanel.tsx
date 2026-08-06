import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { RotateCcw, Square, TerminalSquare, X } from "lucide-react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useTranslation } from "react-i18next";

import type { ConnectionStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

interface TerminalPanelProps {
  chatId: string;
  projectPath: string;
  desktopWidth?: number;
  onResizeStart?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onClose: () => void;
}

type TerminalStatus = "connecting" | "ready" | "stopping" | "exited" | "error";

const TERMINAL_THEME = {
  background: "#0d1117",
  foreground: "#d7dae0",
  cursor: "#f0a45d",
  cursorAccent: "#0d1117",
  selectionBackground: "#35536f99",
  black: "#1f242c",
  red: "#f47067",
  green: "#57ab5a",
  yellow: "#c69026",
  blue: "#539bf5",
  magenta: "#b083f0",
  cyan: "#39c5cf",
  white: "#b1bac4",
  brightBlack: "#636e7b",
  brightRed: "#ff938a",
  brightGreen: "#6bc46d",
  brightYellow: "#daaa3f",
  brightBlue: "#6cb6ff",
  brightMagenta: "#dcbdfb",
  brightCyan: "#56d4dd",
  brightWhite: "#f0f3f6",
};

function projectName(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/$/, "");
  return normalized.split("/").pop() || path;
}

export function TerminalPanel({
  chatId,
  projectPath,
  desktopWidth = 560,
  onResizeStart,
  onClose,
}: TerminalPanelProps) {
  const { t } = useTranslation();
  const { client } = useClient();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const terminalIdRef = useRef<string | null>(null);
  const resizeFrameRef = useRef<number | null>(null);
  const resizeSettleFrameRef = useRef<number | null>(null);
  const lastSentDimensionsRef = useRef({ rows: 0, cols: 0 });
  const [entered, setEntered] = useState(false);
  const [status, setStatus] = useState<TerminalStatus>("connecting");
  const [error, setError] = useState<string | null>(null);

  const fitAndResize = useCallback((sendResize: boolean, force = false) => {
    const terminal = terminalRef.current;
    const fit = fitRef.current;
    const container = containerRef.current;
    if (
      !terminal
      || !fit
      || !container?.isConnected
      || container.clientWidth <= 0
      || container.clientHeight <= 0
    ) return;
    try {
      fit.fit();
    } catch {
      return;
    }
    const dimensions = { rows: terminal.rows, cols: terminal.cols };
    if (dimensions.rows < 2 || dimensions.cols < 2) return;
    if (
      !force
      && dimensions.rows === lastSentDimensionsRef.current.rows
      && dimensions.cols === lastSentDimensionsRef.current.cols
    ) return;
    const terminalId = terminalIdRef.current;
    if (sendResize && terminalId && client.status === "open") {
      lastSentDimensionsRef.current = dimensions;
      client.resizeTerminal(chatId, terminalId, dimensions.rows, dimensions.cols);
    }
  }, [chatId, client]);

  const openTerminal = useCallback(() => {
    fitAndResize(false);
    const terminal = terminalRef.current;
    const rows = Math.min(200, Math.max(2, terminal?.rows ?? 30));
    const cols = Math.min(500, Math.max(2, terminal?.cols ?? 100));
    setStatus("connecting");
    setError(null);
    client.openTerminal(chatId, rows, cols);
  }, [chatId, client, fitAndResize]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setEntered(true));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const terminal = new Terminal({
      allowTransparency: false,
      cursorBlink: true,
      cursorStyle: "bar",
      fontFamily: '"SFMono-Regular", "Cascadia Code", Consolas, "Liberation Mono", monospace',
      fontSize: 12.5,
      letterSpacing: 0,
      lineHeight: 1.28,
      scrollback: 10_000,
      theme: TERMINAL_THEME,
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(container);
    terminalRef.current = terminal;
    fitRef.current = fit;

    const inputSubscription = terminal.onData((data) => {
      const terminalId = terminalIdRef.current;
      if (terminalId) client.writeTerminal(chatId, terminalId, data);
    });
    const terminalSubscription = client.onTerminal(chatId, (event) => {
      if (event.event === "terminal_ready") {
        terminalIdRef.current = event.terminal_id;
        if (event.pty_backend) {
          terminal.options.windowsPty = {
            backend: event.pty_backend,
            ...(typeof event.windows_build === "number"
              ? { buildNumber: event.windows_build }
              : {}),
          };
        }
        terminal.reset();
        if (event.data) {
          terminal.write(event.data, () => fitAndResize(true, true));
        }
        setStatus(event.running ? "ready" : "exited");
        setError(null);
        window.requestAnimationFrame(() => {
          fitAndResize(true, true);
          terminal.focus();
        });
        return;
      }
      if (
        "terminal_id" in event
        && event.terminal_id
        && event.terminal_id !== terminalIdRef.current
      ) return;
      if (event.event === "terminal_output") {
        if (event.replay_reset) terminal.reset();
        if (event.data) terminal.write(event.data);
        return;
      }
      if (event.event === "terminal_exit") {
        setStatus("exited");
        return;
      }
      if (event.event === "terminal_error") {
        setStatus("error");
        setError(event.reason || event.detail || t("terminal.error", {
          defaultValue: "Terminal request failed.",
        }));
      }
    });

    let needsOpen = true;
    const requestOpen = () => {
      if (!needsOpen || client.status !== "open") return;
      needsOpen = false;
      openTerminal();
    };
    const statusSubscription = client.onStatus((connectionStatus: ConnectionStatus) => {
      if (connectionStatus !== "open") {
        needsOpen = true;
        setStatus("connecting");
        return;
      }
      requestOpen();
    });

    const observer = new ResizeObserver(() => {
      if (resizeFrameRef.current !== null) return;
      resizeFrameRef.current = window.requestAnimationFrame(() => {
        resizeFrameRef.current = null;
        fitAndResize(true);
        if (resizeSettleFrameRef.current !== null) {
          window.cancelAnimationFrame(resizeSettleFrameRef.current);
        }
        // The drag handle mutates CSS variables in an animation frame. A
        // second frame lets layout/canvas metrics settle before the final fit,
        // avoiding ConPTY/xterm reflow against a stale column count.
        resizeSettleFrameRef.current = window.requestAnimationFrame(() => {
          resizeSettleFrameRef.current = null;
          fitAndResize(true);
        });
      });
    });
    observer.observe(container);
    const openFrame = window.requestAnimationFrame(requestOpen);
    const fonts = document.fonts;
    if (fonts) {
      void fonts.ready.then(() => fitAndResize(true, true));
    }

    return () => {
      const terminalId = terminalIdRef.current;
      if (terminalId && client.status === "open") {
        client.detachTerminal(chatId, terminalId);
      }
      terminalIdRef.current = null;
      window.cancelAnimationFrame(openFrame);
      if (resizeFrameRef.current !== null) {
        window.cancelAnimationFrame(resizeFrameRef.current);
        resizeFrameRef.current = null;
      }
      if (resizeSettleFrameRef.current !== null) {
        window.cancelAnimationFrame(resizeSettleFrameRef.current);
        resizeSettleFrameRef.current = null;
      }
      observer.disconnect();
      statusSubscription();
      terminalSubscription();
      inputSubscription.dispose();
      terminal.dispose();
      terminalRef.current = null;
      fitRef.current = null;
    };
  }, [chatId, client, fitAndResize, openTerminal, t]);

  const restart = () => {
    const terminalId = terminalIdRef.current;
    if (terminalId) client.killTerminal(chatId, terminalId);
    terminalIdRef.current = null;
    terminalRef.current?.reset();
    window.requestAnimationFrame(openTerminal);
  };

  const kill = () => {
    const terminalId = terminalIdRef.current;
    if (!terminalId) return;
    setStatus("stopping");
    client.killTerminal(chatId, terminalId);
  };

  const statusLabel = status === "ready"
    ? t("terminal.connected", { defaultValue: "Connected" })
    : status === "connecting"
      ? t("terminal.connecting", { defaultValue: "Connecting" })
      : status === "stopping"
        ? t("terminal.stopping", { defaultValue: "Stopping" })
        : status === "exited"
          ? t("terminal.exited", { defaultValue: "Exited" })
          : t("terminal.error", { defaultValue: "Error" });

  return (
    <aside
      aria-label={t("terminal.aria", { defaultValue: "Project terminal" })}
      style={{
        "--terminal-width": `${desktopWidth}px`,
        "--terminal-slot-width": entered ? `${desktopWidth}px` : "0px",
      } as CSSProperties}
      className={cn(
        "absolute inset-y-0 right-0 z-30 w-[min(100vw,var(--terminal-slot-width))] overflow-hidden",
        "transition-[width] duration-300 ease-out will-change-[width]",
        "md:relative md:z-auto md:w-[var(--terminal-slot-width)] md:min-w-0 md:shrink-0",
      )}
      data-testid="terminal-panel"
      data-terminal-panel
    >
      <div
        className={cn(
          "absolute inset-y-0 right-0 flex w-[min(100vw,var(--terminal-width))] flex-col overflow-hidden md:w-[var(--terminal-width)]",
          "border-l border-border/70 bg-background shadow-2xl md:shadow-none",
          "transition-[opacity,transform] duration-300 ease-out will-change-transform",
          entered ? "translate-x-0 opacity-100" : "translate-x-full opacity-0",
          "motion-reduce:translate-x-0",
        )}
      >
        {onResizeStart ? (
          <button
            type="button"
            aria-label={t("terminal.resize", { defaultValue: "Resize terminal" })}
            className={cn(
              "group absolute inset-y-0 left-0 z-20 hidden w-3 -translate-x-1/2 cursor-col-resize touch-none md:flex",
              "items-stretch justify-center focus-visible:outline-none",
            )}
            onPointerDown={onResizeStart}
          >
            <span
              aria-hidden
              className="h-full w-px bg-foreground/25 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:bg-ring group-focus-visible:opacity-100"
            />
          </button>
        ) : null}

        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border/60 px-3">
          <TerminalSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium" title={projectPath}>
              {projectName(projectPath)}
            </div>
          </div>
          <div
            className="flex shrink-0 items-center gap-1.5 text-[10px] text-muted-foreground"
            title={statusLabel}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                status === "ready" && "bg-emerald-500",
                status === "connecting" && "animate-pulse bg-amber-500",
                status === "stopping" && "animate-pulse bg-orange-500",
                status === "exited" && "bg-muted-foreground/50",
                status === "error" && "bg-destructive",
              )}
              aria-hidden
            />
            <span className="hidden sm:inline">{statusLabel}</span>
          </div>
          <button
            type="button"
            onClick={restart}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            title={t("terminal.restart", { defaultValue: "Restart terminal" })}
            aria-label={t("terminal.restart", { defaultValue: "Restart terminal" })}
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={kill}
            disabled={!terminalIdRef.current || status === "stopping" || status === "exited"}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-35"
            title={t("terminal.kill", { defaultValue: "End terminal process" })}
            aria-label={t("terminal.kill", { defaultValue: "End terminal process" })}
          >
            <Square className="h-3 w-3 fill-current" aria-hidden />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            title={t("terminal.detach", { defaultValue: "Hide terminal" })}
            aria-label={t("terminal.detach", { defaultValue: "Hide terminal" })}
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        <div className="relative min-h-0 flex-1 bg-[#0d1117]">
          <div
            ref={containerRef}
            className="absolute inset-0 min-h-0 min-w-0 px-2 py-2 [&_.xterm]:h-full [&_.xterm]:w-full [&_.xterm-screen]:max-w-full [&_.xterm-viewport]:!overflow-y-auto"
            onClick={() => terminalRef.current?.focus()}
          />
          {error ? (
            <div className="pointer-events-none absolute inset-x-4 bottom-4 rounded-md border border-red-400/25 bg-red-950/90 px-3 py-2 text-xs text-red-100 shadow-lg">
              {error}
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
