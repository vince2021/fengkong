import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { CreditFacility, CreditFacilityDetail, FacilityAlert, FacilitySummary, RenewalRiskBaseline, RiskEvent } from "./types";


type Notice = { kind: "error" | "success"; text: string };
type FacilityQueueFilter = "all" | "attention" | "critical" | "controls" | "overdue_controls" | "review_due" | "expiring" | "high_utilization";
const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 });


export default function PostCreditCenter({ focusCaseId, focusFacilityId, focusConditionId, canView, canTransact, canReview, canApproveControlExtensions, canScan, canActAlerts, canCreateRiskEvents, canControl, canCreateRenewal, onOpenApproval, onNotice }: { focusCaseId?: string | null; focusFacilityId?: string | null; focusConditionId?: string | null; canView: boolean; canTransact: boolean; canReview: boolean; canApproveControlExtensions: boolean; canScan: boolean; canActAlerts: boolean; canCreateRiskEvents: boolean; canControl: boolean; canCreateRenewal: boolean; onOpenApproval: (caseId: string) => Promise<void>; onNotice: (notice: Notice) => void }) {
  const [summary, setSummary] = useState<FacilitySummary | null>(null);
  const [facilities, setFacilities] = useState<CreditFacility[]>([]);
  const [alerts, setAlerts] = useState<FacilityAlert[]>([]);
  const [riskEvents, setRiskEvents] = useState<RiskEvent[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<CreditFacilityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [transactionType, setTransactionType] = useState<"drawdown" | "repayment">("drawdown");
  const [amount, setAmount] = useState(0);
  const [transactionRef, setTransactionRef] = useState("");
  const [transactionReason, setTransactionReason] = useState("");
  const [reviewRating, setReviewRating] = useState("A");
  const [reviewDays, setReviewDays] = useState(30);
  const [reviewConclusion, setReviewConclusion] = useState("");
  const [eventType, setEventType] = useState("payment_overdue");
  const [eventSeverity, setEventSeverity] = useState<"warning" | "critical">("warning");
  const [eventSource, setEventSource] = useState("内部业务监控");
  const [eventTitle, setEventTitle] = useState("");
  const [eventDescription, setEventDescription] = useState("");
  const [controlAction, setControlAction] = useState<"freeze" | "unfreeze" | "reduce_limit" | "close">("freeze");
  const [controlTarget, setControlTarget] = useState(0);
  const [controlReason, setControlReason] = useState("");
  const [dispositionAlertId, setDispositionAlertId] = useState("");
  const [dispositionAction, setDispositionAction] = useState<"monitor" | "freeze" | "reduce_limit" | "close">("monitor");
  const [dispositionTarget, setDispositionTarget] = useState(0);
  const [dispositionConclusion, setDispositionConclusion] = useState("");
  const [queueQuery, setQueueQuery] = useState("");
  const [queueFilter, setQueueFilter] = useState<FacilityQueueFilter>("all");
  const [statusFilter, setStatusFilter] = useState("");
  const [showRenewalForm, setShowRenewalForm] = useState(false);
  const [renewalLimit, setRenewalLimit] = useState(0);
  const [renewalTermDays, setRenewalTermDays] = useState(30);
  const [renewalReason, setRenewalReason] = useState("");
  const [conditionNotes, setConditionNotes] = useState<Record<string, string>>({});
  const [extensionDays, setExtensionDays] = useState<Record<string, number>>({});
  const [extensionReasons, setExtensionReasons] = useState<Record<string, string>>({});
  const [extensionReviewComments, setExtensionReviewComments] = useState<Record<string, string>>({});
  const facilityMetrics = useMemo(() => ({
    attention: facilities.filter((item) => facilityRiskSignals(item, alerts).length > 0).length,
    critical: facilities.filter((item) => facilityHasCriticalAlert(item.id, alerts)).length,
    controls: facilities.filter((item) => item.pending_control_count > 0).length,
    overdueControls: facilities.filter((item) => item.overdue_control_count > 0).length,
    reviewDue: facilities.filter((item) => ["active", "frozen"].includes(item.status) && isDateWithinDays(item.next_review_at, 30)).length,
    expiring: facilities.filter((item) => item.status === "active" && isUpcomingWithinDays(item.expires_at, 30)).length,
    highUtilization: facilities.filter((item) => item.utilization_rate >= .9).length,
  }), [alerts, facilities]);
  const visibleFacilities = useMemo(() => {
    const keyword = queueQuery.trim().toLocaleLowerCase("zh-CN");
    return sortFacilitiesByRisk(facilities, alerts)
      .filter((item) => !keyword || `${item.counterparty_name} ${item.case_id}`.toLocaleLowerCase("zh-CN").includes(keyword))
      .filter((item) => !statusFilter || item.status === statusFilter)
      .filter((item) => {
        if (queueFilter === "attention") return facilityRiskSignals(item, alerts).length > 0;
        if (queueFilter === "critical") return facilityHasCriticalAlert(item.id, alerts);
        if (queueFilter === "controls") return item.pending_control_count > 0;
        if (queueFilter === "overdue_controls") return item.overdue_control_count > 0;
        if (queueFilter === "review_due") return ["active", "frozen"].includes(item.status) && isDateWithinDays(item.next_review_at, 30);
        if (queueFilter === "expiring") return item.status === "active" && isUpcomingWithinDays(item.expires_at, 30);
        if (queueFilter === "high_utilization") return item.utilization_rate >= .9;
        return true;
      });
  }, [alerts, facilities, queueFilter, queueQuery, statusFilter]);

  const reload = useCallback(async (focusId?: string) => {
    if (!canView) return;
    setLoading(true);
    try {
      const [summaryRow, facilityRows, alertRows, eventRows] = await Promise.all([api.facilitySummary(), api.creditFacilities(), api.facilityAlerts(), api.riskEvents()]);
      setSummary(summaryRow);
      setFacilities(facilityRows);
      setAlerts(alertRows);
      setRiskEvents(eventRows);
      const focusedFacilityId = focusFacilityId && facilityRows.some((item) => item.id === focusFacilityId)
        ? focusFacilityId
        : focusCaseId ? facilityRows.find((item) => item.case_id === focusCaseId)?.id : undefined;
      const existingFacilityId = facilityRows.some((item) => item.id === selectedId) ? selectedId : undefined;
      const target = focusId || focusedFacilityId || existingFacilityId || sortFacilitiesByRisk(facilityRows, alertRows)[0]?.id || "";
      setSelectedId(target);
      setSelected(target ? await api.creditFacility(target) : null);
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "贷后工作台加载失败" }); }
    finally { setLoading(false); }
  }, [canView, focusCaseId, focusFacilityId, onNotice, selectedId]);

  useEffect(() => { void reload(); }, [canView, focusCaseId]);
  useEffect(() => {
    if (!selectedId || !canView) return;
    void api.creditFacility(selectedId).then((row) => { setSelected(row); setReviewRating(row.rating); }).catch((error: Error) => onNotice({ kind: "error", text: error.message }));
  }, [selectedId, canView, onNotice]);
  useEffect(() => {
    if (!selected) return;
    setShowRenewalForm(false);
    setRenewalLimit(selected.approved_limit);
    setRenewalTermDays(selected.payment_term_days);
    setRenewalReason("");
  }, [selected?.id]);
  useEffect(() => {
    if (!selected || !focusConditionId || !selected.control_conditions.some((item) => item.id === focusConditionId)) return;
    const frame = requestAnimationFrame(() => document.getElementById(`facility-condition-${focusConditionId}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
    return () => cancelAnimationFrame(frame);
  }, [focusConditionId, selected]);

  async function transact() {
    if (!selected) return;
    setBusy("transaction");
    try {
      const result = await api.transactFacility(selected.id, { transaction_ref: transactionRef || `TX-${Date.now()}`, transaction_type: transactionType, amount, expected_row_version: selected.row_version, reason: transactionReason });
      await reload(selected.id);
      setAmount(0); setTransactionRef(""); setTransactionReason("");
      onNotice({ kind: "success", text: result.idempotent ? "重复请求已按幂等规则返回原交易" : transactionType === "drawdown" ? "额度占用成功" : "额度归还成功" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "额度交易失败" }); }
    finally { setBusy(""); }
  }

  async function review() {
    if (!selected) return;
    setBusy("review");
    try {
      await api.reviewFacility(selected.id, { expected_row_version: selected.row_version, rating: reviewRating, next_review_days: reviewDays, conclusion: reviewConclusion });
      await reload(selected.id); setReviewConclusion("");
      onNotice({ kind: "success", text: "贷后复评已完成" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "贷后复评失败" }); }
    finally { setBusy(""); }
  }

  async function scan() {
    setBusy("scan");
    try { const result = await api.scanFacilities(); await reload(selectedId); onNotice({ kind: "success", text: `扫描 ${result.active_facilities_scanned} 笔授信和 ${result.control_conditions_scanned} 项逾期条件，新增 ${result.alerts_opened} 条预警、升级 ${result.control_conditions_escalated} 项任务并发送 ${result.control_notifications_created} 条通知` }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "贷后扫描失败" }); }
    finally { setBusy(""); }
  }

  async function acknowledge(alert: FacilityAlert) {
    setBusy(alert.id);
    try { await api.acknowledgeFacilityAlert(alert.id); await reload(selectedId); onNotice({ kind: "success", text: "预警已确认接收" }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "预警处理失败" }); }
    finally { setBusy(""); }
  }

  async function createRiskEvent() {
    if (!selected) return;
    setBusy("risk-event");
    try {
      const result = await api.createRiskEvent(selected.id, { external_event_id: `MANUAL-${Date.now()}`, event_type: eventType, source: eventSource, severity: eventSeverity, occurred_at: new Date().toISOString(), title: eventTitle, description: eventDescription, payload: {} });
      await reload(selected.id); setEventTitle(""); setEventDescription("");
      onNotice({ kind: "success", text: result.idempotent ? "风险事件已存在，返回原记录" : "风险事件已归档并生成预警" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "风险事件登记失败" }); }
    finally { setBusy(""); }
  }

  async function controlFacility() {
    if (!selected) return;
    setBusy("control");
    try {
      await api.controlFacility(selected.id, { expected_row_version: selected.row_version, action: controlAction, ...(controlAction === "reduce_limit" ? { target_limit: controlTarget } : {}), reason: controlReason });
      await reload(selected.id); setControlReason(""); setControlTarget(0);
      onNotice({ kind: "success", text: "授信控制已执行并写入审计链" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "授信控制失败" }); }
    finally { setBusy(""); }
  }

  async function disposeAlert() {
    const alert = alerts.find((item) => item.id === dispositionAlertId);
    const facility = facilities.find((item) => item.id === alert?.facility_id);
    if (!alert || !facility) return;
    setBusy("disposition");
    try {
      await api.disposeFacilityAlert(alert.id, { expected_alert_version: alert.row_version, expected_facility_version: facility.row_version, action: dispositionAction, ...(dispositionAction === "reduce_limit" ? { target_limit: dispositionTarget } : {}), conclusion: dispositionConclusion });
      await reload(facility.id); setDispositionAlertId(""); setDispositionConclusion(""); setDispositionTarget(0);
      onNotice({ kind: "success", text: "预警已完成处置闭环" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "预警处置失败" }); }
    finally { setBusy(""); }
  }

  async function completeCondition(conditionId: string, rowVersion: number) {
    if (!selected) return;
    const conclusion = conditionNotes[conditionId]?.trim() ?? "";
    if (conclusion.length < 5) return;
    setBusy(`condition:${conditionId}`);
    try {
      await api.completeFacilityControlCondition(selected.id, conditionId, { expected_row_version: rowVersion, conclusion });
      setConditionNotes((current) => ({ ...current, [conditionId]: "" }));
      await reload(selected.id);
      onNotice({ kind: "success", text: "控制条件已完成并写入贷后审计轨迹" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "控制条件闭环失败" }); }
    finally { setBusy(""); }
  }

  async function requestConditionExtension(conditionId: string, rowVersion: number) {
    if (!selected) return;
    const days = extensionDays[conditionId] ?? 7;
    const reason = extensionReasons[conditionId]?.trim() ?? "";
    if (reason.length < 10) return;
    setBusy(`extension:${conditionId}`);
    try {
      await api.requestFacilityControlExtension(selected.id, conditionId, { expected_condition_version: rowVersion, extension_days: days, reason });
      setExtensionReasons((current) => ({ ...current, [conditionId]: "" }));
      await reload(selected.id);
      onNotice({ kind: "success", text: "延期申请已提交授信审批人独立审批" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "延期申请提交失败" }); }
    finally { setBusy(""); }
  }

  async function reviewConditionExtension(conditionId: string, conditionVersion: number, extensionId: string, extensionVersion: number, decision: "approve" | "reject") {
    if (!selected) return;
    const comment = extensionReviewComments[extensionId]?.trim() ?? "";
    if (comment.length < 5) return;
    setBusy(`extension-review:${extensionId}`);
    try {
      await api.reviewFacilityControlExtension(selected.id, conditionId, extensionId, { expected_extension_version: extensionVersion, expected_condition_version: conditionVersion, decision, comment });
      setExtensionReviewComments((current) => ({ ...current, [extensionId]: "" }));
      await reload(selected.id);
      onNotice({ kind: "success", text: decision === "approve" ? "延期已批准，新截止日及预警状态已同步更新" : "延期申请已驳回并通知申请人" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "延期审批失败" }); }
    finally { setBusy(""); }
  }

  async function createRenewal() {
    if (!selected) return;
    setBusy("renewal");
    try {
      const result = await api.createFacilityRenewal(selected.id, {
        expected_row_version: selected.row_version,
        requested_limit: renewalLimit,
        requested_term_days: renewalTermDays,
        renewal_reason: renewalReason,
      });
      await reload(selected.id);
      onNotice({ kind: "success", text: result.idempotent ? `已打开在途续授信 ${result.case_id}` : `续授信 ${result.case_id} 已创建，请更新并核验资料` });
      await onOpenApproval(result.case_id);
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "续授信发起失败" }); }
    finally { setBusy(""); }
  }

  if (!canView) return <div className="panel post-credit-empty"><strong>当前身份无贷后管理权限</strong><p>请切换为客户经理、风控、审批、运营或审计角色。</p></div>;
  if (loading && !summary) return <div className="panel post-credit-empty">正在加载授信台账…</div>;
  const dispositionAlert = alerts.find((item) => item.id === dispositionAlertId);
  const selectedAlerts = selected ? alerts.filter((item) => item.facility_id === selected.id && item.status !== "resolved") : [];
  const selectedGuide = selected ? facilityOperationGuide(selected, selectedAlerts) : null;
  const selectedHidden = Boolean(selected && !visibleFacilities.some((item) => item.id === selected.id));
  const renewalTerminal = Boolean(selected?.renewal_case && ["已完成", "已拒绝", "已撤回"].includes(selected.renewal_case.status));
  const canStartRenewal = Boolean(selected && canCreateRenewal && selected.status !== "closed" && (!selected.renewal_case || renewalTerminal));
  const renewalSnapshot = selected?.renewal_case?.request_snapshot;
  const renewalBelowBalance = Boolean(selected && renewalLimit < selected.used_limit);
  const currentCapabilities = [
    canTransact ? "额度交易" : "",
    canReview ? "贷后复评" : "",
    canApproveControlExtensions ? "控制条件延期审批" : "",
    canCreateRiskEvents ? "登记风险事件" : "",
    canActAlerts ? "预警处置" : "",
    canControl ? "授信控制" : "",
    canCreateRenewal ? "发起续授信" : "",
  ].filter(Boolean);

  return <div className="post-credit-center">
    <section className="post-credit-hero"><div><span>POST-CREDIT CONTROL</span><h2>授信台账与贷后风险控制</h2><p>最终审批自动形成可执行额度账户，所有占用、归还、复评和预警均可追溯。</p></div>{canScan && <button className="primary-button" disabled={busy === "scan"} onClick={() => void scan()}>{busy === "scan" ? "正在扫描…" : "运行贷后扫描"}</button>}</section>
    {summary && <section className="facility-metric-grid"><Metric label="生效授信" value={String(summary.active_facilities)} suffix="笔" /><Metric label="批准额度" value={formatWan(summary.approved_limit)} suffix="万元" /><Metric label="已用额度" value={formatWan(summary.used_limit)} suffix="万元" tone="amber" /><Metric label="可用额度" value={formatWan(summary.available_limit)} suffix="万元" tone="teal" /><Metric label="未闭环预警" value={String(summary.unresolved_alerts)} suffix="条" tone={summary.critical_alerts ? "red" : "blue"} /></section>}

    <section className="panel facility-task-radar">
      <div className="post-section-head"><div><span>POST-CREDIT TASK RADAR</span><h2>贷后任务雷达</h2><p>优先处理严重预警、逾期控制条件、状态异常、复评与到期任务，再关注高额度使用率。</p></div><small>{visibleFacilities.length} / {facilities.length} 笔</small></div>
      <div className="facility-task-metrics">
        <button className={queueFilter === "attention" ? "active" : ""} onClick={() => setQueueFilter("attention")}><span>需关注</span><strong>{facilityMetrics.attention}</strong><small>至少一项风险信号</small></button>
        <button className={`critical ${queueFilter === "critical" ? "active" : ""}`} onClick={() => setQueueFilter("critical")}><span>严重预警</span><strong>{facilityMetrics.critical}</strong><small>风控优先处置</small></button>
        <button className={queueFilter === "controls" ? "active" : ""} onClick={() => setQueueFilter("controls")}><span>待落实条件</span><strong>{facilityMetrics.controls}</strong><small>{summary?.pending_control_conditions ?? 0} 项控制任务</small></button>
        <button className={`critical ${queueFilter === "overdue_controls" ? "active" : ""}`} onClick={() => setQueueFilter("overdue_controls")}><span>逾期控制条件</span><strong>{facilityMetrics.overdueControls}</strong><small>{summary?.overdue_control_conditions ?? 0} 项逾期 · {summary?.critical_control_conditions ?? 0} 项升级</small></button>
        <button className={queueFilter === "review_due" ? "active" : ""} onClick={() => setQueueFilter("review_due")}><span>30日内复评</span><strong>{facilityMetrics.reviewDue}</strong><small>含已逾期任务</small></button>
        <button className={queueFilter === "expiring" ? "active" : ""} onClick={() => setQueueFilter("expiring")}><span>30日内到期</span><strong>{facilityMetrics.expiring}</strong><small>需续评或退出</small></button>
        <button className={queueFilter === "high_utilization" ? "active" : ""} onClick={() => setQueueFilter("high_utilization")}><span>高使用率</span><strong>{facilityMetrics.highUtilization}</strong><small>额度使用 ≥ 90%</small></button>
      </div>
      <div className="facility-queue-toolbar">
        <label><span>搜索企业或审批单</span><input value={queueQuery} onChange={(event) => setQueueQuery(event.target.value)} placeholder="企业名称 / 申请编号" aria-label="搜索贷后授信" /></label>
        <label><span>授信状态</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="按授信状态筛选"><option value="">全部状态</option><option value="active">生效中</option><option value="frozen">已冻结</option><option value="expired">已到期</option><option value="closed">已关闭</option></select></label>
        <label><span>任务范围</span><select value={queueFilter} onChange={(event) => setQueueFilter(event.target.value as FacilityQueueFilter)} aria-label="按贷后任务筛选"><option value="all">全部授信</option><option value="attention">需关注</option><option value="critical">严重预警</option><option value="controls">待落实控制条件</option><option value="overdue_controls">逾期控制条件</option><option value="review_due">30日内复评</option><option value="expiring">30日内到期</option><option value="high_utilization">高使用率</option></select></label>
        <button onClick={() => { setQueueQuery(""); setStatusFilter(""); setQueueFilter("all"); }}>重置筛选</button>
      </div>
      <div className="facility-queue-rule"><span>排序规则</span><strong>严重预警 → 逾期控制条件 → 状态异常 → 复评/到期 → 高使用率 → 最近任务日期</strong></div>
      {selectedHidden && <div className="facility-hidden-selection"><span>右侧当前授信已被筛选条件隐藏</span><button onClick={() => { setQueueQuery(""); setStatusFilter(""); setQueueFilter("all"); }}>显示当前授信</button></div>}
    </section>

    <section className="facility-work-grid">
      <div className="panel facility-list-panel"><div className="post-section-head"><div><span>PRIORITY FACILITY QUEUE</span><h2>贷后优先队列</h2></div><small>{visibleFacilities.length} 笔</small></div>{visibleFacilities.length ? <div className="facility-list">{visibleFacilities.map((item) => {
        const signals = facilityRiskSignals(item, alerts);
        return <button className={`facility-row ${selectedId === item.id ? "selected" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}><div><strong>{item.counterparty_name}</strong><span className={`facility-status ${item.status}`}>{statusLabel(item.status)}</span></div><p>{item.rating} · {item.access_strategy} · 账期 {item.payment_term_days} 天</p><div className="facility-row-signals">{signals.length ? signals.slice(0, 2).map((signal) => <span className={signal.tone} key={signal.key}>{signal.label}</span>) : <span className="healthy">当前无待办风险</span>}</div><div className="utilization-line"><i style={{ width: `${Math.min(item.utilization_rate * 100, 100)}%` }} /><span>{(item.utilization_rate * 100).toFixed(1)}%</span></div><footer><span>可用 {money.format(item.available_limit)}</span><small>{formatDate(item.next_review_at)} 复评</small></footer></button>;
      })}</div> : <div className="post-credit-empty compact"><strong>{facilities.length ? "没有符合条件的授信" : "暂无已生效授信"}</strong><p>{facilities.length ? "调整任务范围、状态或搜索条件后重试。" : "通过最终审批后会自动生成授信台账。"}</p>{facilities.length > 0 && <button onClick={() => { setQueueQuery(""); setStatusFilter(""); setQueueFilter("all"); }}>清除筛选</button>}</div>}</div>

      <div className="panel facility-detail-panel">{selected ? <><div className="post-section-head"><div><span>FACILITY DETAIL</span><h2>{selected.counterparty_name}</h2></div><span className={`facility-status ${selected.status}`}>{statusLabel(selected.status)}</span></div><div className="facility-balance"><div><span>批准额度</span><strong>{money.format(selected.approved_limit)}</strong></div><div><span>已用额度</span><strong>{money.format(selected.used_limit)}</strong></div><div><span>可用额度</span><strong>{money.format(selected.available_limit)}</strong></div></div><div className="facility-meta"><span>评级 <b>{selected.rating}</b></span><span>监控频率 <b>{selected.monitoring_frequency}</b></span><span>下次复评 <b>{formatDate(selected.next_review_at)}</b></span><span>授信到期 <b>{formatDate(selected.expires_at)}</b></span>{selected.supersedes_facility_id && <span>承接自 <b>{selected.supersedes_facility_id.slice(0, 8)}</b></span>}{selected.opening_balance > 0 && <span>期初承接余额 <b>{money.format(selected.opening_balance)}</b></span>}</div>
        {selectedGuide && <section className={`facility-operation-guide ${selectedGuide.tone}`}><header><div><span>NEXT BEST ACTION</span><strong>{selectedGuide.title}</strong></div><i>{selectedGuide.priority}</i></header><div><p><span>当前风险</span><strong>{selectedGuide.risk}</strong></p><p><span>责任角色</span><strong>{selectedGuide.owner}</strong></p><p><span>应该怎么做</span><strong>{selectedGuide.action}</strong></p><p><span>完成条件</span><strong>{selectedGuide.completion}</strong></p></div><footer><span>当前身份权限范围（具体动作仍受授信状态与字段门禁控制）</span><strong>{currentCapabilities.length ? currentCapabilities.join(" · ") : "仅可查看，无处置权限"}</strong></footer></section>}
        {(selected.renewal_case || canStartRenewal) && <section className="facility-renewal-panel">
          <header><div><span>FACILITY RENEWAL</span><strong>续授信与额度承接</strong></div>{selected.renewal_case && <i className={renewalTerminal ? "terminal" : "active"}>{selected.renewal_case.status}</i>}</header>
          {selected.renewal_case && <><div className="renewal-linked-case"><div><span>最近续授信审批</span><strong>{selected.renewal_case.case_id}</strong><small>{stageName(selected.renewal_case.current_stage)} · {formatDateTime(selected.renewal_case.created_at)}</small></div><button onClick={() => void onOpenApproval(selected.renewal_case!.case_id)}>查看审批流程</button></div>{renewalSnapshot && <><div className="renewal-request-comparison"><div><span>原批准额度</span><strong>{money.format(renewalSnapshot.current_approved_limit)}</strong><i>→</i><b>{money.format(renewalSnapshot.requested_limit)}</b><small className={deltaTone(renewalSnapshot.limit_delta)}>{signedMoney(renewalSnapshot.limit_delta)}</small></div><div><span>原账期</span><strong>{renewalSnapshot.current_payment_term_days} 天</strong><i>→</i><b>{renewalSnapshot.requested_term_days} 天</b><small className={deltaTone(renewalSnapshot.term_delta_days)}>{signedDays(renewalSnapshot.term_delta_days)}</small></div><div><span>基线风险条件</span><strong>{renewalSnapshot.current_rating ?? "—"} · {renewalSnapshot.current_access_strategy ?? "—"}</strong><i>→</i><b>待重新评级</b><small>{renewalSnapshot.baseline_status === "frozen" ? "发起时冻结" : "历史台账兼容补齐"} · {renewalSnapshot.current_monitoring_frequency ?? "—"}</small></div><p>{renewalSnapshot.renewal_reason}</p></div><RenewalRiskBaselineCard baseline={renewalSnapshot.risk_baseline} /></>}</>}
          {canStartRenewal && <><p>{renewalTerminal ? "最近一次续授信已结束，可基于最新经营与风险资料重新发起。" : "复用已核验企业主体，但更新后的业务、财务与授权资料必须重新上传并由独立风控核验。审批通过时，旧台账已用余额将原子承接到新台账。"}</p>
            {!showRenewalForm ? <button className="renewal-start" onClick={() => setShowRenewalForm(true)}>{renewalTerminal ? "重新发起续授信" : "发起续授信"}</button> : <div className="renewal-form"><div className="renewal-live-diff"><span>当前额度 <b>{money.format(selected.approved_limit)}</b></span><i>→</i><span>申请额度 <b>{money.format(renewalLimit)}</b></span><em className={deltaTone(renewalLimit - selected.approved_limit)}>{signedMoney(renewalLimit - selected.approved_limit)}</em></div><label><span>申请额度（元）</span><input type="number" min={selected.used_limit} step="0.01" value={renewalLimit} onChange={(event) => setRenewalLimit(Number(event.target.value))} /></label><label><span>申请账期（天）</span><input type="number" min="0" max="365" value={renewalTermDays} onChange={(event) => setRenewalTermDays(Number(event.target.value))} /></label><div className={`renewal-balance-gate wide ${renewalBelowBalance ? "blocked" : "pass"}`}><span>{renewalBelowBalance ? "申请被阻断" : "余额承接门禁通过"}</span><strong>当前已用余额 {money.format(selected.used_limit)}，申请额度不得低于该金额</strong></div><label className="wide"><span>续授信原因与业务依据</span><textarea value={renewalReason} maxLength={1000} onChange={(event) => setRenewalReason(event.target.value)} placeholder="说明续期原因、预计业务规模及风险变化…" /></label><div className="renewal-form-actions"><button className="secondary" onClick={() => setShowRenewalForm(false)}>取消</button><button disabled={busy === "renewal" || renewalLimit <= 0 || renewalBelowBalance || renewalTermDays < 0 || renewalTermDays > 365 || renewalReason.trim().length < 2} onClick={() => void createRenewal()}>{busy === "renewal" ? "正在创建…" : "创建续授信审批"}</button></div></div>}
          </>}
        </section>}
        {selected.control_conditions.length > 0 && <section className="facility-control-conditions">
          <header><div><span>APPROVAL CONDITIONS · SLA</span><strong>审批控制条件执行与升级台账</strong><p>控制条件按截止日自动预警；逾期 7 天升级授信审批人，逾期 30 天升级平台管理员。</p></div><i>{selected.pending_control_count} 待完成 · {selected.overdue_control_count} 已逾期</i></header>
          <div>{selected.control_conditions.map((condition) => <article id={`facility-condition-${condition.id}`} className={`${condition.status} ${condition.sla_status} escalation-${condition.escalation_level} ${focusConditionId === condition.id ? "focused" : ""}`} key={condition.id}>
            <span>{String(condition.sequence).padStart(2, "0")}</span>
            <div>
              <strong>{condition.measure}</strong>
              <small>执行：风控经理 · 截止 {formatDate(condition.due_at)} · 来源审批 {condition.source_case_id}</small>
              {condition.status === "pending" && <div className="condition-sla-line"><b>{conditionSlaLabel(condition.sla_status, condition.days_remaining, condition.overdue_days)}</b>{condition.escalation_role && <em>督办：{conditionRoleLabel(condition.escalation_role)} · L{condition.escalation_level}</em>}</div>}
              {condition.status === "completed" && <p>{condition.completion_note} · {condition.completed_by} · {formatDateTime(condition.completed_at)}</p>}
              {condition.extension_requests.length > 0 && <div className="condition-extension-history">{condition.extension_requests.map((extension) => <section className={extension.status} key={extension.id}><header><b>{extensionStatusLabel(extension.status)}</b><span>延期 {extension.extension_days} 天 · 新截止 {formatDate(extension.proposed_due_at)}</span></header><p>{extension.reason}</p><small>申请：{extension.requested_by_name} · {formatDateTime(extension.requested_at)}{extension.reviewed_by_name ? ` · 审批：${extension.reviewed_by_name}` : ""}</small>{extension.review_comment && <em>审批意见：{extension.review_comment}</em>}{extension.status === "pending" && canApproveControlExtensions && <div className="condition-extension-review"><input value={extensionReviewComments[extension.id] ?? ""} onChange={(event) => setExtensionReviewComments((current) => ({ ...current, [extension.id]: event.target.value }))} placeholder="填写独立审批意见（不少于5字）" /><button className="reject" disabled={busy === `extension-review:${extension.id}` || (extensionReviewComments[extension.id]?.trim().length ?? 0) < 5} onClick={() => void reviewConditionExtension(condition.id, condition.row_version, extension.id, extension.row_version, "reject")}>驳回</button><button disabled={busy === `extension-review:${extension.id}` || (extensionReviewComments[extension.id]?.trim().length ?? 0) < 5} onClick={() => void reviewConditionExtension(condition.id, condition.row_version, extension.id, extension.row_version, "approve")}>批准延期</button></div>}</section>)}</div>}
              {condition.status === "pending" && canReview && !condition.extension_requests.some((item) => item.status === "pending") && condition.extension_requests.filter((item) => item.status === "approved").length < 2 && condition.overdue_days < 30 && <div className="condition-extension-request"><span>无法按原计划完成？申请受控延期</span><select value={extensionDays[condition.id] ?? 7} onChange={(event) => setExtensionDays((current) => ({ ...current, [condition.id]: Number(event.target.value) }))}>{[3, 7, 14, 21, 30].map((days) => <option key={days} value={days}>{days} 天</option>)}</select><input value={extensionReasons[condition.id] ?? ""} onChange={(event) => setExtensionReasons((current) => ({ ...current, [condition.id]: event.target.value }))} placeholder="说明延期原因、当前进展及证据（不少于10字）" /><button disabled={busy === `extension:${condition.id}` || (extensionReasons[condition.id]?.trim().length ?? 0) < 10} onClick={() => void requestConditionExtension(condition.id, condition.row_version)}>{busy === `extension:${condition.id}` ? "提交中…" : "提交延期申请"}</button><small>单次最多 30 天、累计最多 60 天；必须由授信审批人独立批准。</small></div>}
              {condition.status === "pending" && canReview && !condition.extension_requests.some((item) => item.status === "pending") && (condition.overdue_days >= 30 || condition.extension_requests.filter((item) => item.status === "approved").length >= 2) && <div className="condition-extension-blocked">{condition.overdue_days >= 30 ? "已严重逾期，30 天延期无法形成未来截止日；请立即完成条件或执行授信控制。" : "该条件已达到两次延期上限，请完成条件或登记风险并执行授信控制。"}</div>}
              {condition.status === "pending" && canReview && <label><input value={conditionNotes[condition.id] ?? ""} onChange={(event) => setConditionNotes((current) => ({ ...current, [condition.id]: event.target.value }))} placeholder="填写执行结果和核验证据（不少于5字）" /><button disabled={busy === `condition:${condition.id}` || (conditionNotes[condition.id]?.trim().length ?? 0) < 5} onClick={() => void completeCondition(condition.id, condition.row_version)}>{busy === `condition:${condition.id}` ? "提交中…" : "完成条件"}</button></label>}
            </div>
            <i>{condition.status === "completed" ? "已完成" : condition.sla_status === "overdue" ? `逾期 ${condition.overdue_days} 天` : condition.sla_status === "due_soon" ? "即将到期" : "按期执行"}</i>
          </article>)}</div>
        </section>}
        {(canTransact || canReview || canCreateRiskEvents || canControl) && <section className="facility-action-workbench">
          <header><div><span>ACTION WORKBENCH</span><h3>授信业务与风险操作</h3><p>每类操作独立分区；提交前请确认当前授信状态、业务依据和风险影响。</p></div><small>{currentCapabilities.length} 类可用操作</small></header>
          <div className="facility-actions">
          {canTransact && <div className="facility-action-module transaction"><header><i>01</i><div><h3>额度交易</h3><p>处理额度占用与归还</p></div></header><div className="action-form-grid"><select aria-label="额度交易类型" value={transactionType} onChange={(event) => setTransactionType(event.target.value as "drawdown" | "repayment")}><option value="drawdown">额度占用</option><option value="repayment">额度归还</option></select><input aria-label="额度交易金额" type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(Number(event.target.value))} placeholder="金额" /><input aria-label="业务交易号" value={transactionRef} onChange={(event) => setTransactionRef(event.target.value)} placeholder="业务交易号（留空自动生成）" /><input aria-label="额度交易原因" value={transactionReason} onChange={(event) => setTransactionReason(event.target.value)} placeholder="交易原因" /></div><button disabled={busy === "transaction" || selected.status !== "active" || amount <= 0 || transactionReason.trim().length < 2} onClick={() => void transact()}>{busy === "transaction" ? "处理中…" : "提交额度交易"}</button></div>}
          {canReview && <div className="facility-action-module review"><header><i>02</i><div><h3>贷后复评</h3><p>更新评级与下次复评周期</p></div></header><div className="action-form-grid"><select aria-label="复评评级" value={reviewRating} onChange={(event) => setReviewRating(event.target.value)}>{["AAA", "AA", "A", "BBB", "BB", "B", "D"].map((item) => <option key={item}>{item}</option>)}</select><input aria-label="下次复评间隔天数" type="number" min="1" max="365" value={reviewDays} onChange={(event) => setReviewDays(Number(event.target.value))} /><input aria-label="复评结论" className="wide" value={reviewConclusion} onChange={(event) => setReviewConclusion(event.target.value)} placeholder="复评结论与风险变化" /></div><button disabled={busy === "review" || selected.status !== "active" || reviewConclusion.trim().length < 2} onClick={() => void review()}>{busy === "review" ? "提交中…" : "完成贷后复评"}</button></div>}
          {canCreateRiskEvents && <div className="facility-action-module risk-event"><header><i>03</i><div><h3>登记风险事件</h3><p>形成可处置的预警线索</p></div></header><div className="action-form-grid"><select aria-label="风险事件类型" value={eventType} onChange={(event) => setEventType(event.target.value)}><option value="payment_overdue">回款逾期</option><option value="litigation">诉讼风险</option><option value="business_abnormal">经营异常</option><option value="negative_public_opinion">负面舆情</option><option value="financial_deterioration">财务恶化</option><option value="ownership_change">股权变更</option><option value="other">其他风险</option></select><select aria-label="风险事件等级" value={eventSeverity} onChange={(event) => setEventSeverity(event.target.value as "warning" | "critical")}><option value="warning">一般预警</option><option value="critical">严重预警</option></select><input aria-label="风险事件来源" value={eventSource} onChange={(event) => setEventSource(event.target.value)} placeholder="事件来源" /><input aria-label="风险事件标题" value={eventTitle} onChange={(event) => setEventTitle(event.target.value)} placeholder="事件标题" /><input aria-label="风险事实与影响" className="wide" value={eventDescription} onChange={(event) => setEventDescription(event.target.value)} placeholder="风险事实与影响" /></div><button disabled={busy === "risk-event" || eventSource.trim().length < 2 || eventTitle.trim().length < 2 || eventDescription.trim().length < 2} onClick={() => void createRiskEvent()}>{busy === "risk-event" ? "登记中…" : "登记并生成预警"}</button></div>}
          {canControl && <div className="facility-action-module control"><header><i>04</i><div><h3>授信控制</h3><p>冻结、压降或关闭授信</p></div></header><div className="action-form-grid"><select aria-label="授信控制动作" value={controlAction} onChange={(event) => setControlAction(event.target.value as "freeze" | "unfreeze" | "reduce_limit" | "close")}><option value="freeze">冻结授信</option><option value="unfreeze">解除冻结</option><option value="reduce_limit">压降额度</option><option value="close">关闭授信</option></select>{controlAction === "reduce_limit" && <input aria-label="压降后目标额度" type="number" min="0" step="0.01" value={controlTarget} onChange={(event) => setControlTarget(Number(event.target.value))} placeholder="目标额度" />}<input aria-label="授信控制原因" className="wide" value={controlReason} onChange={(event) => setControlReason(event.target.value)} placeholder="控制原因与审批依据" /></div><button disabled={busy === "control" || controlReason.trim().length < 2 || (controlAction === "reduce_limit" && controlTarget <= 0)} onClick={() => void controlFacility()}>{busy === "control" ? "执行中…" : "执行授信控制"}</button></div>}
          </div>
        </section>}
        <div className="transaction-history"><h3>额度流水</h3>{selected.transactions.length ? selected.transactions.map((item) => <div key={item.id}><span className={item.transaction_type}>{item.transaction_type === "drawdown" ? "占用" : "归还"}</span><div><strong>{money.format(item.amount)}</strong><small>{item.transaction_ref} · {item.actor} · {formatDateTime(item.occurred_at)}</small></div><b>余额 {money.format(item.balance_after)}</b></div>) : <p>暂无额度交易</p>}</div></> : <div className="post-credit-empty">请选择一笔授信台账</div>}</div>
    </section>

    <section className="panel risk-event-panel"><div className="post-section-head"><div><span>RISK EVENT HUB</span><h2>风险事件台账</h2></div><small>{riskEvents.filter((item) => item.status === "active").length} 条活跃事件</small></div>{riskEvents.length ? <div className="risk-event-list">{riskEvents.map((item) => <article className={`${item.severity} ${item.status}`} key={item.id}><span>{eventTypeLabel(item.event_type)}</span><div><strong>{item.title}</strong><p>{item.counterparty_name} · {item.description}</p><small>{item.source} · {formatDateTime(item.occurred_at)} · {item.external_event_id}</small></div><i>{item.status === "resolved" ? "已解决" : item.severity === "critical" ? "严重" : "关注"}</i></article>)}</div> : <div className="post-credit-empty compact"><strong>暂无风险事件</strong><p>业务监控或外部数据源发现风险后，可在授信详情中登记。</p></div>}</section>

    <section className="panel facility-alert-panel"><div className="post-section-head"><div><span>EARLY WARNING</span><h2>贷后风险预警</h2></div><small>{alerts.filter((item) => item.status !== "resolved").length} 条未闭环</small></div>{alerts.length ? <div className="facility-alert-list">{alerts.map((item) => <div className={`facility-alert ${item.severity} ${item.status}`} key={item.id}><span>{item.severity === "critical" ? "!!" : "!"}</span><div><strong>{item.title}</strong><p>{item.counterparty_name} · {item.message}</p><small>{formatDateTime(item.created_at)}{item.disposition_note ? ` · ${item.disposition_note}` : ""}</small></div><div className="alert-command">{canActAlerts && item.status === "open" && <button disabled={busy === item.id} onClick={() => void acknowledge(item)}>确认接收</button>}{canActAlerts && item.status !== "resolved" && item.alert_type !== "control_condition_overdue" && <button className="secondary" onClick={() => { setDispositionAlertId(item.id); setDispositionAction("monitor"); }}>处置预警</button>}{item.status !== "resolved" && item.alert_type === "control_condition_overdue" && <i>完成控制条件后自动闭环</i>}{item.status === "resolved" && <i>{alertStatus(item.status)}</i>}</div></div>)}</div> : <div className="post-credit-empty compact"><strong>暂无贷后预警</strong></div>}
      {dispositionAlert && <div className="alert-disposition-form"><header><div><span>DISPOSITION</span><strong>处置：{dispositionAlert.title}</strong></div><button onClick={() => setDispositionAlertId("")}>取消</button></header><div className="action-form-grid"><select value={dispositionAction} onChange={(event) => setDispositionAction(event.target.value as "monitor" | "freeze" | "reduce_limit" | "close")}><option value="monitor">持续监控并闭环</option>{canControl && <option value="freeze">冻结授信</option>}{canControl && <option value="reduce_limit">压降额度</option>}{canControl && <option value="close">关闭授信</option>}</select>{dispositionAction === "reduce_limit" && <input type="number" min="0" step="0.01" value={dispositionTarget} onChange={(event) => setDispositionTarget(Number(event.target.value))} placeholder="目标额度" />}<input className="wide" value={dispositionConclusion} onChange={(event) => setDispositionConclusion(event.target.value)} placeholder="核查结论、控制依据与后续安排" /></div><button disabled={busy === "disposition" || dispositionConclusion.trim().length < 2 || (dispositionAction === "reduce_limit" && dispositionTarget <= 0)} onClick={() => void disposeAlert()}>{busy === "disposition" ? "处置中…" : "提交处置结论"}</button></div>}
    </section>
  </div>;
}

