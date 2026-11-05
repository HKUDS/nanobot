import type { HTMLAttributes } from "react";

const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock"]);

/** Preserve keyboard focus cues without treating Shift + wheel as navigation. */
export const surfaceFocusProps = {
  onFocusCapture(event) {
    if (event.target !== event.currentTarget) return;
    if (event.currentTarget.matches(":focus-visible")) event.currentTarget.dataset.keyboardFocus = "true";
    else delete event.currentTarget.dataset.keyboardFocus;
  },
  onBlurCapture(event) {
    if (event.target === event.currentTarget) delete event.currentTarget.dataset.keyboardFocus;
  },
  onPointerDownCapture(event) {
    delete event.currentTarget.dataset.keyboardFocus;
  },
  onKeyDownCapture(event) {
    if (event.target === event.currentTarget && !MODIFIER_KEYS.has(event.key)
      && !event.ctrlKey && !event.metaKey && !event.altKey) event.currentTarget.dataset.keyboardFocus = "true";
  },
} satisfies HTMLAttributes<HTMLElement>;
