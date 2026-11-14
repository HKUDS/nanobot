import { flushSync } from "react-dom";

import "./session-transition.css";

let active: ViewTransition | null = null;
let pending: (() => void) | null = null;

export function finishSessionTransition(): void {
  const update = pending;
  pending = null;
  active?.skipTransition();
  active = null;
  delete document.documentElement.dataset.sessionTransition;
  if (update) flushSync(update);
}

export function transitionSession(update: () => void, animate = true): void {
  pending = update;
  active?.skipTransition();
  const root = document.documentElement;
  if (!animate || !document.startViewTransition
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches
    || root.hasAttribute("data-theme-snapshot")) {
    active = null;
    pending = null;
    delete root.dataset.sessionTransition;
    update();
    return;
  }

  root.dataset.sessionTransition = "";
  const transition = document.startViewTransition(() => {
    if (pending !== update) return;
    pending = null;
    flushSync(update);
  });
  active = transition;
  // Skipped captures still run their update; only the latest navigation may commit.
  void transition.ready.catch(() => {});
  const release = () => {
    if (active !== transition) return;
    active = null;
    delete root.dataset.sessionTransition;
  };
  void transition.finished.then(release, release);
}
