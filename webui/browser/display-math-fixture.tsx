import { useState } from "react";

import { MarkdownText } from "@/components/MarkdownText";

export function DisplayMathFixture() {
  const [step, setStep] = useState(0);
  const [streaming, setStreaming] = useState(true);
  const terms = step === 0 ? "x + y" : Array.from({ length: 24 }, (_, index) => `x_{${index}}`).join(" + ");
  const tag = step < 2 ? "1" : "1000000";
  return <main className="mx-auto max-w-3xl p-6">
    <button onClick={() => setStep((value) => value + 1)}>Advance stream</button>
    <button onClick={() => setStreaming(false)}>Complete</button>
    <div data-testid="math-reply"><MarkdownText streaming={streaming} preserveStreamingLayout>
      {`$$${terms} = 1 \\tag{${tag}}$$`}
    </MarkdownText></div>
  </main>;
}
