import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { DocumentCorrection, DocumentCorrectionTask, NotificationRecord, OperationsSummary, PersonalTask, PersonalTaskQueue, SlaScanExecution, SlaScanHistory, SlaScanRun, TaskAction, TeamTask, TeamTaskBoard } from "./types";

type Notice = { kind: "error" | "success"; text: string };

export default function OperationsCenter({ canViewTasks, canViewOperations, canManageTasks, canViewNotifications, canScan, canActCorrections, onNavigate, onNotice }: { canViewTasks: boolean; canViewOperations: boolean; canManageTasks: boolean; canViewNotifications: boolean; canScan: boolean; canActCorrections: boolean; onNavigate: (action: TaskAction) => void; onNotice: (notice: Notice) => void }) {
  const [taskQueue, setTaskQueue] = useState<PersonalTaskQueue | null>(null);
  const [teamBoard, setTeamBoard] = useState<TeamTaskBoard | null>(null);
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [scanHistory, setScanHistory] = useState<SlaScanHistory | null>(null);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [correctionTasks, setCorrectionTasks] = useState<DocumentCorrectionTask[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [retryingRunKey, setRetryingRunKey] = useState("");
  const [releasingLease, setReleasingLease] = useState(false);
  const [assigningId, setAssigningId] = useState("");
  const [supervisingId, setSupervisingId] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [taskResult, teamResult, summaryResult, scanHistoryResult, notificationRows, correctionRows] = await Promise.all([
        canViewTasks ? api.personalTasks() : Promise.resolve(null),
        canViewOperations ? api.teamTasks() : Promise.resolve(null),
        canViewOperations ? api.operationsSummary() : Promise.resolve(null),
        canViewOperations ? api.slaScanHistory() : Promise.resolve(null),
        canViewNotifications ? api.notifications(unreadOnly) : Promise.resolve([]),
        canViewOperations ? api.documentCorrectionWorkbench() : Promise.resolve([]),
      ]);
      setTaskQueue(taskResult);
      setTeamBoard(teamResult);
      setSummary(summaryResult);
      setScanHistory(scanHistoryResult);
      setNotifications(notificationRows);
      setCorrectionTasks(correctionRows);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "运营数据加载失败" });
    } finally {
      setLoading(false);
    }
  }, [canViewNotifications, canViewOperations, canViewTasks, onNotice, unreadOnly]);

  useEffect(() => { void reload(); }, [reload]);

  useEffect(() => {
    if (!canViewOperations) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const result = await api.slaScanHistory();
        if (!cancelled) setScanHistory(result);
      } catch {
        // Background refresh is best effort; the main reload path surfaces errors.
      }
    };
    const interval = window.setInterval(() => void refresh(), scanHistory?.execution_summary.running || ["active", "overdue"].includes(scanHistory?.execution_lease.status ?? "idle") ? 3000 : 15000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [canViewOperations, scanHistory?.execution_summary.running, scanHistory?.execution_lease.status]);

  async function scan() {
    setScanning(true);
    try {
      const result = await api.runSlaScan();
      await reload();
      onNotice({ kind: "success", text: `扫描 ${result.active_cases_scanned} 笔申请、${result.active_corrections_scanned} 项补件、${result.active_facilities_scanned} 笔授信及 ${result.control_conditions_scanned} 项逾期条件；新增 ${result.notifications_created} 条通知、${result.facility_alerts_opened} 条预警，升级 ${result.control_conditions_escalated} 项贷后任务，回收 ${result.expired_assignments_released} 项过期认领` });
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

  async function retryScan(runKey: string, reason: string): Promise<boolean> {
    setRetryingRunKey(runKey);
    try {
      const result = await api.retrySlaScan(runKey, reason);
      await reload();
      onNotice({
        kind: result.status === "completed" ? "success" : "error",
        text: result.status === "completed"
          ? `第 ${result.retry.retry_number} 次人工重试成功，失败告警已恢复并写入审计链`
          : `第 ${result.retry.retry_number} 次人工重试已执行但仍失败，请依据最新服务日志继续排查`,
      });
      return true;
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "失败扫描人工重试未能提交" });
      return false;
    } finally {
      setRetryingRunKey("");
    }
  }

  async function releaseScanLease(executionId: string, reason: string): Promise<boolean> {
    setReleasingLease(true);
    try {
      await api.releaseSlaScanLease(executionId, reason);
      await reload();
      onNotice({ kind: "success", text: "长时扫描租约已受控释放，操作人、原因和原租约快照已写入审计链" });
      return true;
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "扫描租约释放失败" });
      return false;
    } finally {
      setReleasingLease(false);
    }
  }

  async function openNotification(item: NotificationRecord) {
    try {
      if (item.status === "unread") await api.markNotificationRead(item.id);
      onNavigate(item.action);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "任务入口打开失败" });
    }
  }

  async function actOnCorrection(task: DocumentCorrectionTask, payload: { action: "remind" | "reassign" | "extend"; reason: string; assigned_role?: DocumentCorrection["assigned_role"]; extension_hours?: number }) {
    await api.actOnDocumentCorrection(task.id, { expected_row_version: task.row_version, ...payload });
    await reload();
    onNotice({ kind: "success", text: `${payload.action === "remind" ? "人工催办" : payload.action === "reassign" ? "责任转派" : "SLA 延期"}已完成并写入审计链` });
  }

  async function assignTask(task: PersonalTask, action: "claim" | "renew" | "release") {
    if (task.task_type !== "approval" && task.task_type !== "correction") return;
    setAssigningId(task.id);
    try {
      await api.assignPersonalTask(
        task.task_type,
        task.task_type === "approval" ? task.case_id! : task.correction_id!,
        action,
        task.row_version,
      );
      await reload();
      onNotice({ kind: "success", text: action === "claim" ? "任务已认领，租约有效期 4 小时" : action === "renew" ? "任务认领已续期 4 小时" : "任务已释放并返回角色公共队列" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "任务认领操作失败" });
    } finally {
      setAssigningId("");
    }
  }

  async function supervisorRelease(task: TeamTask, reason: string) {
    if (task.task_type !== "approval" && task.task_type !== "correction") return;
    setSupervisingId(task.id);
    try {
      await api.releaseTeamTask(
        task.task_type,
        task.task_type === "approval" ? task.case_id! : task.correction_id!,
        task.row_version,
        reason,
      );
      await reload();
      onNotice({ kind: "success", text: `已解除 ${task.assigned_to_name ?? "处理人"} 的任务占用，原因已写入审计链` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "监督释放失败" });
      throw error;
    } finally {
      setSupervisingId("");
    }
  }

  async function supervisorRemind(task: TeamTask, reason: string) {
    const taskId = taskBackendId(task);
    if (!taskId) return;
    setSupervisingId(task.id);
    try {
      await api.remindTeamTask(
        task.task_type,
        taskId,
        task.row_version,
        reason,
      );
      await reload();
      onNotice({ kind: "success", text: task.claimable ? `已向 ${task.assigned_to_name ?? "任务处理人"} 发送个人定向催办` : `已向${teamRoleLabel(task.reminder_role ?? task.owner_roles[0])}发送角色催办` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "定向催办失败" });
      throw error;
    } finally {
      setSupervisingId("");
    }
  }

  if (!canViewTasks && !canViewOperations && !canViewNotifications) return <div className="panel operations-empty"><strong>当前身份无运营监控权限</strong><p>请切换为业务处理、风控、审计或运营角色。</p></div>;
  if (loading && !taskQueue && !summary && !notifications.length) return <div className="panel operations-loading">正在汇总个人待办、SLA 与通知数据…</div>;

  const activeScanCount = scanHistory?.execution_summary.running ?? 0;
  const leaseActive = ["active", "overdue"].includes(scanHistory?.execution_lease.status ?? "idle");
  const scanBusy = scanning || activeScanCount > 0 || leaseActive;

  return <div className="operations-center">
    <section className="operations-hero">
      <div><span>RISK OPERATIONS</span><h2>个人待办与 SLA 运营监控</h2><p>统一汇总审批、补件、贷后控制与延期审批任务，并识别即将超时、已超时及升级处置事项。</p></div>
      {canScan && <button className="primary-button" disabled={scanBusy} onClick={() => void scan()}>{scanning ? "正在扫描…" : leaseActive || activeScanCount > 0 ? "已有扫描执行中" : "运行全域 SLA 扫描"}</button>}
    </section>

    {taskQueue && <PersonalTaskPanel queue={taskQueue} assigningId={assigningId} onAssign={assignTask} onNavigate={onNavigate} />}
    {teamBoard && <TeamTaskBoardPanel board={teamBoard} canManage={canManageTasks} supervisingId={supervisingId} onRelease={supervisorRelease} onRemind={supervisorRemind} onNavigate={onNavigate} />}

    {summary && <>
      <section className="ops-metric-grid">
        <OpsMetric label="活跃申请" value={summary.active_cases} detail={`${summary.sla.paused} 笔待补件暂停计时`} tone="blue" />
        <OpsMetric label="即将超时" value={summary.sla.due_soon} detail="进入环节时限最后 25%" tone="amber" />
        <OpsMetric label="已经超时" value={summary.sla.overdue} detail="需立即催办责任角色" tone="red" />
        <OpsMetric label="升级处置" value={summary.sla.escalated} detail="持续超时超过 4 小时" tone="purple" />
        <OpsMetric label="补件任务" value={summary.correction_sla.active} detail={`${summary.correction_sla.overdue + summary.correction_sla.escalated} 项超时待办`} tone="gold" unit="项" />
        <OpsMetric label="未读通知" value={summary.unread_notifications.total} detail={`${summary.unread_notifications.critical} 条严重通知`} tone="teal" unit="条" />
      </section>
      <section className="panel correction-sla-overview">
        <div className="ops-section-head"><div><span>DOCUMENT CORRECTION SLA</span><h2>补件责任与时限</h2></div><small>客户经理补件 48 小时 · 风控复核 24 小时</small></div>
        <div className="correction-sla-metrics">
          <span className="normal"><small>正常</small><strong>{summary.correction_sla.normal}</strong></span>
          <span className="due-soon"><small>即将超时</small><strong>{summary.correction_sla.due_soon}</strong></span>
          <span className="overdue"><small>已超时</small><strong>{summary.correction_sla.overdue}</strong></span>
          <span className="escalated"><small>升级催办</small><strong>{summary.correction_sla.escalated}</strong></span>
        </div>
      </section>
      <section className="panel post-credit-sla-overview">
        <div className="ops-section-head"><div><span>POST-CREDIT SLA</span><h2>贷后控制与延期审批</h2></div><small>一次扫描同步检查授信预警、控制条件截止日与分级升级</small></div>
        <div className="post-credit-sla-metrics">
          <span><small>生效授信</small><strong>{summary.post_credit_sla.active_facilities}</strong></span>
          <span><small>待落实条件</small><strong>{summary.post_credit_sla.pending_controls}</strong></span>
          <span className="due-soon"><small>即将到期</small><strong>{summary.post_credit_sla.due_soon}</strong></span>
          <span className="overdue"><small>已逾期</small><strong>{summary.post_credit_sla.overdue}</strong></span>
          <span className="escalated"><small>升级督办</small><strong>{summary.post_credit_sla.escalated}</strong></span>
          <span className="extension"><small>延期待审批</small><strong>{summary.post_credit_sla.pending_extensions}</strong></span>
        </div>
      </section>
      {scanHistory && <ScanGovernancePanel history={scanHistory} canRetry={canScan} canReleaseLease={canManageTasks} scanBusy={scanBusy} retryingRunKey={retryingRunKey} releasingLease={releasingLease} onRetry={retryScan} onReleaseLease={releaseScanLease} />}
      <CorrectionTaskWorkbench tasks={correctionTasks} canAct={canActCorrections} onAct={actOnCorrection} onError={(text) => onNotice({ kind: "error", text })} />
      <section className="panel ops-stage-panel">
        <div className="ops-section-head"><div><span>STAGE DISTRIBUTION</span><h2>活跃申请环节分布</h2></div><small>{summary.last_scan ? `最近全域扫描 ${formatTime(summary.last_scan.run_at)} · ${summary.last_scan.active_facilities_scanned} 笔授信 · 新增 ${summary.last_scan.notifications_created} 条通知 / ${summary.last_scan.facility_alerts_opened} 条预警 · 回收 ${summary.last_scan.expired_assignments_released} 项` : `尚未执行扫描 · 汇总于 ${formatTime(summary.generated_at)}`}</small></div>
        <StageDistribution rows={summary.stage_distribution} />
      </section>
    </>}

    {canViewNotifications && <section className="panel notification-panel">
      <div className="ops-section-head"><div><span>INBOX</span><h2>我的任务通知</h2></div><label className="unread-toggle"><input type="checkbox" checked={unreadOnly} onChange={(event) => setUnreadOnly(event.target.checked)} />仅看未读</label></div>
      {notifications.length ? <div className="notification-list">{notifications.map((item) => <div className={`notification-item ${item.severity} ${item.status}`} key={item.id}><div className="notification-symbol">{item.level === "escalated" ? "!!" : ["overdue", "policy_blocked", "scan_failed"].includes(item.level) ? "!" : ["completed", "resumed"].includes(item.level) ? "✓" : "◷"}</div><div className="notification-body"><div><strong>{item.title}</strong><span>{levelLabel(item.level)}</span></div><p>{item.message}</p><footer><code>{item.case_id ?? (item.category === "authority_policy" ? "策略治理" : item.category === "sla_scan" ? "扫描治理" : "—")}</code><small>{formatTime(item.created_at)}</small></footer></div><div className="notification-actions">{item.action.page && item.status !== "resolved" && <button className="open-task" onClick={() => void openNotification(item)}>前往处理</button>}{item.status === "unread" ? <button onClick={() => void markRead(item)}>标记已读</button> : <span>{item.status === "resolved" ? "已关闭" : "已读"}</span>}</div></div>)}</div> : <div className="notification-empty"><span>✓</span><strong>当前没有{unreadOnly ? "未读" : ""}任务通知</strong><p>审批、补件、贷后控制与延期审批消息会按当前角色出现在这里。</p></div>}
    </section>}
  </div>;
}

