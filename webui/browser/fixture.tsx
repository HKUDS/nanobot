import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MessageBubble } from "@/components/MessageBubble";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { TooltipProvider } from "@/components/ui/tooltip";
import { initializeI18n } from "@/i18n";
import type { UIMessage } from "@/lib/types";
import "../src/globals.css";

const history: UIMessage[] = [
  { id: "question", role: "user", content: "Earlier question", createdAt: 1_700_000_000_000 },
  { id: "answer", role: "assistant", content: "Earlier answer", createdAt: 1_700_000_001_000 },
];
const trace: UIMessage = {
  id: "trace", role: "tool", kind: "trace", content: "Earlier tool call", createdAt: 1_700_000_002_000,
};

function HistoryFixture() {
  const [open, setOpen] = useState(false);
  return <main>
    <button onClick={() => setOpen(!open)}>{open ? "Close history" : "Reopen history"}</button>
    <section aria-label="Persisted history">
      {open && <>
        <ThreadMessages messages={history} isStreaming={false} />
        <MessageBubble message={trace} />
      </>}
    </section>
  </main>;
}

function TallDialogFixture({ placement }: { placement: "center" | "bottom" }) {
  return <main aria-label="Background content" style={{ height: 240, overflowY: "auto" }}>
    <div style={{ minHeight: 1800 }}><Dialog>
      <DialogTrigger asChild><button>Open tall dialog</button></DialogTrigger>
      <DialogContent placement={placement}>
        <DialogTitle>Tall dialog</DialogTitle>
        <DialogDescription>All controls must remain reachable in a short viewport.</DialogDescription>
        {Array.from({ length: 30 }, (_, index) => <label key={index}>
          Field {index + 1}<input aria-label={`Field ${index + 1}`} style={{ display: "block", height: 40 }} />
        </label>)}
        <DialogClose asChild><button>Save tall dialog</button></DialogClose>
      </DialogContent>
    </Dialog></div>
  </main>;
}

const parameters = new URLSearchParams(location.search);
await initializeI18n();
createRoot(document.getElementById("root")!).render(<TooltipProvider>
  {parameters.get("case") === "history"
    ? <HistoryFixture />
    : <TallDialogFixture placement={parameters.get("placement") === "bottom" ? "bottom" : "center"} />}
</TooltipProvider>);
