export const SOUND_URL = "/sounds/turn-complete.mp3";

let cachedAudio: HTMLAudioElement | null = null;

/**
 * Play the short turn-complete sound. Best-effort: any failure (missing
 * asset, autoplay restrictions, unsupported environment) is silently ignored.
 */
export function playTurnCompleteSound(): void {
  try {
    cachedAudio ??= new Audio(SOUND_URL);
    cachedAudio.currentTime = 0;
    const result = cachedAudio.play();
    if (result && typeof result.catch === "function") {
      void result.catch(() => {});
    }
  } catch {
    // Sound playback must never surface errors to the user.
  }
}
