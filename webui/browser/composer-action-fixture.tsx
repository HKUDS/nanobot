import { useState } from "react";
import { ThreadComposer } from "@/components/thread/ThreadComposer";

export function ComposerActionFixture({ parameters }: { parameters: URLSearchParams }) {
  const [running, setRunning] = useState(false);
  const [stopRequested, setStopRequested] = useState(false);
  return <main className="mx-auto w-full max-w-5xl px-4 pt-24">
    <ThreadComposer
      variant={parameters.get("composerVariant") === "thread" ? "thread" : "hero"}
      modelLabel="Preview"
      goalState={parameters.has("goal") ? { active: true, objective: "Keep the work in focus." } : undefined}
      isStreaming={running}
      onTranscribeAudio={async () => "Voice draft"}
      onSend={() => { setStopRequested(false); setRunning(true); }}
      onStop={() => setStopRequested(true)}
    />
    <div className="mt-6 flex gap-4 text-sm">
      <output aria-label="Execution status">{stopRequested ? "Stop requested" : running ? "Working" : "Idle"}</output>
      <button onClick={() => { setRunning(false); setStopRequested(false); }}>Finish response</button>
      <button onClick={() => document.documentElement.classList.toggle("dark")}>Toggle theme</button>
    </div>
  </main>;
}
