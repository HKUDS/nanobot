import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { installThreadSync } from "@/lib/thread-sync";
import "./index.css";
import App from "./App.tsx";

// Sync assistant-ui local thread IDs with server-generated session IDs.
installThreadSync();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TooltipProvider>
      <App />
    </TooltipProvider>
  </StrictMode>,
);
