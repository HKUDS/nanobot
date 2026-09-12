// The short chime played when an agent turn completes while the page is
// visible (#5524). The asset ships with the WebUI's static files; playback is
// gated by the `notificationSound` local preference — off by default — and
// by page visibility: the chime is for someone actively watching the tab, so
// a background tab stays silent (browserNotifications covers that case).

import { readLocalPreferences } from "@/lib/local-preferences";

export const TURN_COMPLETE_SOUND_PATH = "/notification.wav";

let audio: HTMLAudioElement | null = null;

export function playTurnCompleteSound(): void {
  try {
    if (document.visibilityState !== "visible") return;
    if (!readLocalPreferences().notificationSound) return;
    if (audio === null) audio = new Audio(TURN_COMPLETE_SOUND_PATH);
    audio.currentTime = 0;
    void audio.play().catch(() => {
      // Autoplay policies or a missing asset must never surface as an error.
    });
  } catch {
    // A notification chime must never break the stream.
  }
}
