import { useEffect, useRef, useState } from "react";
import { ChevronDown, LoaderCircle, Terminal } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { stripAnsi } from "@/lib/ansi";
import { copyTextToClipboard } from "@/lib/clipboard";
import type { NanobotClient } from "@/lib/nanobot-client";

export type BackgroundCommand = {
  session_id: string; command: string; cwd: string; elapsed_ms: number; exit_code: number | null;
  state: "running" | "completed" | "failed" | "stopped" | "timed_out";
};
type CommandDetail = BackgroundCommand & {
  chunks: { seq: number; stream: "stdout" | "stderr"; text: string }[];
  omitted_chars: number;
};
const states = new Set(["running", "completed", "failed", "stopped", "timed_out"]);
function isCommand(value: unknown): value is BackgroundCommand {
  if (!value || typeof value !== "object") return false;
  return "session_id" in value && typeof value.session_id === "string" && /^[0-9a-f]{12}$/.test(value.session_id)
    && "command" in value && typeof value.command === "string" && value.command.length <= 16384
    && "cwd" in value && typeof value.cwd === "string" && value.cwd.length <= 8192
    && "state" in value && typeof value.state === "string" && states.has(value.state)
    && "elapsed_ms" in value && Number.isSafeInteger(value.elapsed_ms) && Number(value.elapsed_ms) >= 0
    && "exit_code" in value && (value.exit_code === null || Number.isSafeInteger(value.exit_code));
}
export function readCommands(value: unknown): BackgroundCommand[] {
  if (!value || typeof value !== "object" || !("commands" in value) || !Array.isArray(value.commands)
    || value.commands.length > 40 || !value.commands.every(isCommand)) throw new Error("Invalid command list");
  return value.commands;
}
export function readCommandDetail(value: unknown): CommandDetail {
  if (!value || typeof value !== "object" || !("command" in value) || !isCommand(value.command)) throw new Error("Invalid command detail");
  const row = value.command;
  if (!("chunks" in row) || !Array.isArray(row.chunks) || row.chunks.length > 512
    || !("omitted_chars" in row) || !Number.isSafeInteger(row.omitted_chars) || Number(row.omitted_chars) < 0
    || !row.chunks.every((chunk): chunk is CommandDetail["chunks"][number] => chunk && typeof chunk === "object"
      && Number.isSafeInteger(chunk.seq) && chunk.seq > 0 && (chunk.stream === "stdout" || chunk.stream === "stderr")
      && typeof chunk.text === "string")
    // Python bounds Unicode code points; JS strings count UTF-16 code units.
    || row.chunks.reduce((n, chunk) => n + chunk.text.length, 0) > 200_000) throw new Error("Invalid command output");
  return { ...row, chunks: row.chunks, omitted_chars: Number(row.omitted_chars) };
}

