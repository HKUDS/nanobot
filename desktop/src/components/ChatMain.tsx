import React, { useState, useRef, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import {
  CloseIcon,
  ProjectIcon,
  PlusIcon,
  SendIcon,
} from "./Icons";
import MessageBubble from "./MessageBubble";
import type { ChatMessage } from "../hooks/useChat";

interface ChatMainProps {
  sessionKey: string;
  messages: ChatMessage[];
  isLoading: boolean;
  progress: string;
  connected: boolean;
  onSend: (content: string, media?: string[], images?: string[], attachments?: string[]) => void;
  modelLabel?: string;
  providerLabel?: string;
  modelOptions?: Array<{ id: string; name: string; enabled: boolean }>;
  selectedModelId?: string;
  onSelectModel?: (modelId: string) => void;
  modelSwitching?: boolean;
}

interface PendingImage {
  kind: "image" | "file";
  path: string;
  name: string;
  previewUrl?: string;
}

interface ImagePathInfo {
  path: string;
  name: string;
  sizeBytes: number;
  extension: string;
}

interface PreviewImage {
  path: string;
  src: string;
}

interface ComposerDraft {
  inputValue: string;
  pendingImages: PendingImage[];
  attachmentError: string;
}

const emptyDraft = (): ComposerDraft => ({
  inputValue: "",
  pendingImages: [],
  attachmentError: "",
});

const MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024;
const SUPPORTED_IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp"]);

const getMessageDayKey = (timestamp?: string): string => {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
};

const formatMessageDayLabel = (timestamp?: string): string => {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  const todayKey = getMessageDayKey(now.toISOString());
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const yesterdayKey = getMessageDayKey(yesterday.toISOString());
  const dayKey = getMessageDayKey(timestamp);

  if (dayKey === todayKey) return "今天";
  if (dayKey === yesterdayKey) return "昨天";

  return date.toLocaleDateString("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  });
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

const ChatMain: React.FC<ChatMainProps> = ({
  sessionKey,
  messages,
  isLoading,
  progress,
  connected,
  onSend,
  modelLabel,
  providerLabel,
  modelOptions,
  selectedModelId,
  onSelectModel,
  modelSwitching,
}) => {
  const [drafts, setDrafts] = useState<Record<string, ComposerDraft>>({});
  const [dragOver, setDragOver] = useState(false);
  const [previewImage, setPreviewImage] = useState<PreviewImage | null>(null);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const draft = drafts[sessionKey] || emptyDraft();
  const inputValue = draft.inputValue;
  const pendingImages = draft.pendingImages;
  const attachmentError = draft.attachmentError;

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, progress]);

  // Auto-resize textarea
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 200) + "px";
    }
  }, [inputValue]);

  useEffect(() => {
    if (!previewImage) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewImage(null);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [previewImage]);

  useEffect(() => {
    setDragOver(false);
    setPreviewImage(null);
    setModelMenuOpen(false);
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }
  }, [sessionKey]);

  const updateDraft = (updater: (current: ComposerDraft) => ComposerDraft) => {
    setDrafts((prev) => ({
      ...prev,
      [sessionKey]: updater(prev[sessionKey] || emptyDraft()),
    }));
  };

  useEffect(() => {
    if (!modelMenuOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!modelMenuRef.current?.contains(event.target as Node)) {
        setModelMenuOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setModelMenuOpen(false);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [modelMenuOpen]);

  const appendPendingImages = (items: ImagePathInfo[]) => {
    void (async () => {
      const existing = new Set((drafts[sessionKey] || emptyDraft()).pendingImages.map((item) => item.path));
      const nextItems: PendingImage[] = [];
      for (const item of items) {
        const path = normalizeLocalPath(item.path);
        if (!path || existing.has(path)) continue;
        const isImage = SUPPORTED_IMAGE_EXTENSIONS.has(item.extension.toLowerCase());
        let previewUrl: string | undefined;
        if (isImage) {
          previewUrl = await invoke<string>("load_image_preview", {
            input: { path },
          }).catch(() => undefined);
        }
        nextItems.push({
          kind: isImage ? "image" : "file",
          path,
          name: item.name || path.split(/[\\/]/).pop() || path,
          previewUrl,
        });
      }
      updateDraft((current) => ({
        ...current,
        pendingImages: [...current.pendingImages, ...nextItems],
      }));
    })();
  };

  const setAttachmentFeedback = (messages: string[]) => {
    updateDraft((current) => ({
      ...current,
      attachmentError: messages.filter(Boolean).join(" "),
    }));
  };

  const validateImageInfos = (items: ImagePathInfo[]) => {
    const accepted: ImagePathInfo[] = [];
    const rejected: string[] = [];

    for (const item of items) {
      if (item.sizeBytes > MAX_ATTACHMENT_SIZE_BYTES) {
        rejected.push(`${item.name} 超过 20MB`);
        continue;
      }
      accepted.push({
        ...item,
        path: normalizeLocalPath(item.path),
      });
    }

    setAttachmentFeedback(rejected);
    return accepted;
  };

  const inspectAndAppendPaths = async (paths: string[]) => {
    if (paths.length === 0) return;

    const infos = await invoke<ImagePathInfo[]>("inspect_image_paths", {
      input: { paths },
    }).catch(() => []);

    const accepted = validateImageInfos(infos);
    appendPendingImages(accepted);
  };

  const handleSend = () => {
    if ((!inputValue.trim() && pendingImages.length === 0) || isLoading) return;
    const imagePaths = pendingImages.filter((item) => item.kind === "image").map((item) => item.path);
    const attachmentPaths = pendingImages.filter((item) => item.kind === "file").map((item) => item.path);
    onSend(
      inputValue,
      pendingImages.map((image) => image.path),
      imagePaths,
      attachmentPaths,
    );
    updateDraft(() => emptyDraft());
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }
  };

  const handlePickImages = async () => {
    const selected = await open({
      multiple: true,
      title: "选择图片或附件",
    }).catch(() => {
      setAttachmentFeedback(["打开文件选择器失败"]);
      return null;
    });

    if (!selected) return;

    const paths = Array.isArray(selected) ? selected : [selected];
    await inspectAndAppendPaths(paths);
  };

  const handleRemovePendingImage = (path: string) => {
    updateDraft((current) => ({
      ...current,
      pendingImages: current.pendingImages.filter((image) => image.path !== path),
    }));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.key === "Enter" && (e.metaKey || e.ctrlKey)) || (e.key === "Enter" && !e.shiftKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  const handlePaste = async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(e.clipboardData.items || []);
    const imageItems = items.filter((item) => item.type.startsWith("image/"));
    if (imageItems.length === 0) return;

    e.preventDefault();

    const newPaths: string[] = [];
    const rejected: string[] = [];
    for (const item of imageItems) {
      const file = item.getAsFile();
      if (!file) continue;

      if (file.size > MAX_ATTACHMENT_SIZE_BYTES) {
        rejected.push(`${file.name || "粘贴图片"} 超过 20MB`);
        continue;
      }
      if (file.type && !file.type.startsWith("image/")) {
        rejected.push(`${file.name || "粘贴图片"} 格式不支持`);
        continue;
      }

      const nativePath = (file as File & { path?: string }).path;
      if (nativePath) {
        newPaths.push(nativePath);
        continue;
      }

      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("read_failed"));
        reader.readAsDataURL(file);
      }).catch(() => "");

      if (!dataUrl) continue;

      const persistedPath = await invoke<string>("persist_clipboard_image", {
        input: { dataUrl },
      }).catch(() => "");

      if (persistedPath) {
        newPaths.push(persistedPath);
      } else {
        rejected.push(`${file.name || "粘贴图片"} 导入失败`);
      }
    }

    setAttachmentFeedback(rejected);
    await inspectAndAppendPaths(newPaths);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    const hasFiles = Array.from(e.dataTransfer.items || []).some((item) => item.kind === "file");
    if (!hasFiles) return;
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
      setDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);

    const files = Array.from(e.dataTransfer.files || []);
    const acceptedPaths: string[] = [];
    const rejected: string[] = [];

    for (const file of files) {
      if (!file.type.startsWith("image/")) {
        const path = (file as File & { path?: string }).path || "";
        if (path) {
          acceptedPaths.push(path);
        } else {
          rejected.push(`${file.name} 无法读取本地路径`);
        }
        continue;
      }
      if (file.size > MAX_ATTACHMENT_SIZE_BYTES) {
        rejected.push(`${file.name} 超过 20MB`);
        continue;
      }
      const path = (file as File & { path?: string }).path || "";
      if (path) {
        acceptedPaths.push(path);
      } else {
        rejected.push(`${file.name} 无法读取本地路径`);
      }
    }

    setAttachmentFeedback(rejected);
    void inspectAndAppendPaths(acceptedPaths);
  };

  const hasMessages = messages.length > 0;
  const canSend = (!!inputValue.trim() || pendingImages.length > 0) && !isLoading;
  const messageItems = messages.flatMap((msg, index) => {
    const hasRenderableContent = msg.content || (msg.images?.length || 0) > 0 || (msg.attachments?.length || 0) > 0;
    if (!hasRenderableContent) return [];

    const currentDayKey = getMessageDayKey(msg.timestamp);
    const previousDayKey = index > 0 ? getMessageDayKey(messages[index - 1]?.timestamp) : "";
    const items: React.ReactNode[] = [];

    if (currentDayKey && currentDayKey !== previousDayKey) {
      items.push(
        <div key={`day-${msg.id}`} className="chat-date-divider" aria-label={formatMessageDayLabel(msg.timestamp)}>
          <span className="chat-date-divider-label">{formatMessageDayLabel(msg.timestamp)}</span>
        </div>
      );
    }

    items.push(<MessageBubble key={msg.id} message={msg} onPreviewImage={setPreviewImage} />);
    return items;
  });

  return (
    <div className="chat-main">
      {/* Messages / Welcome */}
      <div className="chat-content">
        {!hasMessages ? (
          <div className="chat-welcome">
            <div className="chat-welcome-logo">🐈</div>
            <h1 className="chat-welcome-title">有什么可以帮你的？</h1>
            <p className="chat-welcome-subtitle">
              {connected ? "已连接到 nanobot Gateway" : "正在连接 Gateway..."}
            </p>
          </div>
        ) : (
          <div className="chat-messages">
            {messageItems}

            {/* Loading / Progress */}
            {isLoading && (
              <div className="message-row message-assistant">
                <div className="message-bubble bubble-assistant">
                  {progress ? (
                    <p className="message-progress">{progress}</p>
                  ) : (
                    <div className="typing-indicator">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  )}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          {pendingImages.length > 0 && (
            <div className="chat-attachments">
              {pendingImages.map((image) => (
                <div className="chat-attachment-chip" key={image.path}>
                  {image.kind === "image" && image.previewUrl ? (
                    <img className="chat-attachment-thumb" src={image.previewUrl} alt={image.name} />
                  ) : (
                    <div className="chat-attachment-file-icon">
                      <ProjectIcon />
                    </div>
                  )}
                  <div className="chat-attachment-meta">
                    <span className="chat-attachment-name">{image.name}</span>
                  </div>
                  <button
                    className="chat-attachment-remove"
                    type="button"
                    onClick={() => handleRemovePendingImage(image.path)}
                    title="移除附件"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
          {attachmentError ? <p className="chat-input-error">{attachmentError}</p> : null}
          <div
            className={`chat-input-container ${dragOver ? "drag-over" : ""}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <textarea
              ref={inputRef}
              className="chat-input"
              placeholder="发送消息给 nanobot..."
              value={inputValue}
              onChange={(e) =>
                updateDraft((current) => ({
                  ...current,
                  inputValue: e.target.value,
                }))
              }
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              rows={1}
              disabled={!connected}
            />
            <div className="chat-input-toolbar">
              <div className="chat-input-toolbar-left">
                <button className="chat-input-plus" title="添加附件" type="button" onClick={handlePickImages}>
                  <PlusIcon />
                </button>
                {modelOptions && modelOptions.length > 0 ? (
                  <div className="chat-composer-model-wrap" ref={modelMenuRef}>
                    <button
                      type="button"
                      className="chat-composer-model-switch"
                      disabled={modelSwitching}
                      onClick={() => setModelMenuOpen((prev) => !prev)}
                      title={providerLabel ? `${modelLabel || "nanobot"} · ${providerLabel}` : modelLabel || "nanobot"}
                      aria-haspopup="menu"
                      aria-expanded={modelMenuOpen}
                    >
                      <span className="chat-composer-model-label">{modelLabel || "nanobot"}</span>
                      <span className="chat-composer-model-caret">▾</span>
                    </button>
                    {modelMenuOpen ? (
                      <div className="chat-model-menu chat-model-menu-composer" role="menu">
                        {modelOptions.map((item) => {
                          const isSelected = item.id === selectedModelId;
                          return (
                            <button
                              key={item.id}
                              type="button"
                              role="menuitemradio"
                              aria-checked={isSelected}
                              className={`chat-model-menu-item ${isSelected ? "selected" : ""}`}
                              disabled={!item.enabled || modelSwitching}
                              onClick={() => {
                                setModelMenuOpen(false);
                                if (!isSelected) {
                                  onSelectModel?.(item.id);
                                }
                              }}
                            >
                              <span className="chat-model-menu-check">{isSelected ? "✓" : ""}</span>
                              <span className="chat-model-menu-label">{item.name}</span>
                              {!item.enabled ? <span className="chat-model-menu-meta">停用</span> : null}
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
              <div className="chat-input-actions">
                <button
                  className={`chat-input-send ${canSend ? "active" : ""}`}
                  onClick={handleSend}
                  disabled={!canSend}
                  title="发送"
                >
                  <SendIcon />
                </button>
              </div>
            </div>
          </div>
          <p className="chat-input-hint">支持点击加号选择附件、粘贴截图或拖拽文件到输入框，单个附件限 20MB，支持 Ctrl/Cmd+Enter 发送。</p>
        </div>
      </div>

      {previewImage && (
        <div className="chat-image-preview-backdrop" onClick={() => setPreviewImage(null)}>
          <div className="chat-image-preview-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="chat-image-preview-header">
              <div className="chat-image-preview-meta">
                <span className="chat-image-preview-title">图片预览</span>
                <span className="chat-image-preview-path">{previewImage.path}</span>
              </div>
              <button
                className="chat-image-preview-close"
                type="button"
                onClick={() => setPreviewImage(null)}
                title="关闭预览"
              >
                <CloseIcon />
              </button>
            </div>
            <div className="chat-image-preview-body">
              <img className="chat-image-preview-image" src={previewImage.src} alt="preview" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatMain;
