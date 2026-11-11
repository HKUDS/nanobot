import type { UIMessage } from "./types";
import type { ThreadProjectionEffects } from "./thread-event-projection";

/** Owned by one projector, never shared with its immutable checkpoints. */
export class ThreadProjectionIndex {
  private messages: UIMessage[] | null = null;
  private ids = new Map<string, number>();
  private answers = new Map<string, Set<number>>();
  lastUser = -1;

  position(id: string): number | undefined { return this.ids.get(id); }
  answer(stream: string): ReadonlySet<number> { return this.answers.get(stream) ?? new Set(); }

  private record(row: UIMessage, index: number, remove = false): void {
    if (!remove) this.ids.set(row.id, index);
    if (row.role === "user" && !remove) this.lastUser = index;
    if (row.role !== "assistant") return;
    const key = row.streamId ?? "";
    const positions = this.answers.get(key) ?? new Set<number>();
    if (remove) positions.delete(index);
    else positions.add(index);
    if (positions.size) this.answers.set(key, positions);
    else this.answers.delete(key);
  }

  sync(messages: UIMessage[], effects?: ThreadProjectionEffects): void {
    if (messages === this.messages) return;
    const previous = this.messages;
    if (!previous || !effects || effects.consumed.size || messages.length < previous.length) {
      this.ids.clear();
      this.answers.clear();
      this.lastUser = -1;
      messages.forEach((row, index) => this.record(row, index));
    } else {
      for (const id of effects.bodyWrites) {
        const index = this.ids.get(id);
        if (index === undefined) continue;
        if (messages[index].streamId !== previous[index].streamId) {
          this.record(previous[index], index, true);
          this.record(messages[index], index);
        }
      }
      for (let index = previous.length; index < messages.length; index++) this.record(messages[index], index);
    }
    this.messages = messages;
  }
}
