import { useState } from "react";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ToastProvider } from "@/components/ui/toast";

export function installMissingMicrophonePreview() {
  Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
    value: async () => { throw new DOMException("No microphone", "NotFoundError"); },
  });
}

export function ComposerActionFixture({ parameters }: { parameters: URLSearchParams }) {
  const [running, setRunning] = useState(false);
  const [stopRequested, setStopRequested] = useState(false);
  return <ToastProvider><main className="mx-auto w-full max-w-5xl px-4" style={{ paddingTop: "6rem" }}>
    <ThreadComposer
      variant={parameters.get("composerVariant") === "thread" ? "thread" : "hero"}
      placeholder={parameters.has("opening") ? "Opening a new topic…" : undefined}
      modelLabel="Preview"
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
  </main></ToastProvider>;
}
