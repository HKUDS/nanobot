import { useEffect, useState } from "react";
import type { NanobotClient } from "@/lib/nanobot-client";

export function useRuntimeControls(client: NanobotClient): boolean {
  const [available, setAvailable] = useState(client.supportsRuntimeControls);
  useEffect(() => {
    const update = () => setAvailable(client.supportsRuntimeControls);
    const status = client.onStatus(update);
    const ready = client.onReady(update);
    update();
    return () => { status(); ready(); };
  }, [client]);
  return available;
}
