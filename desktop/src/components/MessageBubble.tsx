import React, { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../hooks/useChat";
import { CheckIcon, CopyIcon, ProjectIcon } from "./Icons";

interface MessageBubbleProps {
  message: ChatMessage;
  onPreviewImage?: (image: { path: string; src: string }) => void;
}

const MessageBubble: React.FC<MessageBubbleProps> = ({ message, onPreviewImage }) => {
  const [copied, setCopied] = useState(false);
  const copyText = async (text: string): Promise<boolean> => {
    if (!text) return false;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      // Fall through to the legacy copy path for desktop webviews.
    }

    try {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "true");
      textarea.style.position = "fixed";
      textarea.style.top = "-9999px";
      textarea.style.left = "-9999px";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      const ok = document.execCommand("copy");
      document.body.removeChild(textarea);
      return ok;
    } catch {
      return false;
    }
  };

  const normalizeLocalPath = (rawPath: string): string => {
    if (!rawPath) return "";
    try {
      if (rawPath.startsWith("file://")) {
        const url = new URL(rawPath);
        return decodeURIComponent(url.pathname);
      }
      return decodeURIComponent(rawPath);
    } catch {
      return rawPath;
    }
  };

  const isUser = message.role === "user";
  const [imageSources, setImageSources] = useState<Array<{ path: string; src: string }>>([]);
  const attachments = (message.attachments || []).map((path) => ({
    path,
    name: path.split(/[\\/]/).pop() || path,
  }));

  useEffect(() => {
    const paths = (message.images || []).map(normalizeLocalPath).filter(Boolean);
    if (paths.length === 0) {
      setImageSources([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      const previews = await Promise.all(
        paths.map(async (path) => {
          const src = await invoke<string>("load_image_preview", {
            input: { path },
          }).catch(() => "");
          return src ? { path, src } : null;
        })
      );
      if (!cancelled) {
        setImageSources(previews.filter((item): item is { path: string; src: string } => Boolean(item)));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [message.images]);

  useEffect(() => {
    setCopied(false);
  }, [message.content]);

  const handleCopyMessage = async () => {
    if (!message.content) return;
    try {
      const ok = await copyText(message.content);
      if (!ok) {
        setCopied(false);
        return;
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={`message-row ${isUser ? "message-user" : "message-assistant"}`}>
      <div className={`message-stack ${isUser ? "message-stack-user" : "message-stack-assistant"}`}>
        <div className={`message-bubble ${isUser ? "bubble-user" : "bubble-assistant"}`}>
          {imageSources.length > 0 && (
            <div className="message-images">
              {imageSources.map((image) => (
                <button
                  key={image.path}
                  className="message-image-link"
                  title={image.path}
                  type="button"
                  onClick={() => onPreviewImage?.(image)}
                >
                  <img className="message-image" src={image.src} alt="attachment" loading="lazy" />
                </button>
              ))}
            </div>
          )}
          {attachments.length > 0 && (
            <div className="message-attachments">
              {attachments.map((attachment) => (
                <div key={attachment.path} className="message-attachment-item" title={attachment.path}>
                  <ProjectIcon className="message-attachment-icon" />
                  <span className="message-attachment-name">{attachment.name}</span>
                </div>
              ))}
            </div>
          )}
          {isUser ? (
            message.content ? <p className="message-text">{message.content}</p> : null
          ) : (
            <div className="message-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className || "");
                    const isInline = !match && !className;
                    if (isInline) {
                      return (
                        <code className="inline-code" {...props}>
                          {children}
                        </code>
                      );
                    }
                    return (
                      <div className="code-block-wrapper">
                        <div className="code-block-header">
                          <span className="code-block-lang">{match?.[1] || "code"}</span>
                          <button
                            className="code-copy-btn"
                            onClick={async () => {
                              const text = String(children).replace(/\n$/, "");
                              await copyText(text);
                            }}
                          >
                            Copy
                          </button>
                        </div>
                        <pre className="code-block-pre">
                          <code className={className} {...props}>
                            {children}
                          </code>
                        </pre>
                      </div>
                    );
                  },
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {message.content ? (
          <div className="message-actions">
            <button
              type="button"
              className={`message-copy-btn ${copied ? "is-copied" : ""}`}
              onClick={handleCopyMessage}
              aria-label={copied ? (isUser ? "已复制提问消息" : "已复制整条回答") : isUser ? "复制提问消息" : "复制整条回答"}
              title={copied ? "已复制" : "复制"}
            >
              {copied ? <CheckIcon className="message-copy-icon" /> : <CopyIcon className="message-copy-icon" />}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default MessageBubble;
