/** Bounded receipt wait: a socket write is not message acceptance. */
export class DeliveryReceipts {
  private pending = new Map<string, { resolve: () => void; reject: (error: Error) => void }>();

  wait(turnId: string, send: () => void): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => {
        clearTimeout(timer);
        this.pending.delete(turnId);
        if (error) reject(error); else resolve();
      };
      const timer = setTimeout(() => finish(new Error("Message acceptance not confirmed; draft retained")), 30_000);
      this.pending.set(turnId, { resolve: () => finish(), reject: finish });
      try { send(); } catch (error) { finish(error instanceof Error ? error : new Error(String(error))); }
    });
  }

  event(event: { event: string; turn_id?: string; detail?: string; reason?: string }): void {
    if (!event.turn_id) return;
    const pending = this.pending.get(event.turn_id);
    if (event.event === "message_accepted" || event.event === "user_message") pending?.resolve();
    else if (event.event === "error") pending?.reject(new Error(event.reason || event.detail || "Message rejected"));
  }

  close(): void {
    for (const pending of this.pending.values()) pending.reject(new Error("Connection closed before message acceptance; draft retained"));
  }
}