function RenewalRiskBaselineCard({ baseline }: { baseline: RenewalRiskBaseline }) {
  const hasCritical = baseline.critical_alert_count > 0 || baseline.critical_risk_event_count > 0;
  const hasSignals = baseline.unresolved_alert_count > 0 || baseline.active_risk_event_count > 0;
  const tone = baseline.capture_status === "legacy_missing" ? "legacy" : hasCritical ? "critical" : hasSignals ? "warning" : "clear";
  return <section className={`renewal-risk-baseline ${tone}`}>
    <header><div><span>RISK BASELINE</span><strong>续授信发起时风险快照</strong></div><i>{baseline.capture_status === "legacy_missing" ? "历史未捕获" : hasCritical ? "重大风险待复核" : hasSignals ? "存在风险信号" : "未见未结风险"}</i></header>
    <div><span><small>未结预警</small><b>{baseline.unresolved_alert_count}</b></span><span><small>严重预警</small><b>{baseline.critical_alert_count}</b></span><span><small>活跃事件</small><b>{baseline.active_risk_event_count}</b></span><span><small>严重事件</small><b>{baseline.critical_risk_event_count}</b></span></div>
    {baseline.signals.length > 0 && <ul>{baseline.signals.slice(0, 3).map((signal, index) => <li className={signal.severity} key={`${signal.alert_type}-${index}`}><i>{signal.severity === "critical" ? "!!" : "!"}</i><span><strong>{signal.title}</strong><small>{signal.message}</small></span></li>)}</ul>}
    <footer>{baseline.capture_status === "legacy_missing" ? "该申请创建于风险基线冻结启用前，办理人应回看来源授信的历史风险台账。" : hasSignals ? "上述风险不会因续授信发起而消失，重新评分和最终决策必须结合最新核查结果。" : "快照时点没有未结风险；后续新增风险仍应进入贷后预警和审批复核。"}</footer>
  </section>;
}

