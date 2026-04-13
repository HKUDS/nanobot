import React, { useEffect, useMemo, useState } from "react";
import { CloseIcon, ClockIcon, EditIcon, PlusIcon, RefreshIcon, SaveIcon, TrashIcon } from "./Icons";

interface CronPageProps {
  gatewayUrl: string;
}

interface CronServiceStatus {
  enabled: boolean;
  jobs: number;
  next_wake_at_ms: number | null;
}

interface CronJob {
  id: string;
  name: string;
  enabled: boolean;
  deleteAfterRun: boolean;
  schedule: {
    kind: "at" | "every" | "cron";
    atMs: number | null;
    everyMs: number | null;
    expr: string | null;
    tz: string | null;
  };
  payload: {
    message: string;
    deliver: boolean;
    channel: string | null;
    to: string | null;
  };
  state: {
    nextRunAtMs: number | null;
    lastRunAtMs: number | null;
    lastStatus: "ok" | "error" | "skipped" | null;
    lastError: string | null;
  };
  createdAtMs: number;
  updatedAtMs: number;
}

type IntervalUnit = "minutes" | "hours" | "days";
type CronFilter = "all" | "enabled" | "disabled" | "at" | "every" | "cron";

interface CronDraft {
  id?: string;
  name: string;
  message: string;
  enabled: boolean;
  kind: "at" | "every" | "cron";
  atLocal: string;
  everyValue: number;
  everyUnit: IntervalUnit;
  cronExpr: string;
  tz: string;
  deleteAfterRun: boolean;
  deliver: boolean;
  channel: string;
  to: string;
}

const emptyDraft = (): CronDraft => ({
  name: "",
  message: "",
  enabled: true,
  kind: "every",
  atLocal: "",
  everyValue: 1,
  everyUnit: "hours",
  cronExpr: "0 9 * * *",
  tz: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai",
  deleteAfterRun: false,
  deliver: false,
  channel: "",
  to: "",
});

const formatDateTime = (timestamp: number | null | undefined) => {
  if (!timestamp) return "未计划";
  return new Date(timestamp).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const formatSchedule = (job: CronJob) => {
  if (job.schedule.kind === "at") {
    return `一次性 · ${formatDateTime(job.schedule.atMs)}`;
  }
  if (job.schedule.kind === "every") {
    const everyMs = job.schedule.everyMs || 0;
    if (everyMs % (24 * 60 * 60 * 1000) === 0) return `每 ${everyMs / (24 * 60 * 60 * 1000)} 天`;
    if (everyMs % (60 * 60 * 1000) === 0) return `每 ${everyMs / (60 * 60 * 1000)} 小时`;
    if (everyMs % (60 * 1000) === 0) return `每 ${everyMs / (60 * 1000)} 分钟`;
    return `每 ${Math.floor(everyMs / 1000)} 秒`;
  }
  return `Cron · ${job.schedule.expr}${job.schedule.tz ? ` · ${job.schedule.tz}` : ""}`;
};

const intervalMs = (value: number, unit: IntervalUnit) => {
  if (unit === "days") return value * 24 * 60 * 60 * 1000;
  if (unit === "hours") return value * 60 * 60 * 1000;
  return value * 60 * 1000;
};

const draftFromJob = (job: CronJob): CronDraft => {
  let everyValue = 1;
  let everyUnit: IntervalUnit = "hours";
  if (job.schedule.kind === "every" && job.schedule.everyMs) {
    const ms = job.schedule.everyMs;
    if (ms % (24 * 60 * 60 * 1000) === 0) {
      everyValue = ms / (24 * 60 * 60 * 1000);
      everyUnit = "days";
    } else if (ms % (60 * 60 * 1000) === 0) {
      everyValue = ms / (60 * 60 * 1000);
      everyUnit = "hours";
    } else {
      everyValue = Math.max(1, Math.floor(ms / (60 * 1000)));
      everyUnit = "minutes";
    }
  }

  return {
    id: job.id,
    name: job.name,
    message: job.payload.message,
    enabled: job.enabled,
    kind: job.schedule.kind,
    atLocal: job.schedule.atMs ? new Date(job.schedule.atMs).toISOString().slice(0, 16) : "",
    everyValue,
    everyUnit,
    cronExpr: job.schedule.expr || "0 9 * * *",
    tz: job.schedule.tz || Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai",
    deleteAfterRun: job.deleteAfterRun,
    deliver: job.payload.deliver,
    channel: job.payload.channel || "",
    to: job.payload.to || "",
  };
};

const cronPresets = [
  { label: "每天 9:00", expr: "0 9 * * *" },
  { label: "工作日 10:00", expr: "0 10 * * 1-5" },
  { label: "每周一 09:30", expr: "30 9 * * 1" },
  { label: "每月 1 号 09:00", expr: "0 9 1 * *" },
];

const cronFilterItems: Array<{ key: CronFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "enabled", label: "已启用" },
  { key: "disabled", label: "已停用" },
  { key: "at", label: "一次性" },
  { key: "every", label: "间隔" },
  { key: "cron", label: "Cron" },
];

