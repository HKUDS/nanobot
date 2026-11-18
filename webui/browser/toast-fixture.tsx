import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ToastCard, ToastProvider, ToastViewport, useToast, type ToastNotice } from "@/components/ui/toast";
import "./toast-fixture.css";

const scenes = ["copied", "copy-failed", "archive", "unarchive", "batch-archive", "delete", "delete-failed", "batch", "stack", "restart"] as const;
type Scene = typeof scenes[number];

function SceneContent({ scene }: { scene: Scene }) {
  const { t, i18n } = useTranslation();
  const chinese = i18n.language === "zh-CN";
  const sceneLabels: Record<Scene, string> = chinese ? {
    copied: "复制成功", "copy-failed": "复制失败", archive: "归档", unarchive: "取消归档", "batch-archive": "批量归档",
    delete: "删除", "delete-failed": "删除失败", batch: "批量删除", stack: "通知叠放", restart: "重启完成",
  } : {
    copied: "Copied", "copy-failed": "Copy failed", archive: "Archive", unarchive: "Unarchive", "batch-archive": "Batch archive",
    delete: "Delete", "delete-failed": "Delete failed", batch: "Batch delete", stack: "Stacked toasts", restart: "Restart complete",
  };
  const showToast = useToast();
  const [undone, setUndone] = useState(false);
  const [committed, setCommitted] = useState(false);
  const isRemoval = scene === "unarchive" ? undone : ["delete", "batch", "stack", "archive", "batch-archive"].includes(scene) && !undone;
  const topicNames = chinese ? ["研究笔记", "组件备忘", "测试记录"] : ["Research notes", "Component notes", "Test notes"];
  if (scene === "delete" && new URLSearchParams(location.search).has("long-title")) {
    topicNames[0] = chinese ? "研究笔记：跨平台布局和键盘可访问性验证记录" : "Research notes: cross-platform layout and keyboard accessibility verification";
  }
  const action = { label: t("toast.undo"), run: () => { setUndone(true); setCommitted(false); } };
  const copy: ToastNotice = { message: t("fileActions.copied"), tone: "success", dedupeKey: "copied" };
  const deletion: ToastNotice = {
    message: scene === "batch" ? t("toast.pendingDelete", { count: 3 }) : t("toast.pendingDeleteSingle"),
    detail: scene === "batch" ? undefined : topicNames[0],
    tone: "pending", action, onExpire: () => setCommitted(true),
  };
  const notices: Record<Scene, ToastNotice[]> = {
    copied: [copy],
    "copy-failed": [{ message: t("fileActions.failed"), tone: "error", dedupeKey: "copy-failed" }],
    archive: [{ message: t("toast.archivedSingle"), detail: topicNames[0], tone: "success", action }],
    unarchive: [{ message: t("toast.unarchivedSingle"), detail: topicNames[0], tone: "success", action }],
    "batch-archive": [{ message: t("toast.archived", { count: 3 }), tone: "success", action }],
    delete: [deletion],
    "delete-failed": [{ message: t("toast.deleteFailedSingle"), tone: "error" }],
    batch: [deletion],
    stack: [deletion, copy],
    restart: [{ message: t("app.restart.completed", { seconds: "2.4" }), tone: "success", dedupeKey: "restart-completed" }],
  };
  const [sample, setSample] = useState(true);
  return (
    <main className="toast-review" data-stack={scene === "stack" || undefined}>
        <aside className="toast-review-sidebar">
          <div className="toast-review-brand"><img src="/brand/nanobot_mark.svg" alt="" />nanobot</div>
          <p aria-current="page">{chinese ? "视觉审查" : "WebUI design review"}</p>
          <p>{chinese ? "发布记录" : "Release notes"}</p>
          {!isRemoval && topicNames.slice(0, scene === "batch" || scene === "batch-archive" ? 3 : 1).map((name) => <p key={name}>{name}</p>)}
        </aside>
        <section className="toast-review-main">
          <h1>{chinese ? "Toast 视觉样例" : "Toast fixtures"}</h1>
          <p className="toast-review-description">{chinese ? "打开时样例会停住，方便审查。点「播放计时」体验暂停和撤销。这里不会发送网关请求。" : "The initial sample is held for visual review. Play it to test the timer, pause and undo. No gateway requests are sent."}</p>
          <nav aria-label={chinese ? "Toast 样例" : "Toast examples"} className="toast-review-nav">
            {scenes.map((item) => {
              const url = new URL(location.href);
              url.searchParams.set("scene", item);
              return <a key={item} href={url.href} aria-current={scene === item ? "page" : undefined}>{sceneLabels[item]}</a>;
            })}
          </nav>
          <div className="toast-review-actions">
            <Button variant="outline" size="sm" onClick={() => {
              setSample(false);
              setUndone(false);
              setCommitted(false);
              for (const notice of notices[scene]) showToast?.(notice);
            }}>{chinese ? "播放计时" : "Play timing"}</Button>
            {undone && <p>{chinese ? "已撤销" : "Undo applied"}</p>}
            {committed && <p>{chinese ? "模拟删除完成" : "Simulated delete committed"}</p>}
          </div>
        </section>
      {sample && <ToastViewport>{notices[scene].map((notice) => (
        <ToastCard key={notice.message} notice={notice} paused
          onAction={() => { notice.action?.run(); setSample(false); }} />
      ))}</ToastViewport>}
    </main>
  );
}

export function ToastFixture({ parameters }: { parameters: URLSearchParams }) {
  const scene = scenes.find((candidate) => candidate === parameters.get("scene")) ?? "copied";
  document.documentElement.classList.toggle("dark", parameters.has("dark"));
  return <ToastProvider><SceneContent scene={scene} /></ToastProvider>;
}