function Metric({ label, value, suffix, tone = "blue" }: { label: string; value: string; suffix: string; tone?: string }) { return <div className={`facility-metric ${tone}`}><span>{label}</span><strong>{value}<small>{suffix}</small></strong><i /></div>; }
function formatWan(value: number): string { return (value / 10000).toFixed(value >= 1000000 ? 0 : 1); }
function signedMoney(value: number): string { return `${value > 0 ? "+" : ""}${money.format(value)}`; }
function signedDays(value: number): string { return value === 0 ? "不变" : `${value > 0 ? "+" : ""}${value} 天`; }
function deltaTone(value: number): string { return value > 0 ? "increase" : value < 0 ? "decrease" : "unchanged"; }
function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value)) : "—"; }
function formatDateTime(value: string | null): string { return value ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "—"; }
function statusLabel(status: string): string { return ({ active: "生效中", expired: "已到期", frozen: "已冻结", closed: "已关闭" } as Record<string, string>)[status] ?? status; }
function stageName(stage: string): string { return ({ registration: "客户注册", document_upload: "上传资料", supplement: "补充资料", approval_submit: "发起审批", model_selection: "选择模型", scoring: "形成评分", credit_proposal: "额度与授信期", final_strategy: "最终策略" } as Record<string, string>)[stage] ?? stage; }
function alertStatus(status: string): string { return status === "resolved" ? "已闭环" : status === "acknowledged" ? "已确认" : "待处理"; }
function eventTypeLabel(type: string): string { return ({ payment_overdue: "回款逾期", litigation: "诉讼风险", business_abnormal: "经营异常", negative_public_opinion: "负面舆情", financial_deterioration: "财务恶化", ownership_change: "股权变更", other: "其他风险" } as Record<string, string>)[type] ?? type; }

