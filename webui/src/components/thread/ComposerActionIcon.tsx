import { ModelsIcon, StopIcon } from "@/components/icons/product-icons";
import { LoadingRing } from "@/components/ui/loading-ring";

export type ComposerActionState = "voice" | "recording" | "busy" | "stop" | "setup" | "send";

export function ComposerActionIcon({ state }: { state: ComposerActionState }) {
  return (
    <span className="composer-action-icons pointer-events-none relative block h-7 w-7 shrink-0" data-state={state} aria-hidden="true">
      <span className="composer-action-glyph" data-action-icon="voice" data-active={state === "voice" || undefined}>
        <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="9.5" y="4.75" width="5" height="9.5" rx="2.5" fill="currentColor" />
          <path d="M7 11.25v.5a5 5 0 0 0 10 0v-.5M12 16.75v2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </span>
      <span className="composer-action-glyph" data-action-icon="send" data-active={state === "send" || undefined}>
        <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="m8.25 10.25 3.75-3.75 3.75 3.75M12 7v10.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span className="composer-action-glyph" data-action-icon="stop" data-active={state === "stop" || undefined}>
        <LoadingRing track={false} strokeDasharray="12 50.8" className="absolute h-6 w-6 text-foreground/50" strokeWidth="1.5" />
        <svg className="h-6 w-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <rect x="8" y="8" width="8" height="8" rx="1.75" />
        </svg>
      </span>
      <span className="composer-action-glyph" data-action-icon="recording" data-active={state === "recording" || undefined}>
        <StopIcon className="h-3.5 w-3.5" fill="currentColor" />
      </span>
      <span className="composer-action-glyph" data-action-icon="busy" data-active={state === "busy" || undefined}>
        <LoadingRing className="h-4 w-4" />
      </span>
      <span className="composer-action-glyph" data-action-icon="setup" data-active={state === "setup" || undefined}>
        <ModelsIcon className="h-4 w-4" />
      </span>
    </span>
  );
}
