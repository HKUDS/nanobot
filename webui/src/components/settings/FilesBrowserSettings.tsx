import { useCallback, useEffect, useRef, useState } from "react";
import {
  Download,
  Edit3,
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileJson,
  FileText,
  Folder,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  deleteFile,
  downloadFile,
  fetchFileContent,
  fetchFilesList,
  saveFile,
  uploadFileChunked,
} from "@/lib/api";
import type { FileContentPayload, FileEntry } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export function FilesBrowserSettings() {
  const { t } = useTranslation();
  const { token } = useClient();
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [breadcrumbs, setBreadcrumbs] = useState<string[]>([]);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [previewFile, setPreviewFile] = useState<string | null>(null);
  const uploadPathRef = useRef<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [actionTarget, setActionTarget] = useState<{ path: string; name: string; isDir: boolean } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDir = useCallback(
    async (path: string | null) => {
      setLoading(true);
      setError(null);
      try {
        const payload = await fetchFilesList(token, path);
        if (payload.error) {
          setError(payload.error);
          return;
        }
        setEntries(payload.entries);
        setHasMore(payload.has_more);
        setCurrentPath(path);
        if (path === null) {
          setBreadcrumbs([]);
        } else {
          setBreadcrumbs(path.split("/").filter(Boolean));
        }
      } catch {
        setError(t("settings.files.loadError", { defaultValue: "Failed to load directory." }));
      } finally {
        setLoading(false);
      }
    },
    [token, t],
  );

  useEffect(() => {
    void loadDir(null);
  }, [loadDir]);

  const navigateTo = (index: number) => {
    if (index < 0) {
      void loadDir(null);
    } else {
      const parts = breadcrumbs.slice(0, index + 1);
      void loadDir(parts.join("/"));
    }
  };

  const handleEntryClick = (entry: FileEntry) => {
    if (entry.is_dir) {
      const newPath = currentPath ? `${currentPath}/${entry.name}` : entry.name;
      void loadDir(newPath);
    } else {
      const filePath = currentPath ? `${currentPath}/${entry.name}` : entry.name;
      setPreviewFile(filePath);
    }
  };

  const handleUploadClick = (path: string | null) => {
    const targetPath = path ?? "/";
    uploadPathRef.current = targetPath;
    setUploadError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
      fileInputRef.current.click();
    }
  };

  const handleFileInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    const targetPath = uploadPathRef.current ?? "/";
    console.log("[FilesBrowser] handleFileInputChange", { targetPath, files: files?.length });
    if (!files || files.length === 0) {
      console.log("[FilesBrowser] No files selected");
      return;
    }
    if (!targetPath) {
      console.log("[FilesBrowser] targetPath is empty");
      setUploadError("Upload path is empty");
      return;
    }

    setUploading(true);
    setUploadError(null);
    try {
      for (const file of Array.from(files)) {
        console.log("[FilesBrowser] Uploading:", file.name, file.size, "bytes to", targetPath);
        const buffer = await file.arrayBuffer();
        console.log("[FilesBrowser] buffer size:", buffer.byteLength);
        const result = await uploadFileChunked(token, targetPath, file.name, buffer);
        console.log("[FilesBrowser] uploadFileChunked result:", result);
        if (result.error) {
          console.log("[FilesBrowser] uploadFileChunked error:", result.error);
          setUploadError(result.error);
          return;
        }
      }
      void loadDir(targetPath === "/" ? null : targetPath);
    } catch (err) {
      console.error("[FilesBrowser] upload catch error:", err);
      setUploadError(t("settings.files.uploadError", { defaultValue: "Failed to upload file." }));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDownload = async (entry: FileEntry) => {
    const filePath = currentPath ? `${currentPath}/${entry.name}` : entry.name;
    try {
      const buffer = await downloadFile(token, filePath);
      const blob = new Blob([buffer]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = entry.name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      setError(t("settings.files.downloadError", { defaultValue: "Failed to download file." }));
    }
  };

  const handleDelete = async () => {
    if (!actionTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const result = await deleteFile(token, actionTarget.path);
      if (result.error) {
        setDeleteError(result.error);
        return;
      }
      setActionTarget(null);
      void loadDir(currentPath);
    } catch {
      setDeleteError(t("settings.files.deleteError", { defaultValue: "Failed to delete." }));
    } finally {
      setDeleting(false);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <p className="max-w-[680px] text-[13px] leading-5 text-muted-foreground">
          {t("settings.files.description", {
            defaultValue: "Browse files in the agent workspace directory.",
          })}
        </p>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void loadDir(currentPath)}
            disabled={loading}
            title={t("settings.files.refresh", { defaultValue: "Refresh" })}
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => handleUploadClick(currentPath)}
            disabled={uploading}
            title={t("settings.files.upload", { defaultValue: "Upload" })}
          >
            {uploading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Plus className="h-4 w-4" aria-hidden />
            )}
          </Button>
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileInputChange}
      />

      {uploadError && (
        <div className="rounded-[14px] bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {uploadError}
        </div>
      )}

      {deleteError && (
        <div className="rounded-[14px] bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {deleteError}
        </div>
      )}

      {breadcrumbs.length > 0 && (
        <div className="flex items-center gap-1 overflow-x-auto text-[13px]">
          <button
            type="button"
            onClick={() => navigateTo(-1)}
            className="shrink-0 rounded px-1.5 py-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {t("settings.files.workspace", { defaultValue: "Workspace" })}
          </button>
          {breadcrumbs.map((part, i) => (
            <span key={i} className="flex items-center gap-1">
              <span className="text-muted-foreground/40">/</span>
              <button
                type="button"
                onClick={() => navigateTo(i)}
                className={cn(
                  "shrink-0 rounded px-1.5 py-0.5 transition-colors",
                  i === breadcrumbs.length - 1
                    ? "font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {part}
              </button>
            </span>
          ))}
        </div>
      )}

      {loading && entries.length === 0 ? (
        <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("settings.files.loading", { defaultValue: "Loading..." })}
        </div>
      ) : error ? (
        <div className="rounded-[14px] bg-destructive/10 px-4 py-4 text-sm text-destructive">
          {error}
        </div>
      ) : entries.length === 0 ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          {t("settings.files.empty", { defaultValue: "This directory is empty." })}
        </div>
      ) : (
        <div className="space-y-0.5">
          {entries.map((entry) => (
            <FileRow
              key={entry.name}
              entry={entry}
              onClick={() => handleEntryClick(entry)}
              onDelete={() => {
                const path = currentPath ? `${currentPath}/${entry.name}` : entry.name;
                setActionTarget({ path, name: entry.name, isDir: entry.is_dir });
              }}
              onDownload={() => handleDownload(entry)}
              formatSize={formatSize}
            />
          ))}
          {hasMore && (
            <div className="py-2 text-center text-[12px] text-muted-foreground">
              {t("settings.files.truncated", { defaultValue: "Directory listing truncated." })}
            </div>
          )}
        </div>
      )}

      <FilePreviewSheet path={previewFile} onClose={() => setPreviewFile(null)} />

      <DeleteConfirmDialog
        target={actionTarget}
        onClose={() => setActionTarget(null)}
        onConfirm={handleDelete}
        deleting={deleting}
      />
    </div>
  );
}