type FacilityRiskSignal = { key: string; label: string; tone: "critical" | "warning" | "info" };

function daysUntil(value: string | null): number | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return null;
  return Math.ceil((timestamp - Date.now()) / 86400000);
}

function isDateWithinDays(value: string | null, windowDays: number): boolean {
  const days = daysUntil(value);
  return days !== null && days <= windowDays;
}

function isUpcomingWithinDays(value: string | null, windowDays: number): boolean {
  const days = daysUntil(value);
  return days !== null && days >= 0 && days <= windowDays;
}

function facilityHasCriticalAlert(facilityId: string, alerts: FacilityAlert[]): boolean {
  return alerts.some((item) => item.facility_id === facilityId && item.status !== "resolved" && item.severity === "critical");
}

function facilityRiskSignals(facility: CreditFacility, alerts: FacilityAlert[]): FacilityRiskSignal[] {
  if (facility.status === "closed") return [];
  const signals: FacilityRiskSignal[] = [];
  const unresolved = alerts.filter((item) => item.facility_id === facility.id && item.status !== "resolved");
  if (unresolved.some((item) => item.severity === "critical")) signals.push({ key: "critical_alert", label: "严重预警待处置", tone: "critical" });
  else if (unresolved.length) signals.push({ key: "open_alert", label: `${unresolved.length} 条预警未闭环`, tone: "warning" });
  if (facility.status === "expired") signals.push({ key: "expired", label: "授信已到期", tone: "critical" });
  if (facility.status === "frozen") signals.push({ key: "frozen", label: "授信已冻结", tone: "warning" });
  if (facility.overdue_control_count > 0) signals.push({ key: "overdue_controls", label: `${facility.overdue_control_count} 项控制条件逾期`, tone: facility.critical_control_count > 0 ? "critical" : "warning" });
  else if (facility.pending_control_count > 0) signals.push({ key: "pending_controls", label: `${facility.pending_control_count} 项控制条件待落实`, tone: "warning" });
  const reviewDays = daysUntil(facility.next_review_at);
  if (reviewDays !== null && reviewDays < 0) signals.push({ key: "review_overdue", label: `复评逾期 ${Math.abs(reviewDays)} 天`, tone: "critical" });
  else if (reviewDays !== null && reviewDays <= 30) signals.push({ key: "review_due", label: reviewDays === 0 ? "今日应复评" : `${reviewDays} 天内复评`, tone: "info" });
  const expiryDays = daysUntil(facility.expires_at);
  if (facility.status === "active" && expiryDays !== null && expiryDays <= 0) signals.push({ key: "expiry_overdue", label: "有效期已届满", tone: "critical" });
  else if (facility.status === "active" && expiryDays !== null && expiryDays <= 30) signals.push({ key: "expiring", label: `${expiryDays} 天内到期`, tone: "warning" });
  if (facility.status === "active" && facility.utilization_rate >= .9) signals.push({ key: "high_utilization", label: `额度使用 ${(facility.utilization_rate * 100).toFixed(0)}%`, tone: "warning" });
  return signals;
}

