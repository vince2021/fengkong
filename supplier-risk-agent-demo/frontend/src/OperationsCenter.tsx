import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { DocumentCorrection, DocumentCorrectionTask, NotificationRecord, OperationsSummary, PersonalTask, PersonalTaskQueue, TaskAction, TeamTask, TeamTaskBoard } from "./types";

type Notice = { kind: "error" | "success"; text: string };

export default function OperationsCenter({ canViewTasks, canViewOperations, canManageTasks, canViewNotifications, canScan, canActCorrections, onNavigate, onNotice }: { canViewTasks: boolean; canViewOperations: boolean; canManageTasks: boolean; canViewNotifications: boolean; canScan: boolean; canActCorrections: boolean; onNavigate: (action: TaskAction) => void; onNotice: (notice: Notice) => void }) {
  const [taskQueue, setTaskQueue] = useState<PersonalTaskQueue | null>(null);
  const [teamBoard, setTeamBoard] = useState<TeamTaskBoard | null>(null);
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [correctionTasks, setCorrectionTasks] = useState<DocumentCorrectionTask[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [assigningId, setAssigningId] = useState("");
  const [supervisingId, setSupervisingId] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [taskResult, teamResult, summaryResult, notificationRows, correctionRows] = await Promise.all([
        canViewTasks ? api.personalTasks() : Promise.resolve(null),
        canViewOperations ? api.teamTasks() : Promise.resolve(null),
        canViewOperations ? api.operationsSummary() : Promise.resolve(null),
        canViewNotifications ? api.notifications(unreadOnly) : Promise.resolve([]),
        canViewOperations ? api.documentCorrectionWorkbench() : Promise.resolve([]),
      ]);
      setTaskQueue(taskResult);
      setTeamBoard(teamResult);
      setSummary(summaryResult);
      setNotifications(notificationRows);
      setCorrectionTasks(correctionRows);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "运营数据加载失败" });
    } finally {
      setLoading(false);
    }
  }, [canViewNotifications, canViewOperations, canViewTasks, onNotice, unreadOnly]);

  useEffect(() => { void reload(); }, [reload]);

  async function scan() {
    setScanning(true);
    try {
      const result = await api.runSlaScan();
      await reload();
      onNotice({ kind: "success", text: `扫描 ${result.active_cases_scanned} 笔申请、${result.active_corrections_scanned} 项补件，新增 ${result.notifications_created} 条通知，回收 ${result.expired_assignments_released} 项过期认领` });
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

  return <div className="operations-center">
    <section className="operations-hero">
      <div><span>RISK OPERATIONS</span><h2>个人待办与 SLA 运营监控</h2><p>统一汇总审批、补件、贷后控制与延期审批任务，并识别即将超时、已超时及升级处置事项。</p></div>
      {canScan && <button className="primary-button" disabled={scanning} onClick={() => void scan()}>{scanning ? "正在扫描…" : "立即运行 SLA 扫描"}</button>}
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
      <CorrectionTaskWorkbench tasks={correctionTasks} canAct={canActCorrections} onAct={actOnCorrection} onError={(text) => onNotice({ kind: "error", text })} />
      <section className="panel ops-stage-panel">
        <div className="ops-section-head"><div><span>STAGE DISTRIBUTION</span><h2>活跃申请环节分布</h2></div><small>{summary.last_scan ? `最近扫描 ${formatTime(summary.last_scan.run_at)} · 新增 ${summary.last_scan.notifications_created} 条 · 回收 ${summary.last_scan.expired_assignments_released} 项` : `尚未执行扫描 · 汇总于 ${formatTime(summary.generated_at)}`}</small></div>
        <StageDistribution rows={summary.stage_distribution} />
      </section>
    </>}

    {canViewNotifications && <section className="panel notification-panel">
      <div className="ops-section-head"><div><span>INBOX</span><h2>我的任务通知</h2></div><label className="unread-toggle"><input type="checkbox" checked={unreadOnly} onChange={(event) => setUnreadOnly(event.target.checked)} />仅看未读</label></div>
      {notifications.length ? <div className="notification-list">{notifications.map((item) => <div className={`notification-item ${item.severity} ${item.status}`} key={item.id}><div className="notification-symbol">{item.level === "escalated" ? "!!" : ["overdue", "policy_blocked"].includes(item.level) ? "!" : ["completed", "resumed"].includes(item.level) ? "✓" : "◷"}</div><div className="notification-body"><div><strong>{item.title}</strong><span>{levelLabel(item.level)}</span></div><p>{item.message}</p><footer><code>{item.case_id ?? (item.category === "authority_policy" ? "策略治理" : "—")}</code><small>{formatTime(item.created_at)}</small></footer></div><div className="notification-actions">{item.action.page && item.status !== "resolved" && <button className="open-task" onClick={() => void openNotification(item)}>前往处理</button>}{item.status === "unread" ? <button onClick={() => void markRead(item)}>标记已读</button> : <span>{item.status === "resolved" ? "已关闭" : "已读"}</span>}</div></div>)}</div> : <div className="notification-empty"><span>✓</span><strong>当前没有{unreadOnly ? "未读" : ""}任务通知</strong><p>补件流转、审批恢复与 SLA 催办消息会按当前角色出现在这里。</p></div>}
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
function levelLabel(level: NotificationRecord["level"]): string { return ({ due_soon: "即将超时", overdue: "已超时", escalated: "升级催办", reminder: "人工催办", assignment: "任务转派", extension: "SLA 延期", task_created: "新增任务", resubmitted: "等待复核", reopened: "重新补件", completed: "核验完成", resumed: "审批恢复", supervisor_reminder: "个人催办", lease_due_soon: "租约临期", lease_expired: "认领回收", policy_blocked: "策略切换阻断" } as const)[level]; }
function formatLease(value: number | null): string { if (value === null) return "即将"; const totalMinutes = Math.max(1, Math.floor(value / 60)); const hours = Math.floor(totalMinutes / 60); const minutes = totalMinutes % 60; return hours ? `${hours}小时${minutes}分` : `${minutes}分钟`; }
function formatTime(value: string | null): string { return value ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "—"; }
