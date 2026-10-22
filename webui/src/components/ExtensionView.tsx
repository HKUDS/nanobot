import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { normalizeExtensionRequestPath } from "@/lib/extension-client";
import { fetchExtension } from "@/lib/extensions";
import type { WebUIExtensionSummary } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

interface ExtensionViewProps {
  extensionId: string;
}

/**
 * A bidirectional postMessage bridge between the WebUI host and a sandboxed
 * extension iframe.
 *
 * The host holds the WebUI API token and never hands it to the frame.
 * Extensions request data by posting a ``nanobot:request`` message; the host
 * fetches the path (scoped to the extension's own ``/api/extensions/<id>``
 * namespace) and posts back a ``nanobot:response``. This keeps credentials
 * out of third-party extension code while still giving extensions a tiny
 * read-only JSON API surface.
 */
export function ExtensionView({ extensionId }: ExtensionViewProps) {
  const { t } = useTranslation();
  const { getToken } = useClient();
  const [extension, setExtension] = useState<WebUIExtensionSummary | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [failed, setFailed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const extensionRef = useRef<WebUIExtensionSummary | null>(null);
  extensionRef.current = extension;

  useEffect(() => {
    let cancelled = false;
    setExtension(null);
    setNotFound(false);
    setFailed(false);
    fetchExtension(getToken(), extensionId)
      .then((payload) => {
        if (cancelled) return;
        if (!payload) {
          setNotFound(true);
          return;
        }
        setExtension(payload);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [extensionId, getToken]);

  // Serve extension requests scoped to this extension's own API namespace.
  useEffect(() => {
    const onMessage = async (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as
        | { source?: string; type?: string; id?: string; path?: string }
        | null;
      if (
        !data
        || data.source !== "nanobot-webui-extension"
        || data.type !== "nanobot:request"
        || typeof data.id !== "string"
        || typeof data.path !== "string"
      ) {
        return;
      }
      const current = extensionRef.current;
      if (!current) return;
      const prefix = `/api/extensions/${current.id}`;
      const normalizedPath = normalizeExtensionRequestPath(current.id, data.path);
      // Only allow this extension to read its own API namespace.
      if (!normalizedPath.startsWith(prefix + "/") && normalizedPath !== prefix) return;

      const frame = iframeRef.current;
      const respond = (payload: { status: number; ok: boolean; data?: unknown; error?: string }) => {
        frame?.contentWindow?.postMessage(
          { source: "nanobot-webui", type: "nanobot:response", id: data.id, ...payload },
          window.location.origin,
        );
      };
      try {
        const res = await fetch(normalizedPath, {
          headers: { Authorization: `Bearer ${getToken()}` },
          credentials: "same-origin",
          cache: "no-store",
        });
        if (!res.ok) {
          respond({ status: res.status, ok: false, error: `HTTP ${res.status}` });
          return;
        }
        respond({ status: res.status, ok: true, data: await res.json() });
      } catch (error) {
        respond({
          status: 0,
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [getToken]);

  // Pass the manifest to the iframe once it has loaded.
  useEffect(() => {
    const frame = iframeRef.current;
    if (!frame || !extension) return;
    const onLoad = () => {
      try {
        frame.contentWindow?.postMessage(
          { source: "nanobot-webui", type: "nanobot:extension:init", extension },
          window.location.origin,
        );
      } catch {
        // Non-fatal: the extension can render its static UI without metadata.
      }
    };
    frame.addEventListener("load", onLoad);
    return () => frame.removeEventListener("load", onLoad);
  }, [extension]);

  if (failed || notFound) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("extensions.notFound")}
      </div>
    );
  }
  if (!extension) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        …
      </div>
    );
  }
  if (extension.enabled === false) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-sm text-muted-foreground">
        {t("extensions.disabled", { defaultValue: "This extension is disabled." })}
      </div>
    );
  }

  return (
    <iframe
      ref={iframeRef}
      title={extension.name}
      src={`/extensions/${encodeURIComponent(extension.id)}/${extension.entry.replace(/^\.?\//, "")}`}
      sandbox="allow-scripts allow-same-origin"
      referrerPolicy="no-referrer"
      className="h-full w-full border-0 bg-background"
    />
  );
}
