import type { SessionMention } from "./types";

/** Page-lifetime drafts. Files stay in memory, including unfinished attachments. */
export interface ComposerDraft {
  text: string;
  files: File[];
  sessionMentions: SessionMention[];
  quotedContext: string | null;
}

export type ComposerDraftStore = Map<string, ComposerDraft>;
