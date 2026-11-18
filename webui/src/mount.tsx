import ReactDOM from "react-dom/client";
import App from "./App";
import type { preloadInitialBootstrap } from "./lib/initial-bootstrap";

export function mountWebui(container: HTMLElement, takeInitialBootstrap: ReturnType<typeof preloadInitialBootstrap>) {
  /* StrictMode disabled: dev double-invokes state updaters; delta accumulation must stay pure — see useNanobotStream. */
  ReactDOM.createRoot(container).render(<App takeInitialBootstrap={takeInitialBootstrap} />);
}