function facilityRiskPriority(facility: CreditFacility, alerts: FacilityAlert[]): number {
  const signals = facilityRiskSignals(facility, alerts);
  let priority = 0;
  if (signals.some((item) => item.key === "critical_alert")) priority += 1000;
  if (facility.status === "expired") priority += 900;
  if (facility.status === "frozen") priority += 850;
  if (signals.some((item) => item.key === "review_overdue")) priority += 800;
  if (signals.some((item) => item.key === "expiry_overdue")) priority += 750;
  if (signals.some((item) => item.key === "open_alert")) priority += 700;
  if (signals.some((item) => item.key === "overdue_controls")) priority += facility.critical_control_count > 0 ? 780 : 680;
  if (signals.some((item) => item.key === "pending_controls")) priority += 650;
  if (signals.some((item) => item.key === "expiring")) priority += 600;
  if (signals.some((item) => item.key === "high_utilization")) priority += 500;
  if (signals.some((item) => item.key === "review_due")) priority += 400;
  return priority;
}

function facilityNextTaskTime(facility: CreditFacility): number {
  const values = [facility.next_review_at, facility.expires_at]
    .map((value) => value ? Date.parse(value) : Number.NaN)
    .filter((value) => !Number.isNaN(value));
  return values.length ? Math.min(...values) : Number.MAX_SAFE_INTEGER;
}