function FileRow({
  entry,
  onClick,
  onDelete,
  onDownload,
  formatSize,
}: {
  entry: FileEntry;
  onClick: () => void;
  onDelete: () => void;
  onDownload: () => void;
  formatSize: (bytes: number) => string;
}) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      className="group flex w-full min-w-0 items-center gap-1 rounded-[14px] px-3 py-2 transition-colors hover:bg-muted/40"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        onClick={onClick}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
      >
        <FileEntryIcon name={entry.name} isDir={entry.is_dir} />
        <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-foreground/90">
          {entry.name}
        </span>
        {!entry.is_dir && (
          <span className="shrink-0 text-[12px] text-muted-foreground">
            {formatSize(entry.size)}
          </span>
        )}
      </button>

      <div
        className={cn(
          "flex items-center gap-0.5 transition-opacity",
          hovered ? "opacity-100" : "opacity-0 pointer-events-none",
        )}
      >
        {!entry.is_dir && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={(e) => { e.stopPropagation(); onDownload(); }}
            title="Download"
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-destructive/70 hover:text-destructive"
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          title="Delete"
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
        </Button>
      </div>
    </div>
  );
}

function DeleteConfirmDialog({
  target,
  onClose,
  onConfirm,
  deleting,
}: {
  target: { path: string; name: string; isDir: boolean } | null;
  onClose: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  const { t } = useTranslation();

  return (
    <Dialog open={!!target} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-sm gap-0 overflow-hidden p-0">
        <div className="flex items-start gap-3 px-5 pt-5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-destructive/10">
            <Trash2 className="h-5 w-5 text-destructive" aria-hidden />
          </div>
          <div className="min-w-0 flex-1 pt-1">
            <DialogTitle className="text-[16px] font-semibold text-foreground">
              {t("settings.files.deleteTitle", { defaultValue: "Delete {{name}}?", name: target?.name ?? "" })}
            </DialogTitle>
            <DialogDescription className="mt-1 text-[13px] text-muted-foreground">
              {target?.isDir
                ? t("settings.files.deleteDirHint", { defaultValue: "The directory must be empty." })
                : t("settings.files.deleteFileHint", { defaultValue: "This action cannot be undone." })}
            </DialogDescription>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-4">
          <Button variant="ghost" onClick={onClose} disabled={deleting}>
            {t("settings.files.cancel", { defaultValue: "Cancel" })}
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={deleting}>
            {deleting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              t("settings.files.delete", { defaultValue: "Delete" })
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function FileEntryIcon({ name, isDir }: { name: string; isDir: boolean }) {
  if (isDir) return <Folder className="h-4 w-4 shrink-0 text-amber-500" aria-hidden />;

  const lower = name.toLowerCase();
  if (/\.(png|jpg|jpeg|gif|svg|webp|bmp|ico)$/.test(lower))
    return <FileImage className="h-4 w-4 shrink-0 text-green-500" aria-hidden />;
  if (/\.(mp3|wav|ogg|m4a|flac|aac)$/.test(lower))
    return <FileAudio className="h-4 w-4 shrink-0 text-purple-500" aria-hidden />;
  if (/\.(zip|tar|gz|rar|7z)$/.test(lower))
    return <FileArchive className="h-4 w-4 shrink-0 text-orange-500" aria-hidden />;
  if (/\.(py|js|ts|tsx|jsx|go|rs|java|c|cpp|h|hpp|sh|rb)$/.test(lower))
    return <FileCode className="h-4 w-4 shrink-0 text-blue-400" aria-hidden />;
  if (/\.(json|jsonl)$/.test(lower))
    return <FileJson className="h-4 w-4 shrink-0 text-yellow-500" aria-hidden />;
  if (/\.(md|txt)$/.test(lower))
    return <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />;

  return <File className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />;
}

function FilePreviewSheet({
  path,
  onClose,
}: {
  path: string | null;
  onClose: () => void;
}) {
  const { token } = useClient();
  const { t } = useTranslation();
  const [content, setContent] = useState<FileContentPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) {
      setContent(null);
      setEditing(false);
      setEditValue("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setContent(null);
    setEditing(false);
    setEditValue("");
    setSaveError(null);
    void fetchFileContent(token, path)
      .then((payload) => {
        if (cancelled) return;
        if (payload.error) {
          setError(payload.error);
        } else {
          setContent(payload);
        }
      })
      .catch(() => {
        if (!cancelled) setError(t("settings.files.previewError", { defaultValue: "Failed to load file." }));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, token, t]);

  const handleEdit = () => {
    if (!content) return;
    setEditing(true);
    setEditValue(content.content);
  };

  const handleSave = async () => {
    if (!path || !content) return;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await saveFile(token, path, editValue);
      if (result.error) {
        setSaveError(result.error);
        return;
      }
      setEditing(false);
      setContent({ ...content, content: editValue });
    } catch {
      setSaveError(t("settings.files.saveError", { defaultValue: "Failed to save file." }));
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setEditing(false);
    setEditValue("");
    setSaveError(null);
  };

  return (
    <Dialog open={!!path} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        className="max-w-[min(80vw,80rem)] max-h-[85vh] flex flex-col overflow-hidden p-0 gap-0"
        showCloseButton={false}
      >
        <DialogHeader className="flex-row items-center justify-between border-b border-border/45 px-5 py-3.5 shrink-0">
          <div className="min-w-0 flex-1">
            <DialogTitle className="truncate text-[14px] font-semibold text-foreground">
              {path ?? ""}
            </DialogTitle>
            {content && (
              <DialogDescription className="sr-only">
                {content.language} · {content.size} bytes{content.truncated ? " · " + t("settings.files.truncated", { defaultValue: "Truncated" }) : ""}{editing ? " · " + t("settings.files.editing", { defaultValue: "Editing" }) : ""}
              </DialogDescription>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0 ml-2">
            {editing ? (
              <>
                <Button variant="ghost" size="icon" onClick={handleCancel} disabled={saving}>
                  <X className="h-4 w-4" aria-hidden />
                </Button>
                <Button variant="default" size="icon" onClick={handleSave} disabled={saving}>
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Save className="h-4 w-4" aria-hidden />
                  )}
                </Button>
              </>
            ) : (
              <>
                <Button variant="ghost" size="icon" onClick={handleEdit} disabled={loading || !!error}>
                  <Edit3 className="h-4 w-4" aria-hidden />
                </Button>
                <Button variant="ghost" size="icon" onClick={onClose}>
                  <X className="h-4 w-4" aria-hidden />
                </Button>
              </>
            )}
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-auto p-5">
          {loading ? (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t("settings.files.loading", { defaultValue: "Loading..." })}
            </div>
          ) : error ? (
            <div className="rounded-[14px] bg-destructive/10 px-4 py-4 text-sm text-destructive">
              {error}
            </div>
          ) : content ? (
            editing ? (
              <>
                <textarea
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  className={cn(
                    "w-full min-h-[60vh] rounded-[14px] border border-border/35 bg-muted/20 p-4",
                    "font-mono text-[12.5px] leading-[1.75] text-foreground/80 resize-none",
                    "focus:outline-none focus:ring-2 focus:ring-ring",
                  )}
                  spellCheck={false}
                />
                {saveError && (
                  <div className="mt-3 rounded-[14px] bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {saveError}
                  </div>
                )}
              </>
            ) : (
              <pre
                className={cn(
                  "whitespace-pre-wrap break-words rounded-[14px] border border-border/35 bg-muted/20 p-4",
                  "font-mono text-[12.5px] leading-[1.75] text-foreground/80",
                )}
              >
                {content.content}
              </pre>
            )
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