function PersonalTaskPanel({ queue, assigningId, onAssign, onNavigate }: { queue: PersonalTaskQueue; assigningId: string; onAssign: (task: PersonalTask, action: "claim" | "renew" | "release") => Promise<void>; onNavigate: (action: TaskAction) => void }) {
  const [filter, setFilter] = useState<"all" | "approval" | "correction" | "post_credit" | "risk">("all");
  const tasks = queue.tasks.filter((task) => filter === "all"
    || task.task_type === filter
    || (filter === "post_credit" && ["facility_control", "control_extension"].includes(task.task_type))
    || (filter === "risk" && task.sla_status !== "normal"));
  return <section className="panel personal-task-panel">
    <div className="ops-section-head">
      <div><span>MY WORK QUEUE</span><h2>我的待办</h2></div>
      <small>按 SLA 风险与截止时间排序 · 共 {queue.summary.total} 项{queue.summary.truncated ? `，展示前 ${queue.summary.returned} 项` : ""}</small>
    </div>
    <div className="personal-task-summary">
      <span><small>全部待办</small><strong>{queue.summary.total}</strong></span>
      <span><small>审批环节</small><strong>{queue.summary.approval}</strong></span>
      <span><small>补件任务</small><strong>{queue.summary.correction}</strong></span>
      <span><small>贷后任务</small><strong>{queue.summary.post_credit}</strong></span>
      <span className={queue.summary.overdue + queue.summary.escalated ? "danger" : ""}><small>超时风险</small><strong>{queue.summary.overdue + queue.summary.escalated}</strong></span>
    </div>
    <div className="personal-task-filters">
      {([["all", "全部"], ["approval", "审批"], ["correction", "补件"], ["post_credit", "贷后"], ["risk", "时限风险"]] as const).map(([key, label]) => <button className={filter === key ? "active" : ""} key={key} onClick={() => setFilter(key)}>{label}</button>)}
    </div>
    {tasks.length ? <div className="personal-task-list">{tasks.map((task) => <PersonalTaskCard task={task} assigning={assigningId === task.id} onAssign={onAssign} onNavigate={onNavigate} key={task.id} />)}</div> : <div className="notification-empty compact"><span>✓</span><strong>{queue.tasks.length ? "当前筛选条件下没有待办" : "当前角色没有待办任务"}</strong><p>任务会随审批环节和补件责任自动流转。</p></div>}
  </section>;
}

