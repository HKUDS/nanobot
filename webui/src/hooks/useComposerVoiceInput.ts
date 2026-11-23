import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useToast } from "@/components/ui/toast";
import { useVoiceRecorder, type VoiceRecorderErrorKey } from "@/hooks/useVoiceRecorder";

const VOICE_SHORTCUT_CODE = "KeyD";
const VOICE_SHORTCUT_ARIA = "Control+Shift+D";
type VoiceShortcutPlatform = "apple" | "chromeos" | "linux" | "other" | "windows";

function isVoiceShortcutDown(event: KeyboardEvent): boolean {
  return (
    event.code === VOICE_SHORTCUT_CODE
    && event.ctrlKey
    && event.shiftKey
    && !event.altKey
    && !event.metaKey
  );
}

function isVoiceShortcutRelease(event: KeyboardEvent): boolean {
  return (
    event.code === VOICE_SHORTCUT_CODE
    || event.key === "Control"
    || event.key === "Shift"
  );
}

function getVoiceShortcutPlatform(): VoiceShortcutPlatform {
  if (typeof navigator === "undefined") return "other";
  const userAgentData = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData;
  const platform = [
    userAgentData?.platform,
    navigator.platform,
    navigator.userAgent,
  ].filter(Boolean).join(" ").toLowerCase();
  const isIpadPretendingToBeMac =
    navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  if (isIpadPretendingToBeMac || /mac|iphone|ipad|ipod/.test(platform)) return "apple";
  if (/win/.test(platform)) return "windows";
  if (/cros/.test(platform)) return "chromeos";
  if (/linux|x11|android/.test(platform)) return "linux";
  return "other";
}

function getVoiceShortcutLabel(): string {
  switch (getVoiceShortcutPlatform()) {
    case "apple":
      return "⌃⇧D";
    case "chromeos":
    case "linux":
    case "windows":
    case "other":
      return "Ctrl ⇧ D";
  }
}

type VoiceInputOptions = Pick<Parameters<typeof useVoiceRecorder>[0],
  "disabled" | "onTranscribeAudio" | "onTranscript" | "wantsWav">;

/** Owns press/shortcut recording and how the composer presents voice setup errors. */
export function useComposerVoiceInput({ disabled, onTranscribeAudio, onTranscript, wantsWav }: VoiceInputOptions) {
  const { t } = useTranslation();
  const showToast = useToast();
  const [voiceSetupError, setVoiceSetupError] = useState<VoiceRecorderErrorKey | null>(null);
  const [shortcutLabel] = useState(getVoiceShortcutLabel);
  const voiceShortcutDownRef = useRef(false);
  const clearVoiceSetupError = useCallback(() => setVoiceSetupError(null), []);
  const setVoiceError = useCallback((key: VoiceRecorderErrorKey) => {
    // Setup blockers carry instructions users may need to keep in view while fixing them.
    if (key === "insecureContext" || key === "permission" || key === "notConfigured") {
      setVoiceSetupError(key);
      return;
    }
    showToast?.({ message: t(`thread.composer.voiceErrors.${key}`), tone: "error", dedupeKey: "voice-input" });
  }, [showToast, t]);
  const voiceRecorder = useVoiceRecorder({
    disabled,
    onClearError: clearVoiceSetupError,
    onError: setVoiceError,
    onTranscript,
    onTranscribeAudio,
    wantsWav,
  });

  useEffect(() => {
    if (!onTranscribeAudio) return;

    function onKeyDown(event: KeyboardEvent): void {
      if (!isVoiceShortcutDown(event) || event.repeat || voiceShortcutDownRef.current) return;
      event.preventDefault();
      voiceShortcutDownRef.current = true;
      voiceRecorder.beginShortcutHold();
    }

    function onKeyUp(event: KeyboardEvent): void {
      if (!voiceShortcutDownRef.current || !isVoiceShortcutRelease(event)) return;
      event.preventDefault();
      voiceShortcutDownRef.current = false;
      voiceRecorder.endShortcutHold();
    }

    function onWindowBlur(): void {
      if (!voiceShortcutDownRef.current) return;
      voiceShortcutDownRef.current = false;
      voiceRecorder.endShortcutHold();
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onWindowBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onWindowBlur);
    };
  }, [onTranscribeAudio, voiceRecorder.beginShortcutHold, voiceRecorder.endShortcutHold]);

  return {
    recorder: voiceRecorder,
    setupError: voiceSetupError,
    clearSetupError: clearVoiceSetupError,
    shortcutLabel,
    shortcutAria: VOICE_SHORTCUT_ARIA,
    // Includes the interval while the shortcut is held and permission is still pending.
    canSendQueuedPrompt: () => voiceRecorder.state === "idle" && !voiceShortcutDownRef.current,
  };
}
