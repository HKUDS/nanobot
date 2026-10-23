import { useState } from "react";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type { SendAttachment, SendOptions } from "@/hooks/useNanobotStream";

export function QueuedGuidanceFixture() {
  const [away, setAway] = useState(false);
  const [completed, setCompleted] = useState(new URLSearchParams(location.search).has("complete"));
  const [sent, setSent] = useState<Array<{ text: string; images?: SendAttachment[]; options?: SendOptions }>>([]);
  return <main className="mx-auto max-w-3xl p-4">
    <div className="mb-4 flex flex-wrap gap-4">
      <button onClick={() => setAway(!away)}>Switch topic</button>
      <button onClick={() => setCompleted(true)}>Complete original reply</button>
    </div>
    {away ? <p>Another topic</p> : <ThreadComposer
      pendingQueueKey="queued-fixture"
      isStreaming={!completed}
      activeTurnId={completed ? null : "turn-a"}
      completedTurnIds={completed ? ["turn-a"] : []}
      onStop={() => setCompleted(true)}
      onSend={(text, images, options) => {
        setSent((current) => [...current, { text, images, options }]);
        return true;
      }}
    />}
    <output aria-label="Submitted messages">{JSON.stringify(sent)}</output>
  </main>;
}