function PersonalTaskCard({ task, assigning, onAssign, onNavigate }: { task: PersonalTask; assigning: boolean; onAssign: (task: PersonalTask, action: "claim" | "renew" | "release") => Promise<void>; onNavigate: (action: TaskAction) => void }) {
  return <article className={`personal-task-card ${task.sla_status}`}>
    <div className={`personal-task-kind ${task.task_type}`}>{taskTypeLabel(task.task_type)}</div>
    <div className="personal-task-main">
      <header><strong>{task.title}</strong><span>{taskSlaLabel(task.sla_status)}</span></header>
      <p>{task.counterparty_name} · {task.case_id ?? "未关联审批单"}</p>
      <small>{task.description}</small>
      <footer><span>截止 {formatTime(task.due_at)}</span>{!task.claimable && <em>系统按角色直派</em>}{task.viewer_mode === "collaborator" && <em>协作处理</em>}{task.assigned_to_name && <em>{task.assigned_to_name} 已认领 · {formatLease(task.lease_remaining_seconds)}后回收</em>}{task.assignment_expired && <em className="expired">上次认领已超时回收</em>}</footer>
    </div>
    <div className="personal-task-actions">
      {!task.claimable ? <button onClick={() => onNavigate(task.action)}>{task.task_type === "control_extension" ? "前往审批" : "前往落实"}</button> : task.assignment_state === "unassigned" ? <button disabled={assigning} onClick={() => void onAssign(task, "claim")}>{assigning ? "认领中…" : "认领任务"}</button> : task.assignment_state === "mine" ? <><button onClick={() => onNavigate(task.action)}>立即处理</button><button className="renew" disabled={assigning} onClick={() => void onAssign(task, "renew")}>续期</button><button className="release" disabled={assigning} onClick={() => void onAssign(task, "release")}>释放</button></> : <><span>{task.assigned_to_name ?? "他人"}处理中</span>{task.can_release && <button className="release" disabled={assigning} onClick={() => void onAssign(task, "release")}>{assigning ? "释放中…" : "管理员释放"}</button>}</>}
    </div>
  </article>;
}

