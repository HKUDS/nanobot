import { useState } from "react";

import { FileActionsProvider } from "@/components/FileActions";
import { FilePreviewAvailabilityProvider } from "@/components/FilePreviewAvailabilityContext";
import { MessageBubble } from "@/components/MessageBubble";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";

const references = [
  "notes/ready.md",
  `notes/${"long directory/".repeat(16)}report.md`,
  String.raw`C:\Users\reader\My Docs\report.md`,
  "pytest tests/test_agent.py",
  "cat  \t~/My Docs/report.md",
  "这是一段说明文字，最后引用 /tmp/sample.txt",
  "notes/chart.png",
  `notes/${"segment".repeat(30)}.md`,
];
const source = references.map(text => `Before \`${text}\` after.`).join("\n\n")
  + "\n\n[Short report](notes/ready.md)";
const resolve = async (path: string) => path.startsWith("notes/");

export function InlineFileReferenceFixture() {
  const { theme } = useTheme();
  const [text, setText] = useState(source);
  const [streaming, setStreaming] = useState(true);
  const [opened, setOpened] = useState("");
  return <ThemeProvider theme={theme}><FileActionsProvider value={{
    resolveMetadata: async (path) => ({ path, relative_path: path }),
    loadPreview: async (path) => ({
      path, display_path: path, project_path: path, size: 68, kind: "image", mime_type: "image/png",
      data_url: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=",
    }),
  }}><FilePreviewAvailabilityProvider resolve={resolve}>
    <main className="mx-auto space-y-4 p-4" style={{ maxWidth: 680 }}>
      <textarea aria-label="Markdown source" className="h-24 w-full font-mono" value={text} onChange={event => setText(event.target.value)} />
      <button onClick={() => setStreaming(false)}>Complete message</button>
      <section aria-label="File references">
        <MessageBubble message={{ id: "file-references", role: "assistant", createdAt: 1, content: text, isStreaming: streaming }}
          onOpenFilePreview={setOpened} />
      </section>
      <output aria-label="Opened file">{opened}</output>
    </main>
  </FilePreviewAvailabilityProvider></FileActionsProvider></ThemeProvider>;
}
