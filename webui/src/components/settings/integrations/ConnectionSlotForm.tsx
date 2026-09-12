import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ConnectionSlot, ConnectionSlotUpdate } from "@/lib/integrations";

export function ConnectionSlotForm({ title, config, busy, onSave }: {
  title: string;
  config: ConnectionSlot;
  busy: boolean;
  onSave: (value: ConnectionSlotUpdate) => Promise<boolean>;
}) {
  const id = useId();
  const [url, setUrl] = useState(config.base_url);
  const [password, setPassword] = useState("");
  return (
    <form aria-label={`Konfiguracja ${title}`} className="space-y-4 p-4 sm:p-5" onSubmit={(event) => {
      event.preventDefault();
      if (busy) return;
      const value = { base_url: url.trim(), ...(password.trim() ? { password } : {}) };
      setPassword("");
      void onSave(value);
    }}>
      <p className="text-[13px] leading-6 text-muted-foreground">
        Miejsce na integrację — adapter nie jest jeszcze zainstalowany. Zapis nie łączy się z usługą.
        Docelowo tylko odczyt; bez transakcji i zmian danych finansowych.
      </p>
      <div className="space-y-2">
        <label htmlFor={`${id}-url`} className="text-sm">Adres {title}</label>
        <Input id={`${id}-url`} type="url" value={url} maxLength={2048} disabled={busy}
          placeholder="https://…" onChange={(e) => setUrl(e.target.value)} />
      </div>
      <div className="space-y-2">
        <label htmlFor={`${id}-token`} className="text-sm">Token {title} (opcjonalny)</label>
        <Input id={`${id}-token`} type="password" autoComplete="new-password" value={password}
          maxLength={8192} disabled={busy} onChange={(e) => setPassword(e.target.value)} />
        <p className="text-xs text-muted-foreground">
          {config.credential_configured ? "Token zapisany; puste pole zachowuje sekret." : "Brak zapisanego tokenu."}
          {" "}Sekret trafia do prywatnego magazynu, nie do config.json.
        </p>
      </div>
      <Button type="submit" disabled={busy}>Zapisz miejsce {title}</Button>
    </form>
  );
}