function TeamTaskBoardPanel({ board, canManage, supervisingId, onRelease, onRemind, onNavigate }: { board: TeamTaskBoard; canManage: boolean; supervisingId: string; onRelease: (task: TeamTask, reason: string) => Promise<void>; onRemind: (task: TeamTask, reason: string) => Promise<void>; onNavigate: (action: TaskAction) => void }) {
  const [filter, setFilter] = useState<"all" | "unassigned" | "claimed" | "direct" | "risk">("all");
  const [selectedId, setSelectedId] = useState("");
  const [action, setAction] = useState<"remind" | "release">("remind");
  const [reason, setReason] = useState("");
  const tasks = board.tasks.filter((task) => filter === "all"
    || (filter === "unassigned" && task.assignment_state === "unassigned")
    || (filter === "claimed" && task.assignment_state === "assigned_other")
    || (filter === "direct" && !task.claimable)
    || (filter === "risk" && task.sla_status !== "normal"));

  async function submit(task: TeamTask) {
    if (reason.trim().length < 5) return;
    try {
      await (action === "remind" ? onRemind(task, reason.trim()) : onRelease(task, reason.trim()));
      setSelectedId("");
      setReason("");
    } catch {
      // Parent displays the API error and leaves the form open for correction.
    }
  }

  return <section className="panel team-task-board">
    <div className="ops-section-head">
      <div><span>TEAM CONTROL TOWER</span><h2>团队任务负载、占用与角色催办</h2></div>
      <small>全局 {board.summary.total} 项 · {board.summary.claimed} 项已认领 · {board.summary.at_risk} 项时限风险</small>
    </div>
    <div className="team-task-summary">
      <span><small>任务总量</small><strong>{board.summary.total}</strong></span>
      <span><small>已认领</small><strong>{board.summary.claimed}</strong></span>
      <span className={board.summary.unassigned ? "warning" : ""}><small>待认领</small><strong>{board.summary.unassigned}</strong></span>
      <span><small>系统直派</small><strong>{board.summary.direct}</strong></span>
      <span className={board.summary.expired ? "danger" : ""}><small>待回收过期</small><strong>{board.summary.expired}</strong></span>
    </div>
    <div className="team-load-section">
      <header><strong>可处理角色负载</strong><small>同一任务支持多角色处理时会分别计入</small></header>
      <div className="team-role-load">{board.role_load.map((item) => <div key={item.role}><span>{teamRoleLabel(item.role)}</span><strong>{item.total}</strong><small>{item.claimed} 已认领 · {item.unassigned} 待认领 · {item.direct} 直派 · {item.risk} 风险</small></div>)}</div>
    </div>
    <div className="team-load-section assignees">
      <header><strong>任务分配负载</strong><small>有效认领、未认领与系统直派分别汇总</small></header>
      <div className="team-assignee-load">{board.assignee_load.map((item) => <div key={item.subject ?? "unassigned"}><span>{item.name}</span><strong>{item.total}</strong><small>{item.risk} 项时限风险</small></div>)}</div>
    </div>
    <div className="personal-task-filters">
      {([["all", "全部"], ["unassigned", "待认领"], ["claimed", "已认领"], ["direct", "系统直派"], ["risk", "时限风险"]] as const).map(([key, label]) => <button className={filter === key ? "active" : ""} key={key} onClick={() => setFilter(key)}>{label}</button>)}
    </div>
    {tasks.length ? <div className="team-task-list">{tasks.map((task) => <article className={`team-task-row ${task.sla_status}`} key={task.id}>
      <div className={`team-task-status ${task.task_type}`}><span>{taskTypeLabel(task.task_type)}</span><i>{taskSlaLabel(task.sla_status)}</i></div>
      <div className="team-task-content"><strong>{task.title}</strong><p>{task.counterparty_name} · {task.case_id ?? "未关联审批单"}</p><small>{task.owner_roles.map(teamRoleLabel).join(" / ")} · 截止 {formatTime(task.due_at)}</small></div>
      <div className="team-task-owner">{!task.claimable ? <><strong>系统按角色直派</strong><small>完成后移出 · 可受控催办</small></> : task.assignment_state === "assigned_other" ? <><strong>{task.assigned_to_name}</strong><small>{formatLease(task.lease_remaining_seconds)}后回收</small></> : <><strong>角色公共队列</strong><small>{task.assignment_expired ? "上次占用已过期" : "等待认领"}</small></>}</div>
      <div className="team-task-actions"><button onClick={() => onNavigate(task.action)}>定位任务</button>{canManage && task.can_remind && <button className="remind" onClick={() => { setSelectedId(task.id); setAction("remind"); setReason(""); }}>{task.claimable ? "定向催办" : `催办${teamRoleLabel(task.reminder_role ?? task.owner_roles[0])}`}</button>}{canManage && task.can_force_release && <button className="danger" onClick={() => { setSelectedId(task.id); setAction("release"); setReason(""); }}>解除占用</button>}</div>
      {selectedId === task.id && <div className="team-release-form"><label><span>{action === "remind" ? task.claimable ? "定向催办原因" : `${teamRoleLabel(task.reminder_role ?? task.owner_roles[0])}角色催办原因` : "监督释放原因"}</span><input value={reason} maxLength={1000} onChange={(event) => setReason(event.target.value)} placeholder={action === "remind" ? task.claimable ? "说明催办事项和期望处理时点，至少 5 个字…" : "说明角色催办事项和期望处理时点，至少 5 个字…" : "说明离岗、误认领或应急接管依据，至少 5 个字…"} /></label><button onClick={() => setSelectedId("")}>取消</button><button className={action === "release" ? "danger" : "remind"} disabled={reason.trim().length < 5 || supervisingId === task.id} onClick={() => void submit(task)}>{supervisingId === task.id ? "提交中…" : action === "remind" ? task.claimable ? "发送个人催办" : "发送角色催办" : "确认释放并留痕"}</button></div>}
    </article>)}</div> : <div className="notification-empty compact"><strong>当前筛选条件下没有团队任务</strong><p>任务流转后会自动进入团队负载看板。</p></div>}
  </section>;
}

function OpsMetric({ label, value, detail, tone, unit = "笔" }: { label: string; value: number; detail: string; tone: string; unit?: string }) { return <div className={`ops-metric ${tone}`}><span>{label}</span><strong>{value}<small>{unit}</small></strong><p>{detail}</p><i /></div>; }

function ScanGovernancePanel({ history, canRetry, canReleaseLease, scanBusy, retryingRunKey, releasingLease, onRetry, onReleaseLease }: { history: SlaScanHistory; canRetry: boolean; canReleaseLease: boolean; scanBusy: boolean; retryingRunKey: string; releasingLease: boolean; onRetry: (runKey: string, reason: string) => Promise<boolean>; onReleaseLease: (executionId: string, reason: string) => Promise<boolean> }) {
  const schedulerState = history.scheduler_health.state;
  const healthLabel = schedulerState === "healthy" ? "自动调度心跳正常" : schedulerState === "blocked" ? "自动扫描执行失败" : schedulerState === "stale" ? "自动调度心跳超期" : "自动调度尚未接管";
  const healthDetail = schedulerState === "never"
    ? `尚无自动运行 · 已记录 ${history.summary.manual_runs} 次人工扫描`
    : schedulerState === "blocked"
    ? `${history.scheduler_health.error_type ?? "执行异常"} · ${history.scheduler_health.error_message ?? "请检查服务日志"}`
    : schedulerState === "healthy"
    ? `最近自动运行 ${formatTime(history.scheduler_health.last_run_at)} · 预计下次 ${formatTime(history.scheduler_health.next_expected_run_at)}`
    : `最近自动运行 ${formatTime(history.scheduler_health.last_run_at)} · 已漏过 ${history.scheduler_health.missed_intervals} 个周期`;
  return <section className={`panel scan-governance-panel ${schedulerState}`}>
    <div className="ops-section-head">
      <div><span>SCAN GOVERNANCE</span><h2>全域扫描运行健康与风险趋势</h2></div>
      <div className={`scan-health-badge ${schedulerState}`}><i /> <span><strong>{healthLabel}</strong><small>{healthDetail}</small></span></div>
    </div>
    <ScanExecutionStatus history={history} canReleaseLease={canReleaseLease} releasingLease={releasingLease} onReleaseLease={onReleaseLease} />
    <ScanExecutionLedger executions={history.executions} summary={history.execution_summary} />
    <div className="scan-governance-summary">
      <span className={["stale", "blocked"].includes(schedulerState) ? "danger" : schedulerState === "never" ? "warning" : ""}><small>{schedulerState === "blocked" ? "失败运行" : "自动漏跑周期"}</small><strong>{schedulerState === "blocked" ? history.summary.failed_runs : schedulerState === "never" ? "—" : history.scheduler_health.missed_intervals}</strong><em>{schedulerState === "blocked" ? "失败已记录并向运营及管理员告警" : `超过 ${history.stale_after_minutes} 分钟判定心跳超期`}</em></span>
      <span className={history.summary.short_interval_runs ? "warning" : ""}><small>扫描运行来源</small><strong>{history.summary.scheduler_runs}<i> 自动</i></strong><em>{history.summary.manual_runs} 次人工 · {history.summary.retry_runs} 次重试 · {history.summary.failed_runs} 次失败</em></span>
      <span><small>产生新风险的运行</small><strong>{history.summary.runs_with_new_risk}</strong><em>最近 {history.summary.returned_runs} 次扫描</em></span>
      <span><small>扫描产出合计</small><strong>{history.summary.total_notifications + history.summary.total_alerts + history.summary.total_escalations}</strong><em>{history.summary.total_notifications} 通知 · {history.summary.total_alerts} 预警 · {history.summary.total_escalations} 升级</em></span>
    </div>
    {history.runs.length ? <div className="scan-run-history">
      <header><span>运行时间与执行人</span><span>扫描覆盖</span><span>本次产出</span><span>较上次趋势</span></header>
      {history.runs.map((run) => <ScanRunRow run={run} canRetry={canRetry} scanBusy={scanBusy} retrying={retryingRunKey === run.run_key} onRetry={onRetry} key={run.event_id} />)}
    </div> : <div className="notification-empty compact"><strong>暂无扫描运行记录</strong><p>具备扫描权限的运营人员运行一次全域扫描后，这里会形成可追溯历史。</p></div>}
  </section>;
}