const readableCronPreview = (expr: string, tz: string) => {
  const normalized = expr.trim().replace(/\s+/g, " ");
  const parts = normalized.split(" ");
  if (parts.length !== 5) {
    return "Cron 预览暂仅支持标准 5 段表达式";
  }

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
  const timeLabel = minute !== "*" && hour !== "*" ? `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}` : null;

  if (normalized === "0 9 * * *") return `每天 09:00 执行${tz ? ` · ${tz}` : ""}`;
  if (normalized === "0 10 * * 1-5") return `工作日 10:00 执行${tz ? ` · ${tz}` : ""}`;
  if (normalized === "30 9 * * 1") return `每周一 09:30 执行${tz ? ` · ${tz}` : ""}`;
  if (normalized === "0 9 1 * *") return `每月 1 号 09:00 执行${tz ? ` · ${tz}` : ""}`;
  if (dayOfMonth === "*" && month === "*" && dayOfWeek === "*" && timeLabel) return `每天 ${timeLabel} 执行${tz ? ` · ${tz}` : ""}`;
  if (dayOfMonth === "*" && month === "*" && dayOfWeek === "1-5" && timeLabel) return `工作日 ${timeLabel} 执行${tz ? ` · ${tz}` : ""}`;
  if (dayOfMonth === "*" && month === "*" && /^[0-6]$/.test(dayOfWeek) && timeLabel) {
    const weekdayMap = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    return `每${weekdayMap[Number(dayOfWeek)]} ${timeLabel} 执行${tz ? ` · ${tz}` : ""}`;
  }
  if (/^\d+$/.test(dayOfMonth) && month === "*" && dayOfWeek === "*" && timeLabel) {
    return `每月 ${dayOfMonth} 号 ${timeLabel} 执行${tz ? ` · ${tz}` : ""}`;
  }
  return `Cron: ${normalized}${tz ? ` · ${tz}` : ""}`;
};

const normalizeFetchError = (error: unknown) => {
  const text = error instanceof Error ? error.message : String(error || "");
  if (/load failed|failed to fetch|networkerror|network error/i.test(text)) {
    return "无法连接到 Gateway。请先确认 nanobot gateway 已启动，并重启到包含 /api/cron 接口的最新版本。";
  }
  return text || "请求失败";
};

