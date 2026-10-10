import { useRef, useState } from "react";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { initializeWebui, WebuiSetupError } from "@/lib/bootstrap";

type SetupError = "required" | "mismatch" | "invalidPassword" | "localOnly" | "saveFailed";

export function WebuiSetupForm({
  onInitialized,
  onAlreadyInitialized,
}: {
  onInitialized: (password: string) => void;
  onAlreadyInitialized: () => void;
}) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const confirmationRef = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<SetupError | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    const secret = password.trim();
    if (!secret || Array.from(secret).length > 1024 || secret.includes("${")) {
      setError(secret ? "invalidPassword" : "required");
      inputRef.current?.focus();
      return;
    }
    if (secret !== confirmation.trim()) {
      setError("mismatch");
      confirmationRef.current?.focus();
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await initializeWebui(secret);
      onInitialized(secret);
    } catch (err) {
      if (err instanceof WebuiSetupError && err.code === "already_initialized") {
        onAlreadyInitialized();
        return;
      }
      setError(err instanceof WebuiSetupError && err.code === "invalid_password"
        ? "invalidPassword"
        : err instanceof WebuiSetupError && err.code === "local_only"
          ? "localOnly"
          : "saveFailed");
      setSubmitting(false);
    }
  };

  return (
    <main className="flex h-full w-full flex-col overflow-y-auto bg-background">
      <div className="mx-5 mt-5 shrink-0 self-end sm:mx-8">
        <LanguageSwitcher className="h-8 min-w-0 gap-2 px-3 text-xs" />
      </div>
      <div className="flex flex-1 shrink-0 items-center justify-center px-6 pb-20 pt-8">
        <section aria-labelledby="webui-setup-title" className="w-full max-w-xs">
          <div className="text-center">
            <img src="/brand/nanobot_mark.svg" alt="" width={56} height={56} draggable={false} className="mx-auto mb-5 h-14 w-14 select-none" />
            <h1 id="webui-setup-title" className="text-balance text-2xl font-semibold tracking-tight text-foreground sm:text-[1.75rem]">
              {t("app.setup.title")}
            </h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">{t("app.setup.description")}</p>
          </div>
          <form onSubmit={(event) => void submit(event)} className="mt-7 space-y-4">
            <div>
              <label htmlFor="webui-setup-password" className="mb-2 block text-sm font-medium">{t("app.auth.label")}</label>
              <div className="relative">
                <Input
                  ref={inputRef}
                  id="webui-setup-password"
                  name="webui-setup-password"
                  type={passwordVisible ? "text" : "password"}
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => { setPassword(event.target.value); setError(null); }}
                  disabled={submitting}
                  aria-invalid={error === "required" || error === "invalidPassword" ? true : undefined}
                  aria-describedby={error ? "webui-setup-error" : undefined}
                  className="h-12 rounded-full border-foreground/15 bg-muted/30 px-4 pr-12 text-base"
                  autoFocus
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={submitting}
                  aria-label={t(passwordVisible ? "app.auth.hidePassword" : "app.auth.showPassword")}
                  aria-controls="webui-setup-password webui-setup-confirmation"
                  aria-pressed={passwordVisible}
                  onClick={() => setPasswordVisible((visible) => !visible)}
                  className="absolute right-1 top-1/2 h-10 w-10 -translate-y-1/2 rounded-full text-muted-foreground hover:text-foreground"
                >
                  {passwordVisible ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
                </Button>
              </div>
            </div>
            <div>
              <label htmlFor="webui-setup-confirmation" className="mb-2 block text-sm font-medium">{t("app.setup.confirmPassword")}</label>
              <Input
                ref={confirmationRef}
                id="webui-setup-confirmation"
                name="webui-setup-confirmation"
                type={passwordVisible ? "text" : "password"}
                autoComplete="new-password"
                value={confirmation}
                onChange={(event) => { setConfirmation(event.target.value); setError(null); }}
                disabled={submitting}
                aria-invalid={error === "mismatch" ? true : undefined}
                aria-describedby={error ? "webui-setup-error" : undefined}
                className="h-12 rounded-full border-foreground/15 bg-muted/30 px-4 text-base"
              />
            </div>
            {error ? <p id="webui-setup-error" role="alert" className="text-sm leading-5 text-destructive">{t(`app.setup.${error}`)}</p> : null}
            <Button type="submit" disabled={submitting} className="h-12 w-full rounded-full">
              {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : null}
              {t(submitting ? "app.setup.submitting" : "app.setup.submit")}
            </Button>
          </form>
        </section>
      </div>
    </main>
  );
}