function ScanExecutionStatus({ history, canReleaseLease, releasingLease, onReleaseLease }: { history: SlaScanHistory; canReleaseLease: boolean; releasingLease: boolean; onReleaseLease: (executionId: string, reason: string) => Promise<boolean> }) {
  const [showRelease, setShowRelease] = useState(false);
  const [releaseReason, setReleaseReason] = useState("");
  const active = history.executions.find((item) => item.status === "running");
  const timedOut = history.executions.find((item) => item.status === "timed_out");
  const latest = active ?? timedOut ?? history.executions[0];
  const lease = history.execution_lease;
  const leaseActive = lease.status === "active";
  const leaseOverdue = lease.status === "overdue";
  const heartbeatState = lease.heartbeat_health.state;
  const state = heartbeatState === "lost" ? "heartbeat-lost" : heartbeatState === "delayed" ? "heartbeat-delayed" : leaseOverdue ? "timed-out" : leaseActive || active ? "running" : timedOut || lease.status === "expired" ? "timed-out" : latest?.status === "failed" || latest?.status === "late_failed" || latest?.status === "aborted" || latest?.status === "late_aborted" ? "failed" : "idle";
  const title = heartbeatState === "lost" ? "扫描心跳失联，租约仍在保护期" : heartbeatState === "delayed" ? "扫描心跳延迟，请关注运行进程" : leaseOverdue ? "扫描超时预警，租约仍受保护" : leaseActive || active ? "全域扫描正在执行" : timedOut || lease.status === "expired" ? "存在执行超时未回报" : latest ? "当前无扫描执行中" : "尚无执行轨迹";
  const detail = heartbeatState === "lost"
    ? `最近心跳 ${formatTime(lease.last_heartbeat_at)}，已漏过 ${lease.heartbeat_health.missed_heartbeats} 个周期；请核对进程，达到预警时限后可受控释放`
    : heartbeatState === "delayed"
    ? `最近心跳 ${formatTime(lease.last_heartbeat_at)}，延迟 ${formatDuration(lease.heartbeat_health.age_seconds ?? 0)}；当前执行仍持有租约`
    : leaseOverdue
    ? `${scanTriggerLabel(lease.trigger_type ?? "legacy")}由 ${lease.actor ?? "处理人"} 于 ${formatTime(lease.acquired_at)} 发起；已超过 ${history.execution_timeout_minutes} 分钟预警线，最近心跳 ${formatTime(lease.last_heartbeat_at)}，保护剩余 ${formatDuration(lease.remaining_seconds)}`
    : leaseActive
    ? `${scanTriggerLabel(lease.trigger_type ?? "legacy")}由 ${lease.actor ?? "处理人"} 于 ${formatTime(lease.acquired_at)} 发起，最近心跳 ${formatTime(lease.last_heartbeat_at)}，保护剩余 ${formatDuration(lease.remaining_seconds)}`
    : active
    ? `${scanTriggerLabel(active.trigger_type)}由 ${active.actor} 于 ${formatTime(active.started_at)} 发起，已运行 ${formatDuration(active.elapsed_seconds)}`
    : timedOut
    ? `${scanTriggerLabel(timedOut.trigger_type)}自 ${formatTime(timedOut.started_at)} 起已超过 ${history.execution_timeout_minutes} 分钟，请检查进程状态`
    : latest
    ? `最近一次${scanTriggerLabel(latest.trigger_type)}${scanExecutionResultLabel(latest.status)} · ${latest.actor} · ${formatTime(latest.started_at)}`
    : "人工、自动与恢复扫描启动后，将在这里显示实时状态。";
  async function submitRelease() {
    if (!lease.execution_id || releaseReason.trim().length < 5) return;
    if (await onReleaseLease(lease.execution_id, releaseReason.trim())) {
      setShowRelease(false);
      setReleaseReason("");
    }
  }
  return <div className={`scan-execution-status ${state}`}>
    <div className="scan-execution-overview">
      <div className="scan-execution-state"><i /><span><strong>{title}</strong><small>{detail}</small></span></div>
      <div className="scan-execution-meta"><span><small>执行中</small><strong>{history.execution_summary.running}</strong></span><span className={history.execution_summary.timed_out ? "danger" : ""}><small>超时预警</small><strong>{history.execution_summary.timed_out}</strong></span><span><small>续租心跳</small><strong>{lease.heartbeat_count}</strong></span><span className={history.execution_summary.aborted ? "danger" : ""}><small>失锁中止</small><strong>{history.execution_summary.aborted}</strong></span></div>
      {leaseOverdue && canReleaseLease && !showRelease && <button className="scan-lease-release-button" onClick={() => setShowRelease(true)}>受控释放租约</button>}
      {leaseOverdue && !canReleaseLease && <em className="scan-lease-readonly">需由运营管理角色核实进程后释放</em>}
    </div>
    {showRelease && leaseOverdue && <div className="scan-lease-release-form"><div><strong>受控释放长时扫描</strong><span>系统每 {history.execution_heartbeat_interval_seconds} 秒续租一次。请先核对最近心跳与后台进程；释放后旧进程会在下一检查点停止写入并留下失锁证据。</span></div><label><span>释放原因</span><input autoFocus value={releaseReason} maxLength={1000} onChange={(event) => setReleaseReason(event.target.value)} placeholder="说明心跳、进程核验和接管依据，至少 5 个字…" /></label><button disabled={releasingLease} onClick={() => setShowRelease(false)}>取消</button><button className="danger" disabled={releasingLease || releaseReason.trim().length < 5} onClick={() => void submitRelease()}>{releasingLease ? "释放中…" : "确认释放并留痕"}</button></div>}
  </div>;
}

