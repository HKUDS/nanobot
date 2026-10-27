import { useState } from "react";
import { createRoot } from "react-dom/client";
import { FileActionsProvider } from "@/components/FileActions";
import { FilePreviewAvailabilityProvider } from "@/components/FilePreviewAvailabilityContext";
import { FileReferenceChip } from "@/components/FileReferenceChip";
import { MarkdownText } from "@/components/MarkdownText";
import { WebSearchRun } from "@/components/thread/activity/WebSearchRun";
import { TooltipProvider } from "@/components/ui/tooltip";
import { initializeI18n } from "@/i18n";
import "../src/globals.css";
import { FileEditPathFixture } from "./file-edit-path-fixture";

const resolveAvailability = async (path: string) => path !== "src/missing.md";

function ContentLinkPaletteFixture() {
  const [opened, setOpened] = useState("");
  return <>
    <FileEditPathFixture />
    <FileActionsProvider value={{ resolveMetadata: async (path) => ({ path, relative_path: null }) }}>
      <div className="px-4 pb-4">
        <section aria-label="File references">
          <FilePreviewAvailabilityProvider resolve={resolveAvailability}>
            <MarkdownText onOpenFilePreview={setOpened}>{"Files: `src/report.md`, [Local notes](docs/notes.md), `src/missing.md`."}</MarkdownText>
          </FilePreviewAvailabilityProvider>
          <MarkdownText documentPath="/workspace/REPORT.md" onOpenFilePreview={setOpened}>{"[Local document](notes.md)"}</MarkdownText>
          <FileReferenceChip path="README.md" display="path" onOpen={setOpened} testId="root-file-reference" />
        </section>
        <section aria-label="Search results" className="mt-6">
          <WebSearchRun turnActive={false} run={{
            key: "palette-search", query: "project notes", target: "web", status: "done",
            sources: [{ title: "Project notes", href: "https://example.com/source", host: "example.com", displayUrl: "example.com/source" }],
          }} />
        </section>
        <output aria-label="Opened inline file">{opened}</output>
      </div>
    </FileActionsProvider>
  </>;
}

await initializeI18n();
createRoot(document.getElementById("root")!).render(<TooltipProvider><ContentLinkPaletteFixture /></TooltipProvider>);