/** A read-only log observer with one explicitly scoped stop action; never drains agent output. */
type Props = {
  client: Pick<NanobotClient, "requestMutation">; chatId: string;
};
export function BackgroundCommandsPanel(props: Props) {
  return <BackgroundCommandsBody key={props.chatId} {...props} />;
}
function BackgroundCommandsBody({ client, chatId }: Props) {
  const { t } = useTranslation();
  const label = (key: string) => t(`thread.backgroundCommands.${key}`);
  const [commands, setCommands] = useState<BackgroundCommand[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CommandDetail | null>(null);
  const [error, setError] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [copied, setCopied] = useState(false);
  const [follow, setFollow] = useState(true);
  const [confirm, setConfirm] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const generation = useRef(0);
  const lifetime = useRef(0);
  useEffect(() => () => { lifetime.current++; }, []);
  const log = useRef<HTMLPreElement>(null);
  useEffect(() => {
    const epoch = ++generation.current;
    let disposed = false;
    let busy = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (disposed || busy || document.visibilityState === "hidden") return;
      busy = true;
      try {
        const rows = readCommands(await client.requestMutation("background.list", { chat_id: chatId }, 10_000));
        if (disposed) return;
        setCommands(rows);
        if (expanded && selected && rows.some((row) => row.session_id === selected)) {
          const snapshot = readCommandDetail(await client.requestMutation("background.read", { chat_id: chatId, session_id: selected }, 10_000));
          if (!disposed && snapshot.session_id === selected) setDetail(snapshot);
        } else if (!rows.some((row) => row.session_id === selected)) {
          setDetail(null);
        }
        if (!disposed) setError(false);
      } catch {
        if (!disposed) setError(true);
      } finally {
        busy = false;
        if (!disposed) timer = setTimeout(() => void poll(), 3000);
      }
    }
    function visibility() { clearTimeout(timer); void poll(); }
    void poll();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      disposed = true; if (generation.current === epoch) generation.current++;
      clearTimeout(timer); document.removeEventListener("visibilitychange", visibility);
    };
  }, [client, chatId, selected, expanded, refresh]);
  useEffect(() => {
    if (follow && log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [detail, follow]);
  async function stop() {
    if (!selected || stopping) return;
    const epoch = lifetime.current;
    setStopping(true); setActionError(false);
    try {
      const result = readCommandDetail(await client.requestMutation("background.stop", { chat_id: chatId, session_id: selected }, 15_000));
      if (lifetime.current !== epoch || result.session_id !== selected) return;
      setDetail(result); setConfirm(false); setRefresh((n) => n + 1);
    } catch {
      if (lifetime.current === epoch) setActionError(true);
    } finally {
      if (lifetime.current === epoch) setStopping(false);
    }
  }
  if (!commands.length) return null;
  const active = commands.filter((row) => row.state === "running").length;
  return <section className="mx-auto mb-2 w-full max-w-[49.5rem] rounded-control border border-border/60 bg-muted/20 text-sm">
    <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="flex w-full items-center gap-2 rounded-control px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {active && !error ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> : <Terminal className="size-4" aria-hidden />}
      <span className="flex-1">{label("title")} <span className="text-muted-foreground">({commands.length})</span></span>
      <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
    </button>
    <div hidden={!expanded} className="max-h-[min(60vh,32rem)] space-y-2 overflow-y-auto px-3 pb-3">
      <p className="text-xs text-muted-foreground">{label("retention")}</p>
      {error ? <div role="status" className="flex flex-wrap items-center gap-2 text-xs">{label("stale")}
        <Button variant="ghost" size="sm" onClick={() => setRefresh((n) => n + 1)}>{label("retry")}</Button></div> : null}
      {[...commands].reverse().map((command) => <div key={command.session_id} className="min-w-0 rounded-lg border border-border/60 bg-background/40">
        <button type="button" aria-expanded={selected === command.session_id} disabled={stopping} onClick={() => {
          setSelected(selected === command.session_id ? null : command.session_id); setDetail(null);
          setConfirm(false); setActionError(false); setCopied(false); setFollow(true);
        }} className="w-full space-y-1 rounded-lg p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <div className="flex items-baseline gap-2"><span className="min-w-0 flex-1 truncate font-mono text-xs" title={command.command}>{command.command}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{label(error && command.state === "running" ? "unknown" : command.state)}</span></div>
          <div className="truncate text-xs text-muted-foreground">{command.cwd} · {Math.round(command.elapsed_ms / 1000)}s{command.exit_code === null ? "" : ` · ${label("exit")} ${command.exit_code}`}</div>
        </button>
        {selected === command.session_id ? <div className="space-y-2 px-3 pb-3">
          <div className="flex flex-wrap items-center gap-1">
            <Button size="sm" variant="ghost" aria-pressed={follow} onClick={() => setFollow(!follow)}>{label(follow ? "pauseFollow" : "follow")}</Button>
            <Button size="sm" variant="ghost" disabled={!detail} onClick={async () => {
              const epoch = generation.current;
              const okay = await copyTextToClipboard(stripAnsi(detail?.chunks.map((chunk) => chunk.text).join("") ?? ""));
              if (epoch === generation.current) { setCopied(okay); setActionError(!okay); }
            }}>{label(copied ? "copied" : "copy")}</Button>
            {command.state === "running" ? <Button size="sm" variant="ghost" disabled={error || stopping} onClick={() => setConfirm(true)}>{label("stop")}</Button> : null}
          </div>
          {confirm ? <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2 text-xs">
            <span className="flex-1">{label("confirmStop")}</span>
            <Button size="sm" variant="outline" disabled={stopping} onClick={() => void stop()}>{label(stopping ? "stopping" : "stop")}</Button>
            <Button size="sm" variant="ghost" disabled={stopping} onClick={() => setConfirm(false)}>{label("cancel")}</Button>
          </div> : null}
          {actionError ? <p role="alert" className="text-xs text-destructive">{label("actionFailed")}</p> : null}
          <pre ref={log} tabIndex={0} aria-label={label("output")} onScroll={(event) => {
            const element = event.currentTarget;
            if (element.scrollHeight - element.clientHeight - element.scrollTop > 16) setFollow(false);
          }} className="max-h-48 overflow-auto rounded-lg bg-muted/40 p-3 font-mono text-xs leading-relaxed">
            {detail ? detail.chunks.length ? detail.chunks.map((chunk) => <span key={chunk.seq} className={chunk.stream === "stderr" ? "text-amber-700 dark:text-amber-300" : undefined}>{stripAnsi(chunk.text)}</span>) : label("noOutput") : label("loading")}
          </pre>
          {detail && detail.omitted_chars > 0 ? <p className="text-xs text-muted-foreground">{t("thread.backgroundCommands.truncated", { count: detail.omitted_chars })}</p> : null}
        </div> : null}
      </div>)}
    </div>
  </section>;
}