function ScanExecutionLedger({ executions, summary }: { executions: SlaScanHistory["executions"]; summary: SlaScanHistory["execution_summary"] }) {
  const [filter, setFilter] = useState<"all" | "running" | "abnormal">("all");
  const abnormalStatuses = new Set(["failed", "late_failed", "aborted", "late_aborted", "timed_out", "force_released"]);
  const rows = executions.filter((item) => filter === "all" ? true : filter === "running" ? item.status === "running" : abnormalStatuses.has(item.status) || item.evidence_integrity.state === "broken");
  return <section className="scan-execution-ledger">
    <header><div><span>EXECUTION LEDGER</span><strong>扫描执行与审计证据</strong><small>逐次核对来源、耗时、结束原因及哈希链事件</small></div><aside className={summary.evidence_broken ? "broken" : "verified"}><strong>{summary.evidence_broken ? `${summary.evidence_broken} 条证据异常` : "证据链完整"}</strong><small>已校验 {summary.evidence_events_checked} 个事件</small></aside><nav aria-label="执行台账筛选"><button className={filter === "all" ? "active" : ""} aria-pressed={filter === "all"} onClick={() => setFilter("all")}>全部 {executions.length}</button><button className={filter === "running" ? "active" : ""} aria-pressed={filter === "running"} onClick={() => setFilter("running")}>执行中</button><button className={filter === "abnormal" ? "active" : ""} aria-pressed={filter === "abnormal"} onClick={() => setFilter("abnormal")}>异常证据</button></nav></header>
    {rows.length ? <div className="scan-execution-ledger-list">{rows.map((item) => <details className={`scan-execution-ledger-row ${item.status}`} key={item.execution_id}>
      <summary><span className={`scan-execution-result ${item.status}`}>{scanExecutionStatusLabel(item.status)}</span><span><strong>{scanTriggerLabel(item.trigger_type)}</strong><small>{item.actor}</small></span><span><strong>{formatTime(item.started_at)}</strong><small>{item.finished_at ? `结束 ${formatTime(item.finished_at)}` : `已运行 ${formatDuration(item.elapsed_seconds)}`}</small></span><span><strong>{formatDuration(item.elapsed_seconds)}</strong><small>{item.event_count} 个审计事件</small></span><span className={`scan-evidence-integrity ${item.evidence_integrity.state}`}><strong>{item.evidence_integrity.state === "verified" ? "证据完整" : "证据异常"}</strong><small>{item.evidence_integrity.checked_event_count} 项校验</small></span><code title={item.execution_id}>{item.execution_id.slice(0, 12)}</code><i>⌄</i></summary>
      <div className={`scan-execution-evidence ${item.evidence_integrity.state}`}><div className="scan-execution-conclusion"><span><small>结束结论</small><strong>{scanExecutionResultLabel(item.status)}</strong></span><span><small>终态处理人</small><strong>{item.released_by ?? item.terminal_actor ?? "—"}</strong></span><span><small>结果运行号</small><strong>{item.result_run_id?.slice(0, 18) ?? "—"}</strong></span><span className={item.evidence_integrity.state}><small>证据完整性</small><strong>{item.evidence_integrity.state === "verified" ? "校验通过" : scanEvidenceIssueLabel(item.evidence_integrity.issue_type)}</strong></span><p>{item.evidence_integrity.message} {item.termination_reason ?? (item.status === "completed" ? "扫描正常完成，业务结果与执行轨迹已闭合。" : item.status === "running" ? "当前仍在运行，等待终态事件。" : "未记录额外结束说明。")}</p></div><ol>{item.evidence_events.map((event, index) => <li className={!event.hash_valid || !event.link_valid ? "invalid" : ""} key={`${index}-${event.event_hash}`}><i>{index + 1}</i><div><strong>{scanExecutionEventLabel(event.event_type)}</strong><span>{event.actor} · {formatTime(event.occurred_at)}</span>{(event.reason || event.error_type) && <small>{event.reason ?? event.error_type}</small>}{(!event.hash_valid || !event.link_valid) && <em>{!event.link_valid ? "父级哈希不连续" : "事件内容哈希不匹配"}</em>}</div><code title={event.event_hash}>{event.event_hash.slice(0, 12)}</code></li>)}</ol></div>
    </details>)}</div> : <div className="notification-empty compact"><strong>当前筛选条件下没有执行记录</strong><p>切换“全部”可查看最近执行轨迹。</p></div>}
  </section>;
}

