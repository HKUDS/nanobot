const KEYBOARD_NAVIGATION_KEYS = new Set([
  "Tab",
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Home",
  "End",
  "PageUp",
  "PageDown",
  "Enter",
  " ",
]);

const NON_TEXT_INPUT_TYPES = new Set([
  "button",
  "checkbox",
  "color",
  "file",
  "image",
  "radio",
  "range",
  "reset",
  "submit",
]);

function isTextEntryElement(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLTextAreaElement || target.isContentEditable) return true;
  if (target instanceof HTMLInputElement) {
    return !NON_TEXT_INPUT_TYPES.has((target.type || "text").toLowerCase());
  }
  return false;
}

function isKeyboardFocusKey(event: KeyboardEvent): boolean {
  if (event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return false;
  if (!KEYBOARD_NAVIGATION_KEYS.has(event.key)) return false;
  if (isTextEntryElement(event.target)) {
    if (event.key === "Tab") return true;
    return event.key === "Enter" && event.target instanceof HTMLInputElement;
  }
  return true;
}

interface InstalledModality {
  count: number;
  teardown: () => void;
}

const installedDocuments = new WeakMap<Document, InstalledModality>();

/** Mark a keyboard action handled by a control outside the shared navigation keys. */
export function markKeyboardFocus(doc: Document): void {
  doc.documentElement.dataset.focusModality = "keyboard";
}

/**
 * Track whether the user is navigating by keyboard or pointer on `html[data-focus-modality]`.
 *
 * Browsers widen native `:focus-visible` on any keyboard event (such as holding Shift while
 * clicking, Shift + wheel scrolling, pressing Escape, or triggering shortcuts). Gating focus
 * indicators on explicit keyboard navigation keys prevents stray focus outlines during pointer
 * workflows while keeping full keyboard accessibility.
 */
export function installFocusModality(doc: Document = document): () => void {
  const existing = installedDocuments.get(doc);
  if (existing) {
    existing.count += 1;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      existing.count -= 1;
      if (existing.count === 0) {
        existing.teardown();
        installedDocuments.delete(doc);
      }
    };
  }

  const root = doc.documentElement;
  const previous = root.dataset.focusModality;
  if (!previous) root.dataset.focusModality = "pointer";

  const setPointer = () => {
    root.dataset.focusModality = "pointer";
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (isKeyboardFocusKey(event)) markKeyboardFocus(doc);
  };

  doc.addEventListener("pointerdown", setPointer, { capture: true, passive: true });
  doc.addEventListener("mousedown", setPointer, { capture: true, passive: true });
  doc.addEventListener("touchstart", setPointer, { capture: true, passive: true });
  doc.addEventListener("keydown", onKeyDown, { capture: true });

  const entry: InstalledModality = {
    count: 1,
    teardown: () => {
      doc.removeEventListener("pointerdown", setPointer, { capture: true });
      doc.removeEventListener("mousedown", setPointer, { capture: true });
      doc.removeEventListener("touchstart", setPointer, { capture: true });
      doc.removeEventListener("keydown", onKeyDown, { capture: true });
      if (previous === undefined) delete root.dataset.focusModality;
      else root.dataset.focusModality = previous;
    },
  };
  installedDocuments.set(doc, entry);

  let released = false;
  return () => {
    if (released) return;
    released = true;
    entry.count -= 1;
    if (entry.count === 0) {
      entry.teardown();
      installedDocuments.delete(doc);
    }
  };
}
