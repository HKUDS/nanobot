import { useRef } from "react";
import { ExternalLink, Sparkle, Star, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import starInvitation from "@/assets/star-invitation.webp";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

import "./StarPrompt.css";

const REPOSITORY_URL = "https://github.com/HKUDS/nanobot";
const actionClassName = "h-full min-h-[46px] min-w-0 !whitespace-normal px-3 py-2.5 text-center text-[15px] font-medium max-[480px]:text-sm";

export function StarLinkView({ onActivate, error = false, fullWidth = false }: {
  onActivate: () => void;
  error?: boolean;
  fullWidth?: boolean;
}) {
  const { t } = useTranslation();
  const link = (
    <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer"
      className={fullWidth ? undefined : "inline-flex min-h-10 items-center justify-center gap-2 rounded-control px-2 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"}
      onClick={onActivate} onAuxClick={(event) => { if (event.button === 1) onActivate(); }}>
      {!fullWidth && <Star className="h-4 w-4 shrink-0" aria-hidden />}
      <span className="min-w-0">
        {t(fullWidth ? "starPrompt.action" : "starPrompt.footerAction")}
      </span>
      {fullWidth ? (
        <span className="star-prompt-decoration" aria-hidden="true">
          <Star className="star-prompt-star" size={23} strokeWidth={1.5} fill="currentColor" />
          <Sparkle className="star-prompt-sparkle star-prompt-sparkle-first" size={10} strokeWidth={1.5} fill="currentColor" />
          <Sparkle className="star-prompt-sparkle star-prompt-sparkle-second" size={7} strokeWidth={1.5} fill="currentColor" />
        </span>
      ) : <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />}
    </a>
  );
  return (
    <>
      {fullWidth ? <Button asChild className={`star-prompt-action relative isolate w-full overflow-visible ${actionClassName}`}>{link}</Button> : link}
      {error && <p role="alert" className="text-sm text-destructive">{t("starPrompt.saveError")}</p>}
    </>
  );
}

export function StarPromptView({ open, saving, error, starError = false, onOpenChange, onDismissForever, onStar, onCloseAutoFocus }: {
  open: boolean;
  saving: boolean;
  error: boolean;
  starError?: boolean;
  onOpenChange: (open: boolean) => void;
  onDismissForever: () => void;
  onStar: () => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const { t } = useTranslation();
  const titleRef = useRef<HTMLHeadingElement | null>(null);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false}
        className="flex max-h-[calc(100dvh-32px)] max-w-[520px] flex-col gap-0 overflow-y-auto overscroll-contain p-5 pb-2.5 outline-none max-[480px]:p-4 max-[480px]:pb-2"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          titleRef.current?.focus({ preventScroll: true });
        }} onCloseAutoFocus={onCloseAutoFocus}>
        <img src={starInvitation} alt="" width={1672} height={941} draggable={false}
          className="aspect-[1672/941] w-full shrink-0 select-none rounded-control bg-muted object-cover" />
        <DialogClose aria-label={t("common.close")}
          className="absolute right-[23px] top-[23px] grid h-11 w-11 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-white max-[480px]:right-[18px] max-[480px]:top-[18px]">
          <span className="grid h-[30px] w-[30px] place-items-center rounded-full bg-black/40 text-white backdrop-blur-sm transition-colors hover:bg-black/60 motion-reduce:transition-none">
            <X size={18} strokeWidth={1.75} aria-hidden />
          </span>
        </DialogClose>
        <div className="shrink-0 px-2 pt-[27px] text-left max-[480px]:px-1 max-[480px]:pt-[23px]">
          <DialogTitle ref={titleRef} tabIndex={-1}
            className="text-[26px] font-semibold leading-[1.4] tracking-[-0.035em] outline-none [overflow-wrap:anywhere] max-[480px]:text-[clamp(18px,5.6vw,24px)]">
            {t("starPrompt.title")}
          </DialogTitle>
          <DialogDescription className="mt-[15px] text-[15px] leading-[1.9] text-muted-foreground max-[480px]:mt-3 max-[480px]:text-[13px] max-[480px]:leading-[1.95]">
            <span className="block">{t("starPrompt.intro")}</span>{" "}
            <span className="block">{t("starPrompt.invitation")}</span>{" "}
            <span className="block">{t("starPrompt.thanks")}</span>
          </DialogDescription>
        </div>
        <div className="mt-[27px] grid shrink-0 grid-cols-2 items-stretch gap-3 px-2 max-[480px]:mt-[23px] max-[480px]:gap-2.5 max-[480px]:px-1">
          <Button variant="outline" className={actionClassName}
            onClick={() => onOpenChange(false)}>{t("starPrompt.later")}</Button>
          <div className="flex min-w-0 flex-col gap-2">
            <StarLinkView fullWidth error={starError} onActivate={onStar} />
          </div>
        </div>
        <Button variant="ghost" className="mt-[7px] min-h-11 shrink-0 self-center !whitespace-normal px-4 text-xs font-normal text-muted-foreground" disabled={saving}
          onClick={() => void onDismissForever()}>{t("starPrompt.never")}</Button>
        {error && <p role="alert" className="text-sm text-destructive">{t("starPrompt.saveError")}</p>}
      </DialogContent>
    </Dialog>
  );
}