function ScanRunRow({ run, canRetry, scanBusy, retrying, onRetry }: { run: SlaScanRun; canRetry: boolean; scanBusy: boolean; retrying: boolean; onRetry: (runKey: string, reason: string) => Promise<boolean> }) {
  const [showRetry, setShowRetry] = useState(false);
  const [reason, setReason] = useState("");
  async function submitRetry() {
    if (!run.run_key || scanBusy || reason.trim().length < 5) return;
    if (await onRetry(run.run_key, reason.trim())) {
      setShowRetry(false);
      setReason("");
    }
  }
  return <article className={`${run.risk_increased ? "risk-increased" : ""} ${run.status} ${run.recovered ? "failure-recovered" : ""}`}>
    <div><strong>{formatTime(run.run_at)}</strong><span className={`scan-trigger ${run.status === "failed" ? run.recovered ? "recovered" : "failed" : run.trigger_type}`}>{run.status === "failed" ? run.recovered ? "失败已恢复" : "执行失败" : scanTriggerLabel(run.trigger_type)}</span><small>{run.actor}</small><code title={run.run_key ?? run.run_id}>{run.run_key ?? run.run_id.slice(0, 8)}</code></div>
    <div className="scan-run-coverage"><span><b>{run.active_cases_scanned}</b> 申请</span><span><b>{run.active_corrections_scanned}</b> 补件</span><span><b>{run.active_facilities_scanned}</b> 授信</span><span><b>{run.control_conditions_scanned}</b> 控制条件</span></div>
    <div className="scan-run-output"><span><b>{run.notifications_created}</b> 通知</span><span><b>{run.alerts_opened}</b> 预警</span><span><b>{run.escalations_triggered}</b> 升级</span><span><b>{run.expired_assignments_released}</b> 回收</span>{run.failure_notifications_resolved > 0 && <span className="recovered"><b>{run.failure_notifications_resolved}</b> 告警恢复</span>}</div>
    <div className="scan-run-trend"><TrendValue label="通知" value={run.notification_delta} /><TrendValue label="预警" value={run.alert_delta} /><TrendValue label="升级" value={run.escalation_delta} /></div>
    {run.status === "failed" && <aside className={run.recovered ? "scan-failure-detail recovered" : "scan-failure-detail"}>
      <div><strong>{run.recovered ? "该任务已恢复" : run.error_type ?? "执行异常"}</strong><span>{run.recovered ? `最近由 ${run.last_retry_actor ?? "运营人员"} 于 ${formatTime(run.last_retry_at)} 完成人工恢复` : run.error_message ?? "自动扫描执行失败，请检查服务日志。"}</span>{run.retry_count > 0 && <small>已重试 {run.retry_count} 次 · 最近结果：{retryStatusLabel(run.last_retry_status)}{run.last_retry_reason ? ` · 原因：${run.last_retry_reason}` : ""}</small>}</div>
      {!run.recovered && run.can_retry && canRetry && <button className="scan-retry-button" disabled={retrying || scanBusy} onClick={() => setShowRetry(true)}>{retrying ? "正在重试…" : scanBusy ? "等待当前扫描完成" : "人工重试"}</button>}
      {!run.recovered && !canRetry && <em>当前角色仅可查看，需由运营值班人员执行重试</em>}
    </aside>}
    {showRetry && !run.recovered && <div className="scan-retry-form"><div><strong>受控人工重试</strong><span>{scanBusy ? "检测到另一项扫描正在执行，请等待运行结束后再提交。" : "将沿用原任务键执行，原因、操作人和结果会写入审计链。"}</span></div><label><span>重试原因</span><input autoFocus value={reason} maxLength={1000} onChange={(event) => setReason(event.target.value)} placeholder="说明故障排查和恢复依据，至少 5 个字…" /></label><button disabled={retrying} onClick={() => setShowRetry(false)}>取消</button><button className="primary-button" disabled={retrying || scanBusy || reason.trim().length < 5} onClick={() => void submitRetry()}>{retrying ? "执行中…" : scanBusy ? "等待当前扫描完成" : "确认重试并留痕"}</button></div>}
  </article>;
}

function TrendValue({ label, value }: { label: string; value: number }) {
  return <span className={value > 0 ? "up" : value < 0 ? "down" : "flat"}>{label} {value > 0 ? `+${value}` : value}</span>;
}

function scanTriggerLabel(value: SlaScanRun["trigger_type"]): string { return value === "scheduler" ? "自动调度" : value === "manual" ? "人工运行" : value === "retry" ? "人工恢复" : "历史记录"; }
function retryStatusLabel(value: SlaScanRun["last_retry_status"]): string { return value === "completed" ? "恢复成功" : value === "failed" ? "仍然失败" : value === "requested" ? "已受理" : "暂无结果"; }
function scanExecutionResultLabel(value: SlaScanHistory["executions"][number]["status"]): string { return value === "completed" ? "已完成" : value === "late_completed" ? "释放后返回完成" : value === "late_failed" ? "释放后返回失败" : value === "late_aborted" ? "释放后失锁中止" : value === "aborted" ? "失锁中止" : value === "force_released" ? "已人工释放" : value === "failed" ? "执行失败" : value === "timed_out" ? "超时未回报" : "正在执行"; }
function scanExecutionStatusLabel(value: SlaScanHistory["executions"][number]["status"]): string { return value === "completed" ? "完成" : value === "running" ? "运行中" : value === "timed_out" ? "超时预警" : value === "force_released" ? "人工释放" : value === "aborted" || value === "late_aborted" ? "失锁中止" : value === "late_completed" ? "迟到完成" : "执行失败"; }
function scanExecutionEventLabel(value: string): string { const labels: Record<string, string> = { sla_scan_started: "获取租约并启动", sla_scan_execution_completed: "执行完成", sla_scan_execution_failed: "执行失败", sla_scan_execution_timed_out: "租约硬过期", sla_scan_execution_force_released: "运营受控释放", sla_scan_execution_terminal_lease_released: "终态残留租约清理", sla_scan_execution_lease_lost: "检测到租约失效", sla_scan_execution_aborted: "失锁中止", sla_scan_execution_late_aborted: "释放后中止", sla_scan_execution_late_completed: "迟到完成", sla_scan_execution_late_failed: "迟到失败" }; return labels[value] ?? value; }
function scanEvidenceIssueLabel(value: SlaScanExecution["evidence_integrity"]["issue_type"]): string { return value === "missing_root" ? "缺少根事件" : value === "multiple_roots" ? "存在多个根事件" : value === "broken_link" ? "证据链断裂" : value === "hash_mismatch" ? "内容哈希异常" : "校验异常"; }
function formatDuration(seconds: number): string { const minutes = Math.floor(seconds / 60); const remainder = seconds % 60; return minutes > 0 ? `${minutes} 分 ${remainder} 秒` : `${remainder} 秒`; }

function StageDistribution({ rows }: { rows: OperationsSummary["stage_distribution"] }) {
  const max = useMemo(() => Math.max(1, ...rows.map((item) => item.count)), [rows]);
  return rows.length ? <div className="stage-distribution">{rows.map((item) => <div key={item.stage}><span>{item.label}</span><div><i style={{ width: `${(item.count / max) * 100}%` }} /></div><strong>{item.count}</strong></div>)}</div> : <div className="notification-empty compact"><strong>暂无活跃申请</strong></div>;
}

