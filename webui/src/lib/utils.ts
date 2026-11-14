import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      borderRadius: ["mark", "compact", "control", "floating", "panel", "modal", "prominent"],
    },
    classGroups: {
      "font-size": [{ text: ["ui", "ui-label", "ui-heading", "ui-body", "control-label", "caption", "title", "reading", "reading-small", "code", "code-dense", "composer"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