const CronPage: React.FC<CronPageProps> = ({ gatewayUrl }) => {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [status, setStatus] = useState<CronServiceStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [draft, setDraft] = useState<CronDraft>(emptyDraft);
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedResultId, setExpandedResultId] = useState("");
  const [activeFilter, setActiveFilter] = useState<CronFilter>("all");

  const httpUrl = useMemo(
    () => gatewayUrl.replace("ws://", "http://").replace("wss://", "https://"),
    [gatewayUrl]
  );

  const loadJobs = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await fetch(`${httpUrl}/api/cron`);
      const contentType = res.headers.get("content-type") || "";
      const poweredBy = res.headers.get("x-powered-by") || "";
      const data = contentType.includes("application/json") ? await res.json().catch(() => ({})) : {};
      if (!res.ok) {
        if (res.status === 401 && /express/i.test(poweredBy)) {
          throw new Error(`当前地址 ${httpUrl} 返回的是其他本地服务（Express 401），不是 nanobot gateway。请在设置里确认 Gateway WebSocket 地址。`);
        }
        throw new Error(data.error || "读取定时任务失败");
      }
      if (!contentType.includes("application/json")) {
        throw new Error(`当前地址 ${httpUrl} 没有返回 nanobot 所需的 JSON 接口，请确认 Gateway 地址是否正确。`);
      }
      setJobs(data.jobs || []);
      setStatus(data.status || null);
      setError("");
    } catch (nextError) {
      setJobs([]);
      setStatus(null);
      setError(normalizeFetchError(nextError));
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    void loadJobs();
    const timer = window.setInterval(() => void loadJobs(true), 15000);
    return () => window.clearInterval(timer);
  }, [httpUrl]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 1800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const filteredJobs = jobs.filter((job) => {
    const query = searchQuery.trim().toLowerCase();
    const matchesQuery =
      job.name.toLowerCase().includes(query) ||
      job.payload.message.toLowerCase().includes(query) ||
      (job.schedule.expr || "").toLowerCase().includes(query) ||
      job.id.toLowerCase().includes(query);

    const matchesFilter =
      activeFilter === "all" ||
      (activeFilter === "enabled" && job.enabled) ||
      (activeFilter === "disabled" && !job.enabled) ||
      job.schedule.kind === activeFilter;

    return (query ? matchesQuery : true) && matchesFilter;
  });

  const openCreate = () => {
    setDraft(emptyDraft());
    setEditorOpen(true);
  };

  const openEdit = (job: CronJob) => {
    setDraft(draftFromJob(job));
    setEditorOpen(true);
  };

  const submitDraft = async () => {
    if (!draft.name.trim()) {
      setError("任务名称不能为空");
      return;
    }
    if (!draft.message.trim()) {
      setError("执行内容不能为空");
      return;
    }

    const schedule =
      draft.kind === "at"
        ? {
            kind: "at",
            atMs: new Date(draft.atLocal).getTime(),
          }
        : draft.kind === "every"
          ? {
              kind: "every",
              everyMs: intervalMs(draft.everyValue, draft.everyUnit),
            }
          : {
              kind: "cron",
              expr: draft.cronExpr,
              tz: draft.tz.trim() || null,
          };

    if (draft.kind === "at" && (!draft.atLocal || Number.isNaN(schedule.atMs))) {
      setError("请选择有效的一次性执行时间");
      return;
    }

    if (draft.kind === "every" && draft.everyValue <= 0) {
      setError("间隔执行的数值必须大于 0");
      return;
    }

    if (draft.kind === "cron" && !draft.cronExpr.trim()) {
      setError("Cron 表达式不能为空");
      return;
    }

    const payload = {
      name: draft.name.trim(),
      enabled: draft.enabled,
      deleteAfterRun: draft.kind === "at" ? draft.deleteAfterRun : false,
      schedule,
      payload: {
        message: draft.message.trim(),
        deliver: draft.deliver,
        channel: draft.channel.trim() || null,
        to: draft.to.trim() || null,
      },
    };

    setActionLoadingId(draft.id || "create");
    try {
      const res = await fetch(
        draft.id ? `${httpUrl}/api/cron/${draft.id}` : `${httpUrl}/api/cron`,
        {
          method: draft.id ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || "保存定时任务失败");
      }
      setEditorOpen(false);
      setNotice(draft.id ? "定时任务已更新" : "定时任务已创建");
      await loadJobs();
    } catch (nextError) {
      setError(normalizeFetchError(nextError));
    } finally {
      setActionLoadingId("");
    }
  };

  const runAction = async (jobId: string, action: "run" | "delete" | "toggle", enabled?: boolean) => {
    setActionLoadingId(jobId);
    try {
      const res = await fetch(
        action === "run"
          ? `${httpUrl}/api/cron/${jobId}/run`
          : action === "toggle"
            ? `${httpUrl}/api/cron/${jobId}/enable`
            : `${httpUrl}/api/cron/${jobId}`,
        {
          method: action === "run" ? "POST" : action === "toggle" ? "POST" : "DELETE",
          headers: { "Content-Type": "application/json" },
          body: action === "toggle" ? JSON.stringify({ enabled }) : undefined,
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || "操作失败");
      }
      setNotice(
        action === "run" ? "任务已立即执行" : action === "delete" ? "任务已删除" : enabled ? "任务已启用" : "任务已停用"
      );
      await loadJobs();
    } catch (nextError) {
      setError(normalizeFetchError(nextError));
    } finally {
      setActionLoadingId("");
    }
  };

  return (
    <main className="cron-page">
      <div className="cron-page-header">
        <div>
          <h1 className="cron-page-title">任务调度中心</h1>
          <p className="cron-page-subtitle">接入 nanobot 的真实 cron 服务，支持创建、编辑、启停、立即执行与删除。</p>
        </div>
        <div className="cron-page-header-actions">
          <button className="cron-icon-btn cron-header-icon-btn" type="button" onClick={() => void loadJobs()} title="刷新任务列表">
            <RefreshIcon />
          </button>
          <button className="cron-icon-btn cron-header-icon-btn primary" type="button" onClick={openCreate} title="新建任务">
            <PlusIcon />
          </button>
        </div>
      </div>

      <div className="cron-page-summary">
        <div className="cron-summary-card">
          <span className="cron-summary-label">服务状态</span>
          <strong>{status?.enabled ? "运行中" : "未运行"}</strong>
        </div>
        <div className="cron-summary-card">
          <span className="cron-summary-label">任务总数</span>
          <strong>{status?.jobs ?? jobs.length}</strong>
        </div>
        <div className="cron-summary-card">
          <span className="cron-summary-label">下一次唤醒</span>
          <strong>{formatDateTime(status?.next_wake_at_ms)}</strong>
        </div>
      </div>

      {notice ? <div className="cron-notice">{notice}</div> : null}
      {error ? <div className="cron-error">{error}</div> : null}

      <div className="cron-toolbar">
        <div className="cron-search-box">
          <input
            className="settings-input"
            type="text"
            placeholder="搜索任务名称、内容、Cron 表达式或 ID"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className="cron-toolbar-meta">{filteredJobs.length} / {jobs.length} 个任务</div>
      </div>

      <div className="cron-filter-row">
        {cronFilterItems.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`cron-filter-chip ${activeFilter === item.key ? "active" : ""}`}
            onClick={() => setActiveFilter(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="cron-jobs-panel">
        {loading ? (
          <div className="settings-empty-card">正在加载定时任务...</div>
        ) : filteredJobs.length === 0 ? (
          <div className="settings-empty-card">{jobs.length === 0 ? "当前还没有定时任务，可以先创建一个。" : "没有匹配的定时任务。"}</div>
        ) : (
          <div className="cron-jobs-list">
            {filteredJobs.map((job) => (
              <article className="cron-job-card" key={job.id}>
                <div className="cron-job-main">
                  <div className="cron-job-head">
                    <div className="cron-job-title-wrap">
                      <strong>{job.name}</strong>
                      <span className={`settings-mini-pill ${job.enabled ? "enabled" : "disabled"}`}>
                        {job.enabled ? "已启用" : "已停用"}
                      </span>
                      <span className="settings-mini-pill">{job.schedule.kind}</span>
                    </div>
                    <div className="cron-job-actions">
                      <label className="settings-switch">
                        <input
                          type="checkbox"
                          checked={job.enabled}
                          onChange={(event) => void runAction(job.id, "toggle", event.target.checked)}
                          disabled={actionLoadingId === job.id}
                        />
                        <span />
                      </label>
                      <button className="cron-icon-btn" type="button" title="编辑任务" onClick={() => openEdit(job)}>
                        <EditIcon />
                      </button>
                      <button
                        className="cron-icon-btn"
                        type="button"
                        title="立即执行"
                        onClick={() => void runAction(job.id, "run")}
                        disabled={actionLoadingId === job.id}
                      >
                        <ClockIcon />
                      </button>
                      <button
                        className="cron-icon-btn danger"
                        type="button"
                        title="删除任务"
                        onClick={() => void runAction(job.id, "delete")}
                        disabled={actionLoadingId === job.id}
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  </div>
                  <p className="cron-job-message">{job.payload.message}</p>
                  <div className="cron-job-meta">
                    <span>计划: {formatSchedule(job)}</span>
                    <span>下次执行: {formatDateTime(job.state.nextRunAtMs)}</span>
                    <span>上次执行: {formatDateTime(job.state.lastRunAtMs)}</span>
                    <span>结果: {job.state.lastStatus || "未执行"}</span>
                    {job.payload.deliver ? <span>投递: {job.payload.channel || "unknown"} / {job.payload.to || "-"}</span> : null}
                  </div>
                  <div className="cron-job-subactions">
                    <button
                      className="cron-link-btn"
                      type="button"
                      onClick={() => setExpandedResultId((prev) => (prev === job.id ? "" : job.id))}
                    >
                      {expandedResultId === job.id ? "收起执行详情" : "查看执行详情"}
                    </button>
                    <span className="cron-job-id">ID: {job.id}</span>
                  </div>
                  {expandedResultId === job.id && (
                    <div className="cron-job-result-panel">
                      <div className="cron-job-result-row">
                        <span>最后状态</span>
                        <strong>{job.state.lastStatus || "未执行"}</strong>
                      </div>
                      <div className="cron-job-result-row">
                        <span>最后执行时间</span>
                        <strong>{formatDateTime(job.state.lastRunAtMs)}</strong>
                      </div>
                      <div className="cron-job-result-row">
                        <span>下次执行时间</span>
                        <strong>{formatDateTime(job.state.nextRunAtMs)}</strong>
                      </div>
                      <div className="cron-job-result-row">
                        <span>创建时间</span>
                        <strong>{formatDateTime(job.createdAtMs)}</strong>
                      </div>
                      <div className="cron-job-result-row">
                        <span>更新时间</span>
                        <strong>{formatDateTime(job.updatedAtMs)}</strong>
                      </div>
                      {job.state.lastError ? (
                        <div className="cron-job-result-error">{job.state.lastError}</div>
                      ) : (
                        <div className="cron-job-result-empty">最近一次执行没有错误信息。</div>
                      )}
                    </div>
                  )}
                  {job.state.lastError ? <div className="cron-job-error">{job.state.lastError}</div> : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {editorOpen && (
        <div className="settings-dialog-backdrop" onClick={() => setEditorOpen(false)}>
          <div className="settings-dialog cron-editor-dialog" onClick={(event) => event.stopPropagation()}>
            <div className="settings-dialog-header">
              <div className="settings-dialog-heading">
                <div className="settings-dialog-title">{draft.id ? "编辑定时任务" : "新建定时任务"}</div>
                <div className="settings-dialog-path">支持一次性、间隔和 Cron 表达式三种调度方式。</div>
              </div>
              <div className="settings-section-actions">
                <button className="cron-icon-btn" type="button" onClick={submitDraft} title="保存任务">
                  <SaveIcon />
                </button>
                <button className="cron-icon-btn" type="button" onClick={() => setEditorOpen(false)} title="关闭">
                  <CloseIcon />
                </button>
              </div>
            </div>
            <div className="settings-dialog-body cron-editor-body">
              {error ? <div className="cron-editor-error">{error}</div> : null}
              <div className="cron-editor-stack">
                <section className="cron-editor-section">
                  <div className="cron-editor-section-title">基础信息</div>
                  <div className="cron-editor-grid">
                    <label className="cron-field">
                      <span>任务名称</span>
                      <input className="settings-input" value={draft.name} onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))} />
                    </label>
                    <div className="cron-field">
                      <span>启用任务</span>
                      <div className="cron-inline-switch">
                        <label className="settings-switch">
                          <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft((prev) => ({ ...prev, enabled: e.target.checked }))} />
                          <span />
                        </label>
                        <span className="cron-inline-switch-label">{draft.enabled ? "已启用" : "已停用"}</span>
                      </div>
                    </div>
                  </div>
                </section>

                <section className="cron-editor-section">
                  <div className="cron-editor-section-title">调度方式</div>
                  <div className="cron-editor-grid">
                    <label className="cron-field">
                      <span>调度类型</span>
                      <div className="settings-select-wrap">
                        <select className="settings-select" value={draft.kind} onChange={(e) => setDraft((prev) => ({ ...prev, kind: e.target.value as CronDraft["kind"] }))}>
                          <option value="every">间隔执行</option>
                          <option value="cron">Cron 表达式</option>
                          <option value="at">一次性执行</option>
                        </select>
                      </div>
                    </label>

                    {draft.kind === "every" && (
                      <>
                        <label className="cron-field">
                          <span>间隔数值</span>
                          <input
                            type="number"
                            min={1}
                            className="settings-input"
                            value={draft.everyValue}
                            onChange={(e) => setDraft((prev) => ({ ...prev, everyValue: Math.max(1, Number(e.target.value) || 1) }))}
                          />
                        </label>
                        <label className="cron-field">
                          <span>间隔单位</span>
                          <div className="settings-select-wrap">
                            <select className="settings-select" value={draft.everyUnit} onChange={(e) => setDraft((prev) => ({ ...prev, everyUnit: e.target.value as IntervalUnit }))}>
                              <option value="minutes">分钟</option>
                              <option value="hours">小时</option>
                              <option value="days">天</option>
                            </select>
                          </div>
                        </label>
                      </>
                    )}

                    {draft.kind === "cron" && (
                      <>
                        <label className="cron-field cron-field-full">
                          <span>Cron 表达式</span>
                          <input className="settings-input settings-mono-input" value={draft.cronExpr} onChange={(e) => setDraft((prev) => ({ ...prev, cronExpr: e.target.value }))} />
                          <div className="cron-preset-list">
                            {cronPresets.map((preset) => (
                              <button
                                key={preset.expr}
                                type="button"
                                className="cron-preset-btn"
                                onClick={() => setDraft((prev) => ({ ...prev, cronExpr: preset.expr }))}
                              >
                                {preset.label}
                              </button>
                            ))}
                          </div>
                          <div className="cron-preview-note">{readableCronPreview(draft.cronExpr, draft.tz)}</div>
                        </label>
                        <label className="cron-field cron-field-full">
                          <span>时区</span>
                          <input className="settings-input" value={draft.tz} onChange={(e) => setDraft((prev) => ({ ...prev, tz: e.target.value }))} />
                        </label>
                      </>
                    )}

                    {draft.kind === "at" && (
                      <>
                        <label className="cron-field cron-field-full">
                          <span>执行时间</span>
                          <input type="datetime-local" className="settings-input" value={draft.atLocal} onChange={(e) => setDraft((prev) => ({ ...prev, atLocal: e.target.value }))} />
                        </label>
                        <div className="cron-field">
                          <span>执行后删除</span>
                          <div className="cron-inline-switch">
                            <label className="settings-switch">
                              <input type="checkbox" checked={draft.deleteAfterRun} onChange={(e) => setDraft((prev) => ({ ...prev, deleteAfterRun: e.target.checked }))} />
                              <span />
                            </label>
                            <span className="cron-inline-switch-label">{draft.deleteAfterRun ? "执行后自动删除" : "执行后保留记录"}</span>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </section>

                <section className="cron-editor-section">
                  <div className="cron-editor-section-title">执行内容</div>
                  <label className="cron-field cron-field-full">
                    <span>任务说明</span>
                    <textarea
                      className="settings-textarea cron-textarea"
                      value={draft.message}
                      onChange={(e) => setDraft((prev) => ({ ...prev, message: e.target.value }))}
                    />
                  </label>
                </section>

                <section className="cron-editor-section">
                  <div className="cron-editor-section-title">投递设置</div>
                  <div className="cron-editor-grid">
                    <div className="cron-field">
                      <span>执行后投递结果</span>
                      <div className="cron-inline-switch">
                        <label className="settings-switch">
                          <input type="checkbox" checked={draft.deliver} onChange={(e) => setDraft((prev) => ({ ...prev, deliver: e.target.checked }))} />
                          <span />
                        </label>
                        <span className="cron-inline-switch-label">{draft.deliver ? "已开启" : "未开启"}</span>
                      </div>
                    </div>
                    <label className="cron-field">
                      <span>投递通道</span>
                      <input className="settings-input" value={draft.channel} onChange={(e) => setDraft((prev) => ({ ...prev, channel: e.target.value }))} placeholder="desktop / telegram / feishu..." />
                    </label>
                    <label className="cron-field cron-field-full">
                      <span>投递目标</span>
                      <input className="settings-input" value={draft.to} onChange={(e) => setDraft((prev) => ({ ...prev, to: e.target.value }))} placeholder="chat_id / phone / room id" />
                    </label>
                  </div>
                </section>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
};

export default CronPage;