function sortFacilitiesByRisk(facilities: CreditFacility[], alerts: FacilityAlert[]): CreditFacility[] {
  return [...facilities].sort((left, right) =>
    facilityRiskPriority(right, alerts) - facilityRiskPriority(left, alerts)
    || facilityNextTaskTime(left) - facilityNextTaskTime(right)
    || left.counterparty_name.localeCompare(right.counterparty_name, "zh-CN"));
}

function facilityOperationGuide(facility: CreditFacility, alerts: FacilityAlert[]): { tone: "critical" | "warning" | "healthy" | "neutral"; title: string; priority: string; risk: string; owner: string; action: string; completion: string } {
  const criticalAlerts = alerts.filter((item) => item.severity === "critical");
  const reviewDays = daysUntil(facility.next_review_at);
  const expiryDays = daysUntil(facility.expires_at);
  if (facility.status === "closed") return { tone: "neutral", title: "授信已关闭并停止使用", priority: "流程结束", risk: "额度账户已关闭，不再允许新增用信。", owner: "客户经理 / 贷后运营", action: "确认余额已经清零，保存关闭依据并完成客户沟通。", completion: "无未结余额、预警和后续用信安排。" };
  if (facility.status === "expired" || (expiryDays !== null && expiryDays <= 0)) return { tone: "critical", title: "授信到期，禁止继续用信", priority: "立即处理", risk: `授信已于 ${formatDate(facility.expires_at)} 到期。`, owner: "客户经理 + 风控经理", action: "停止新增额度占用，核对存量余额；需要继续合作时重新发起授信评估。", completion: "存量余额妥善处置，或新审批完成并形成新的授信台账。" };
  if (facility.overdue_control_count > 0) return { tone: facility.critical_control_count > 0 ? "critical" : "warning", title: "审批控制条件已逾期并进入升级督办", priority: facility.critical_control_count > 0 ? "立即处理" : "今日处理", risk: `${facility.overdue_control_count} 项控制条件逾期，其中 ${facility.critical_control_count} 项已升级至审批人或管理员。`, owner: facility.critical_control_count > 0 ? "风控经理执行 + 授信审批人/管理员督办" : "风控经理执行并督办", action: "打开控制条件台账核实执行证据并逐项完成；条件无法落实时登记风险事件并评估冻结或压降额度。", completion: "逾期条件全部完成，对应预警自动闭环，执行结论进入审计轨迹。" };
  if (criticalAlerts.length) return { tone: "critical", title: "严重预警尚未闭环", priority: "立即处理", risk: criticalAlerts.map((item) => item.title).join("；"), owner: "风控经理 + 运营值班", action: "先确认接收并核实风险事实，再选择持续监控、冻结、压降额度或关闭授信。", completion: "预警形成有依据的处置结论，必要的授信控制同步生效。" };
  if (facility.status === "frozen") return { tone: "warning", title: "授信冻结，等待风险结论", priority: "优先处理", risk: "当前额度账户禁止新增占用。", owner: "风控经理 / 授信审批人", action: "核查冻结原因、未闭环预警和存量余额，形成继续冻结、解冻、压降或关闭意见。", completion: "控制动作和业务依据进入审计链，客户经理收到明确执行结论。" };
  if (alerts.length) return { tone: "warning", title: "一般预警待核查处置", priority: "今日处理", risk: alerts.map((item) => item.title).join("；"), owner: "运营值班 + 风控经理", action: "确认预警来源和影响，登记核查结论；风险升级时提交授信控制。", completion: "全部预警已确认并闭环，或已升级为明确的控制任务。" };
  if (facility.pending_control_count > 0) return { tone: "warning", title: "审批控制条件尚未全部落实", priority: "按期完成", risk: `${facility.pending_control_count} 项由最终策略承接的控制条件仍待闭环。`, owner: "风控经理", action: "逐项核验执行证据，填写落实结论并完成控制条件；发现无法落实时立即登记风险事件。", completion: "所有控制条件均具备执行证据、责任人和完成时间。" };
  if (reviewDays !== null && reviewDays < 0) return { tone: "warning", title: "贷后复评已经逾期", priority: "今日处理", risk: `计划复评日为 ${formatDate(facility.next_review_at)}。`, owner: "风控经理", action: "更新企业评级、风险变化与下次复评间隔，提交复评结论。", completion: "复评结果写入台账，并形成新的下次复评日期。" };
  if (expiryDays !== null && expiryDays <= 30) return { tone: "warning", title: "授信即将到期", priority: `${Math.max(expiryDays, 0)} 天内`, risk: `有效期至 ${formatDate(facility.expires_at)}。`, owner: "客户经理 + 风控经理", action: "确认合作续作需求，提前收集更新资料并发起续评；无需续作则安排余额退出。", completion: "续作申请已进入审批，或退出计划、余额安排已确认。" };
  if (reviewDays !== null && reviewDays <= 30) return { tone: "warning", title: reviewDays === 0 ? "贷后复评今日到期" : "贷后复评即将到期", priority: reviewDays === 0 ? "今日处理" : `${reviewDays} 天内`, risk: `下次复评日为 ${formatDate(facility.next_review_at)}。`, owner: "风控经理", action: "准备经营、财务、交易和外部风险变化资料，按期完成评级复核。", completion: "复评结论与下一复评日期写入授信台账。" };
  if (facility.utilization_rate >= .9) return { tone: "warning", title: "额度使用率较高", priority: "持续关注", risk: `已用额度达到批准额度的 ${(facility.utilization_rate * 100).toFixed(1)}%。`, owner: "客户经理 + 贷后运营", action: "核对真实订单、回款计划和额度集中度，持续跟踪可用额度与逾期风险。", completion: "高使用率具备真实交易依据，回款计划清晰且无新增异常。" };
  return { tone: "healthy", title: "当前授信运行正常", priority: "按计划监控", risk: "暂无未闭环预警、临期或高使用率信号。", owner: "客户经理", action: "持续跟踪交易、回款和外部风险，按台账计划准备下一次复评。", completion: `在 ${formatDate(facility.next_review_at)} 前完成例行复评，异常信号及时登记。` };
}

function conditionRoleLabel(role: "risk_manager" | "approver" | "admin"): string {
  return { risk_manager: "风控经理", approver: "授信审批人", admin: "平台管理员" }[role];
}

function extensionStatusLabel(status: "pending" | "approved" | "rejected" | "cancelled"): string {
  return { pending: "待审批", approved: "已批准", rejected: "已驳回", cancelled: "已取消" }[status];
}

function conditionSlaLabel(status: "on_track" | "due_soon" | "overdue" | "completed", daysRemaining: number | null, overdueDays: number): string {
  if (status === "overdue") return `已逾期 ${overdueDays} 天，预警将持续至条件完成`;
  if (status === "due_soon") return daysRemaining === 0 ? "今日到期" : `${daysRemaining} 天内到期`;
  if (status === "completed") return "已完成";
  return `剩余 ${daysRemaining ?? "—"} 天`;
}
