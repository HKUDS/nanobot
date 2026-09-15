import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_LOCAL_PREFS,
  writeLocalPreferences,
} from "@/lib/local-preferences";
import { TURN_COMPLETE_SOUND_PATH } from "@/lib/notification-sound";

class MockAudio {
  static instances: MockAudio[] = [];
  src: string;
  currentTime = 0;
  play = vi.fn().mockResolvedValue(undefined);

  constructor(src: string) {
    this.src = src;
    MockAudio.instances.push(this);
  }
}

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}

describe("playTurnCompleteSound", () => {
  beforeEach(() => {
    MockAudio.instances = [];
    vi.stubGlobal("Audio", MockAudio);
    vi.resetModules();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setVisibility("visible");
    window.localStorage.clear();
  });

  // Fresh module per test: the module keeps one HTMLAudioElement cached for
  // the page's lifetime, and the cache must not leak across cases.
  async function play(): Promise<void> {
    const { playTurnCompleteSound } = await import("@/lib/notification-sound");
    playTurnCompleteSound();
  }

  it("stays silent by default", async () => {
    await play();
    expect(MockAudio.instances).toHaveLength(0);
  });

  it("plays the bundled chime when enabled and the page is visible", async () => {
    writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, notificationSound: true });
    await play();
    expect(MockAudio.instances).toHaveLength(1);
    expect(MockAudio.instances[0].src).toBe(TURN_COMPLETE_SOUND_PATH);
    expect(MockAudio.instances[0].play).toHaveBeenCalledTimes(1);
  });

  it("stays silent when the page is in the background", async () => {
    writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, notificationSound: true });
    setVisibility("hidden");
    await play();
    expect(MockAudio.instances).toHaveLength(0);
  });

  it("reuses one audio element across turns and restarts it", async () => {
    writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, notificationSound: true });
    await play();
    await play();
    expect(MockAudio.instances).toHaveLength(1);
    const first = MockAudio.instances[0];
    expect(first.currentTime).toBe(0);
    expect(first.play).toHaveBeenCalledTimes(2);
  });

  it("swallows playback rejections", async () => {
    class RejectingAudio extends MockAudio {
      play = vi.fn().mockRejectedValue(new Error("autoplay blocked"));
    }
    vi.stubGlobal("Audio", RejectingAudio);
    writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, notificationSound: true });
    await expect(play()).resolves.toBeUndefined();
  });
});