function CorrectionTaskWorkbench({ tasks, canAct, onAct, onError }: {
  tasks: DocumentCorrectionTask[];
  canAct: boolean;
  onAct: (task: DocumentCorrectionTask, payload: { action: "remind" | "reassign" | "extend"; reason: string; assigned_role?: DocumentCorrection["assigned_role"]; extension_hours?: number }) => Promise<void>;
  onError: (text: string) => void;
}) {
  const [filter, setFilter] = useState<"all" | "open" | "resubmitted" | "risk">("all");
  const [selectedId, setSelectedId] = useState("");
  const [action, setAction] = useState<"remind" | "reassign" | "extend">("remind");
  const [reason, setReason] = useState("");
  const [assignedRole, setAssignedRole] = useState<DocumentCorrection["assigned_role"]>("relationship_manager");
  const [extensionHours, setExtensionHours] = useState(24);
  const [submitting, setSubmitting] = useState(false);
  const filtered = tasks.filter((task) => filter === "all"
    || task.status === filter
    || (filter === "risk" && ["due_soon", "overdue", "escalated"].includes(task.sla_status)));

  function prepare(task: DocumentCorrectionTask, nextAction: typeof action) {
    setSelectedId(task.id);
    setAction(nextAction);
    setReason("");
    const roles = eligibleRoles(task);
    setAssignedRole(roles.find((role) => role !== task.assigned_role) ?? roles[0]);
  }

  async function submit(task: DocumentCorrectionTask) {
    if (reason.trim().length < 5) return;
    setSubmitting(true);
    try {
      await onAct(task, {
        action,
        reason: reason.trim(),
        ...(action === "reassign" ? { assigned_role: assignedRole } : {}),
        ...(action === "extend" ? { extension_hours: extensionHours } : {}),
      });
      setSelectedId("");
      setReason("");
    } catch (error) {
      onError(error instanceof Error ? error.message : "补件任务处置失败");
    } finally {
      setSubmitting(false);
    }
  }

  return <section className="panel correction-workbench">
    <div className="ops-section-head">
      <div><span>ACTION WORKBENCH</span><h2>补件任务处置台</h2></div>
      <div className="correction-workbench-filters">
        {([["all", "全部"], ["open", "待上传"], ["resubmitted", "待复核"], ["risk", "时限风险"]] as const).map(([key, label]) => <button className={filter === key ? "active" : ""} key={key} onClick={() => setFilter(key)}>{label}</button>)}
      </div>
    </div>
    {!filtered.length ? <div className="notification-empty compact"><strong>{tasks.length ? "当前筛选条件下没有任务" : "当前没有活跃补件任务"}</strong><p>发生资料退补后，责任、时限与处置入口会集中显示在这里。</p></div> : <div className="correction-ops-list">{filtered.map((task) => {
      const selected = selectedId === task.id;
      return <article className={`correction-ops-task ${task.sla_status}`} key={task.id}>
        <header>
          <div><span>{task.counterparty_name}</span><strong>{task.document_type}</strong><code>{task.case_id ?? "未关联审批单"}</code></div>
          <i>{correctionSlaLabel(task.sla_status)}</i>
        </header>
        <div className="correction-ops-facts">
          <span><small>当前责任</small><strong>{correctionRoleLabel(task.assigned_role)}</strong></span>
          <span><small>任务状态</small><strong>{task.status === "open" ? "等待替换资料" : "等待独立复核"}</strong></span>
          <span><small>SLA 截止</small><strong>{formatTime(task.sla_due_at)}</strong></span>
          <span><small>处置记录</small><strong>{task.reminder_count} 次催办 · {task.extension_count} 次延期</strong></span>
        </div>
        <p>{task.reason}</p>
        {task.recent_actions.length > 0 && <details className="correction-action-history"><summary>最近处置记录（{task.recent_actions.length}）</summary>{task.recent_actions.map((item, index) => <div key={`${item.created_at}-${index}`}><strong>{correctionActionLabel(item.event_type)} · {item.detail}</strong><small>{item.actor} · {formatTime(item.created_at)}</small><p>{item.reason}</p></div>)}</details>}
        {canAct && <footer>
          <button onClick={() => prepare(task, "remind")}>人工催办</button>
          <button onClick={() => prepare(task, "reassign")}>责任转派</button>
          <button onClick={() => prepare(task, "extend")}>合规延期</button>
        </footer>}
        {selected && <div className="correction-action-form">
          <header><strong>{action === "remind" ? "发送人工催办" : action === "reassign" ? "转派当前任务" : "延长 SLA 时限"}</strong><button onClick={() => setSelectedId("")}>取消</button></header>
          {action === "reassign" && <label><span>目标责任角色</span><select value={assignedRole} onChange={(event) => setAssignedRole(event.target.value as DocumentCorrection["assigned_role"])}>{eligibleRoles(task).map((role) => <option key={role} value={role}>{correctionRoleLabel(role)}</option>)}</select></label>}
          {action === "extend" && <label><span>延期时长</span><select value={extensionHours} onChange={(event) => setExtensionHours(Number(event.target.value))}>{[4, 8, 12, 24, 48, 72].map((hours) => <option key={hours} value={hours}>{hours} 小时</option>)}</select></label>}
          <label className="wide"><span>处置原因</span><textarea value={reason} maxLength={1000} onChange={(event) => setReason(event.target.value)} placeholder="说明催办、转派或延期的业务依据，至少 5 个字…" /></label>
          <button className="primary-button" disabled={reason.trim().length < 5 || submitting} onClick={() => void submit(task)}>{submitting ? "正在提交…" : "确认并留痕"}</button>
        </div>}
      </article>;
    })}</div>}
  </section>;
}

function eligibleRoles(task: DocumentCorrectionTask): DocumentCorrection["assigned_role"][] {
  return task.status === "open" ? ["relationship_manager", "client"] : ["risk_manager", "approver"];
}
function correctionRoleLabel(role: DocumentCorrection["assigned_role"]): string { return ({ client: "企业客户", relationship_manager: "客户经理", risk_manager: "风控经理", approver: "授信审批人" } as const)[role]; }
function taskBackendId(task: PersonalTask): string | null { return task.task_type === "approval" ? task.case_id : task.task_type === "correction" ? task.correction_id : task.task_type === "facility_control" ? task.condition_id ?? null : task.extension_id ?? null; }
function taskTypeLabel(type: PersonalTask["task_type"]): string { return ({ approval: "审批", correction: "补件", facility_control: "贷后", control_extension: "延期" } as const)[type]; }
function teamRoleLabel(role: string): string { return ({ client: "企业客户", relationship_manager: "客户经理", risk_manager: "风控经理", model_admin: "模型管理员", approver: "授信审批人", operations: "运营值班", admin: "平台管理员" } as Record<string, string>)[role] ?? role; }
function correctionSlaLabel(status: DocumentCorrection["sla_status"]): string { return ({ normal: "时限正常", due_soon: "即将超时", overdue: "已超时", escalated: "升级催办", stopped: "已停止" } as const)[status]; }
function taskSlaLabel(status: PersonalTask["sla_status"]): string { return ({ normal: "时限正常", due_soon: "即将超时", overdue: "已超时", escalated: "升级处置" } as const)[status]; }
function correctionActionLabel(eventType: DocumentCorrectionTask["recent_actions"][number]["event_type"]): string { return ({ correction_manually_reminded: "人工催办", correction_reassigned: "责任转派", correction_sla_extended: "SLA 延期" } as const)[eventType]; }
function levelLabel(level: NotificationRecord["level"]): string { return ({ due_soon: "即将超时", overdue: "已超时", escalated: "升级催办", reminder: "人工催办", assignment: "任务转派", extension: "SLA 延期", task_created: "新增任务", resubmitted: "等待复核", reopened: "重新补件", completed: "核验完成", resumed: "审批恢复", supervisor_reminder: "个人催办", lease_due_soon: "租约临期", lease_expired: "认领回收", policy_blocked: "策略切换阻断", scan_failed: "扫描失败" } as const)[level]; }
function formatLease(value: number | null): string { if (value === null) return "即将"; const totalMinutes = Math.max(1, Math.floor(value / 60)); const hours = Math.floor(totalMinutes / 60); const minutes = totalMinutes % 60; return hours ? `${hours}小时${minutes}分` : `${minutes}分钟`; }
function formatTime(value: string | null): string { return value ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "—"; }
