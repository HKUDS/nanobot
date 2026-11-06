import { useMemo, useRef, useState } from "react";
import { DiffViewportContext } from "@/components/thread/activity/DiffViewportContext";
import { FileEditGroup, type FileEditSummary } from "@/components/thread/activity/FileEditRow";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { setAppLanguage } from "@/i18n";

const patch = (name: string, lines: string[], oldCount: number, newCount: number) =>
  [`--- a/${name}`, `+++ b/${name}`, `@@ -${oldCount ? 1 : 0},${oldCount} +1,${newCount} @@`, ...lines, ""].join("\n");
const markdown = ["## 发布安排", "", "| 日期 | 角色 | 方向 |", "| --- | --- | --- |", "| 7/22 | trust / core | data-driven |"];
const longLines = Array.from({ length: 600 }, (_, index) => `export const item${index + 1} = "第 ${index + 1} 行 — readable code";`);
const samples: Array<[string, string]> = [
  ["Status.tsx", patch("Status.tsx", [
    ' import { useMemo } from "react";', " export function StatusBadge() {",
    '-  return <span className="badge">old</span>;', '+  return <span className="badge">ready</span>;', " }",
  ], 4, 4)],
  ["table.md", patch("table.md", markdown.map(line => `+${line}`), 0, markdown.length)],
  ["callbacks.tsx", patch("callbacks.tsx", ['+<span className={enabled ? "yes" : "no"} onClick={() => save(new Event("ok"))}>ready</span>'], 0, 1)],
  ["page.html", patch("page.html", ['+<script>alert("not executable")</script>'], 0, 1)],
  ["config.ini", patch("config.ini", [" ; comment", " [server]", "-host=old-server", "+host=localhost"], 3, 3)],
  ["bun.lock", patch("bun.lock", ["+unknown-language contents remain readable"], 0, 1)],
  ["separated.ts", ["--- a/separated.ts", "+++ b/separated.ts", "@@ -1,3 +1,3 @@", " function first() {", "-  return oldFirst;", "+  return newFirst;", " }", "@@ -25,3 +25,3 @@", " function second() {", "-  return oldSecond;", "+  return newSecond;", " }", ""].join("\n")],
  ["long.ts", patch("long.ts", longLines.map(line => `+${line}`), 0, longLines.length)],
  ["worker.ts", patch("worker.ts", longLines.map(line => `+${line} // ${"worker source ".repeat(10)}`), 0, longLines.length)],
  ["long-separated.ts", ["--- a/long-separated.ts", "+++ b/long-separated.ts", ...[0, 1, 2].flatMap(index => [`@@ -${index * 500},0 +${index * 500 + 1},200 @@`, ...longLines.slice(index * 200, (index + 1) * 200).map(line => `+${line}`)]), ""].join("\n")],
  ["truncated.ts", patch("truncated.ts", ["+export const truncated = true;"], 0, 1)],
];

export function FileDiffFixture() {
  const { theme, toggle } = useTheme();
  const [opened, setOpened] = useState("");
  const [changed, setChanged] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const viewport = useMemo(() => ({ scroller, content }), []);
  return <ThemeProvider theme={theme}><DiffViewportContext.Provider value={viewport}>
    <div ref={scroller} className="h-full overflow-y-auto" data-testid="diff-fixture-scroller">
    <main ref={content} className="mx-auto max-w-3xl space-y-6 p-4">
    <button onClick={toggle}>Toggle theme</button>
    <button onClick={() => setChanged(true)}>Change source</button>
    <button onClick={() => void setAppLanguage("zh-CN")}>Chinese</button>
    {samples.map(([path, text]) => {
      const edit: FileEditSummary = {
        key: path, path, absolute_path: `/fixture/${path}`, added: 1, deleted: 1,
        approximate: false, binary: false, status: "done", pending: false,
        diff: { format: "unified", text: changed && path === "Status.tsx" ? text.replace(">ready<", ">updated<") : text, truncated: path === "truncated.ts" },
      };
      return <section key={path} aria-label={path}>
        <FileEditGroup edits={[edit]} displayMode="diff" onOpenFilePreview={setOpened} />
      </section>;
    })}
    <output aria-label="Opened file">{opened}</output>
  </main></div></DiffViewportContext.Provider></ThemeProvider>;
}
