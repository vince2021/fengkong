import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { NotificationRecord, OperationsSummary } from "./types";

type Notice = { kind: "error" | "success"; text: string };

export default function OperationsCenter({ canViewOperations, canViewNotifications, canScan, onNotice }: { canViewOperations: boolean; canViewNotifications: boolean; canScan: boolean; onNotice: (notice: Notice) => void }) {
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryResult, notificationRows] = await Promise.all([
        canViewOperations ? api.operationsSummary() : Promise.resolve(null),
        canViewNotifications ? api.notifications(unreadOnly) : Promise.resolve([]),
      ]);
      setSummary(summaryResult);
      setNotifications(notificationRows);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "运营数据加载失败" });
    } finally {
      setLoading(false);
    }
  }, [canViewNotifications, canViewOperations, onNotice, unreadOnly]);

  useEffect(() => { void reload(); }, [reload]);

  async function scan() {
    setScanning(true);
    try {
      const result = await api.runSlaScan();
      await reload();
      onNotice({ kind: "success", text: `扫描 ${result.active_cases_scanned} 笔申请，新增 ${result.notifications_created} 条通知` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "SLA 扫描失败" });
    } finally { setScanning(false); }
  }

  async function markRead(item: NotificationRecord) {
    try {
      await api.markNotificationRead(item.id);
      await reload();
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "通知处理失败" }); }
  }

  if (!canViewOperations && !canViewNotifications) return <div className="panel operations-empty"><strong>当前身份无运营监控权限</strong><p>请切换为业务处理、风控、审计或运营角色。</p></div>;
  if (loading && !summary && !notifications.length) return <div className="panel operations-loading">正在汇总 SLA 与通知数据…</div>;

  return <div className="operations-center">
    <section className="operations-hero">
      <div><span>RISK OPERATIONS</span><h2>SLA 运营监控与升级催办</h2><p>定时识别即将超时、已超时及持续超时申请，按办理角色分级通知并形成审计证据。</p></div>
      {canScan && <button className="primary-button" disabled={scanning} onClick={() => void scan()}>{scanning ? "正在扫描…" : "立即运行 SLA 扫描"}</button>}
    </section>

    {summary && <>
      <section className="ops-metric-grid">
        <OpsMetric label="活跃申请" value={summary.active_cases} detail={`累计申请 ${summary.total_cases} 笔`} tone="blue" />
        <OpsMetric label="即将超时" value={summary.sla.due_soon} detail="进入环节时限后 25%" tone="amber" />
        <OpsMetric label="已经超时" value={summary.sla.overdue} detail="需立即催办责任角色" tone="red" />
        <OpsMetric label="升级处置" value={summary.sla.escalated} detail="持续超时超过 4 小时" tone="purple" />
        <OpsMetric label="未读通知" value={summary.unread_notifications.total} detail={`${summary.unread_notifications.critical} 条严重通知`} tone="teal" unit="条" />
      </section>
      <section className="panel ops-stage-panel">
        <div className="ops-section-head"><div><span>STAGE DISTRIBUTION</span><h2>活跃申请环节分布</h2></div><small>{summary.last_scan ? `最近扫描 ${formatTime(summary.last_scan.run_at)} · 新增 ${summary.last_scan.notifications_created} 条` : `尚未执行扫描 · 汇总于 ${formatTime(summary.generated_at)}`}</small></div>
        <StageDistribution rows={summary.stage_distribution} />
      </section>
    </>}

    {canViewNotifications && <section className="panel notification-panel">
      <div className="ops-section-head"><div><span>INBOX</span><h2>我的催办通知</h2></div><label className="unread-toggle"><input type="checkbox" checked={unreadOnly} onChange={(event) => setUnreadOnly(event.target.checked)} />仅看未读</label></div>
      {notifications.length ? <div className="notification-list">{notifications.map((item) => <div className={`notification-item ${item.severity} ${item.status}`} key={item.id}><div className="notification-symbol">{item.level === "escalated" ? "!!" : item.level === "overdue" ? "!" : "◷"}</div><div className="notification-body"><div><strong>{item.title}</strong><span>{levelLabel(item.level)}</span></div><p>{item.message}</p><footer><code>{item.case_id}</code><small>{formatTime(item.created_at)}</small></footer></div><div className="notification-actions">{item.status === "unread" ? <button onClick={() => void markRead(item)}>标记已读</button> : <span>已读</span>}</div></div>)}</div> : <div className="notification-empty"><span>✓</span><strong>当前没有{unreadOnly ? "未读" : ""}催办通知</strong><p>SLA 扫描产生的新通知会按当前角色出现在这里。</p></div>}
    </section>}
  </div>;
}

function OpsMetric({ label, value, detail, tone, unit = "笔" }: { label: string; value: number; detail: string; tone: string; unit?: string }) { return <div className={`ops-metric ${tone}`}><span>{label}</span><strong>{value}<small>{unit}</small></strong><p>{detail}</p><i /></div>; }

function StageDistribution({ rows }: { rows: OperationsSummary["stage_distribution"] }) {
  const max = useMemo(() => Math.max(1, ...rows.map((item) => item.count)), [rows]);
  return rows.length ? <div className="stage-distribution">{rows.map((item) => <div key={item.stage}><span>{item.label}</span><div><i style={{ width: `${(item.count / max) * 100}%` }} /></div><strong>{item.count}</strong></div>)}</div> : <div className="notification-empty compact"><strong>暂无活跃申请</strong></div>;
}

function levelLabel(level: NotificationRecord["level"]): string { return level === "due_soon" ? "即将超时" : level === "overdue" ? "已超时" : "升级催办"; }
function formatTime(value: string | null): string { return value ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "—"; }
