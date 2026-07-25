import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { CreditFacility, CreditFacilityDetail, FacilityAlert, FacilitySummary, RiskEvent } from "./types";


type Notice = { kind: "error" | "success"; text: string };
const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 });


export default function PostCreditCenter({ canView, canTransact, canReview, canScan, canActAlerts, canCreateRiskEvents, canControl, onNotice }: { canView: boolean; canTransact: boolean; canReview: boolean; canScan: boolean; canActAlerts: boolean; canCreateRiskEvents: boolean; canControl: boolean; onNotice: (notice: Notice) => void }) {
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

  const reload = useCallback(async (focusId?: string) => {
    if (!canView) return;
    setLoading(true);
    try {
      const [summaryRow, facilityRows, alertRows, eventRows] = await Promise.all([api.facilitySummary(), api.creditFacilities(), api.facilityAlerts(), api.riskEvents()]);
      setSummary(summaryRow);
      setFacilities(facilityRows);
      setAlerts(alertRows);
      setRiskEvents(eventRows);
      const target = focusId || selectedId || facilityRows[0]?.id || "";
      setSelectedId(target);
      setSelected(target ? await api.creditFacility(target) : null);
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "贷后工作台加载失败" }); }
    finally { setLoading(false); }
  }, [canView, onNotice, selectedId]);

  useEffect(() => { void reload(); }, [canView]);
  useEffect(() => {
    if (!selectedId || !canView) return;
    void api.creditFacility(selectedId).then((row) => { setSelected(row); setReviewRating(row.rating); }).catch((error: Error) => onNotice({ kind: "error", text: error.message }));
  }, [selectedId, canView, onNotice]);

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
    try { const result = await api.scanFacilities(); await reload(selectedId); onNotice({ kind: "success", text: `扫描 ${result.active_facilities_scanned} 笔授信，新增 ${result.alerts_opened} 条预警` }); }
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

  if (!canView) return <div className="panel post-credit-empty"><strong>当前身份无贷后管理权限</strong><p>请切换为客户经理、风控、审批、运营或审计角色。</p></div>;
  if (loading && !summary) return <div className="panel post-credit-empty">正在加载授信台账…</div>;
  const dispositionAlert = alerts.find((item) => item.id === dispositionAlertId);

  return <div className="post-credit-center">
    <section className="post-credit-hero"><div><span>POST-CREDIT CONTROL</span><h2>授信台账与贷后风险控制</h2><p>最终审批自动形成可执行额度账户，所有占用、归还、复评和预警均可追溯。</p></div>{canScan && <button className="primary-button" disabled={busy === "scan"} onClick={() => void scan()}>{busy === "scan" ? "正在扫描…" : "运行贷后扫描"}</button>}</section>
    {summary && <section className="facility-metric-grid"><Metric label="生效授信" value={String(summary.active_facilities)} suffix="笔" /><Metric label="批准额度" value={formatWan(summary.approved_limit)} suffix="万元" /><Metric label="已用额度" value={formatWan(summary.used_limit)} suffix="万元" tone="amber" /><Metric label="可用额度" value={formatWan(summary.available_limit)} suffix="万元" tone="teal" /><Metric label="未闭环预警" value={String(summary.unresolved_alerts)} suffix="条" tone={summary.critical_alerts ? "red" : "blue"} /></section>}

    <section className="facility-work-grid">
      <div className="panel facility-list-panel"><div className="post-section-head"><div><span>FACILITY LEDGER</span><h2>授信台账</h2></div><small>{facilities.length} 笔</small></div>{facilities.length ? <div className="facility-list">{facilities.map((item) => <button className={`facility-row ${selectedId === item.id ? "selected" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}><div><strong>{item.counterparty_name}</strong><span className={`facility-status ${item.status}`}>{statusLabel(item.status)}</span></div><p>{item.rating} · {item.access_strategy} · 账期 {item.payment_term_days} 天</p><div className="utilization-line"><i style={{ width: `${Math.min(item.utilization_rate * 100, 100)}%` }} /><span>{(item.utilization_rate * 100).toFixed(1)}%</span></div><footer><span>可用 {money.format(item.available_limit)}</span><small>{formatDate(item.expires_at)} 到期</small></footer></button>)}</div> : <div className="post-credit-empty compact"><strong>暂无已生效授信</strong><p>通过最终审批后会自动生成授信台账。</p></div>}</div>

      <div className="panel facility-detail-panel">{selected ? <><div className="post-section-head"><div><span>FACILITY DETAIL</span><h2>{selected.counterparty_name}</h2></div><span className={`facility-status ${selected.status}`}>{statusLabel(selected.status)}</span></div><div className="facility-balance"><div><span>批准额度</span><strong>{money.format(selected.approved_limit)}</strong></div><div><span>已用额度</span><strong>{money.format(selected.used_limit)}</strong></div><div><span>可用额度</span><strong>{money.format(selected.available_limit)}</strong></div></div><div className="facility-meta"><span>评级 <b>{selected.rating}</b></span><span>监控频率 <b>{selected.monitoring_frequency}</b></span><span>下次复评 <b>{formatDate(selected.next_review_at)}</b></span><span>授信到期 <b>{formatDate(selected.expires_at)}</b></span></div>
        {(canTransact || canReview || canCreateRiskEvents || canControl) && <div className="facility-actions">
          {canTransact && <div><h3>额度交易</h3><div className="action-form-grid"><select value={transactionType} onChange={(event) => setTransactionType(event.target.value as "drawdown" | "repayment")}><option value="drawdown">额度占用</option><option value="repayment">额度归还</option></select><input type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(Number(event.target.value))} placeholder="金额" /><input value={transactionRef} onChange={(event) => setTransactionRef(event.target.value)} placeholder="业务交易号（留空自动生成）" /><input value={transactionReason} onChange={(event) => setTransactionReason(event.target.value)} placeholder="交易原因" /></div><button disabled={busy === "transaction" || selected.status !== "active" || amount <= 0 || transactionReason.trim().length < 2} onClick={() => void transact()}>{busy === "transaction" ? "处理中…" : "提交额度交易"}</button></div>}
          {canReview && <div><h3>贷后复评</h3><div className="action-form-grid"><select value={reviewRating} onChange={(event) => setReviewRating(event.target.value)}>{["AAA", "AA", "A", "BBB", "BB", "B", "D"].map((item) => <option key={item}>{item}</option>)}</select><input type="number" min="1" max="365" value={reviewDays} onChange={(event) => setReviewDays(Number(event.target.value))} /><input className="wide" value={reviewConclusion} onChange={(event) => setReviewConclusion(event.target.value)} placeholder="复评结论与风险变化" /></div><button disabled={busy === "review" || selected.status !== "active" || reviewConclusion.trim().length < 2} onClick={() => void review()}>{busy === "review" ? "提交中…" : "完成贷后复评"}</button></div>}
          {canCreateRiskEvents && <div><h3>登记风险事件</h3><div className="action-form-grid"><select value={eventType} onChange={(event) => setEventType(event.target.value)}><option value="payment_overdue">回款逾期</option><option value="litigation">诉讼风险</option><option value="business_abnormal">经营异常</option><option value="negative_public_opinion">负面舆情</option><option value="financial_deterioration">财务恶化</option><option value="ownership_change">股权变更</option><option value="other">其他风险</option></select><select value={eventSeverity} onChange={(event) => setEventSeverity(event.target.value as "warning" | "critical")}><option value="warning">一般预警</option><option value="critical">严重预警</option></select><input value={eventSource} onChange={(event) => setEventSource(event.target.value)} placeholder="事件来源" /><input value={eventTitle} onChange={(event) => setEventTitle(event.target.value)} placeholder="事件标题" /><input className="wide" value={eventDescription} onChange={(event) => setEventDescription(event.target.value)} placeholder="风险事实与影响" /></div><button disabled={busy === "risk-event" || eventSource.trim().length < 2 || eventTitle.trim().length < 2 || eventDescription.trim().length < 2} onClick={() => void createRiskEvent()}>{busy === "risk-event" ? "登记中…" : "登记并生成预警"}</button></div>}
          {canControl && <div><h3>授信控制</h3><div className="action-form-grid"><select value={controlAction} onChange={(event) => setControlAction(event.target.value as "freeze" | "unfreeze" | "reduce_limit" | "close")}><option value="freeze">冻结授信</option><option value="unfreeze">解除冻结</option><option value="reduce_limit">压降额度</option><option value="close">关闭授信</option></select>{controlAction === "reduce_limit" && <input type="number" min="0" step="0.01" value={controlTarget} onChange={(event) => setControlTarget(Number(event.target.value))} placeholder="目标额度" />}<input className="wide" value={controlReason} onChange={(event) => setControlReason(event.target.value)} placeholder="控制原因与审批依据" /></div><button disabled={busy === "control" || controlReason.trim().length < 2 || (controlAction === "reduce_limit" && controlTarget <= 0)} onClick={() => void controlFacility()}>{busy === "control" ? "执行中…" : "执行授信控制"}</button></div>}
        </div>}
        <div className="transaction-history"><h3>额度流水</h3>{selected.transactions.length ? selected.transactions.map((item) => <div key={item.id}><span className={item.transaction_type}>{item.transaction_type === "drawdown" ? "占用" : "归还"}</span><div><strong>{money.format(item.amount)}</strong><small>{item.transaction_ref} · {item.actor} · {formatDateTime(item.occurred_at)}</small></div><b>余额 {money.format(item.balance_after)}</b></div>) : <p>暂无额度交易</p>}</div></> : <div className="post-credit-empty">请选择一笔授信台账</div>}</div>
    </section>

    <section className="panel risk-event-panel"><div className="post-section-head"><div><span>RISK EVENT HUB</span><h2>风险事件台账</h2></div><small>{riskEvents.filter((item) => item.status === "active").length} 条活跃事件</small></div>{riskEvents.length ? <div className="risk-event-list">{riskEvents.map((item) => <article className={`${item.severity} ${item.status}`} key={item.id}><span>{eventTypeLabel(item.event_type)}</span><div><strong>{item.title}</strong><p>{item.counterparty_name} · {item.description}</p><small>{item.source} · {formatDateTime(item.occurred_at)} · {item.external_event_id}</small></div><i>{item.status === "resolved" ? "已解决" : item.severity === "critical" ? "严重" : "关注"}</i></article>)}</div> : <div className="post-credit-empty compact"><strong>暂无风险事件</strong><p>业务监控或外部数据源发现风险后，可在授信详情中登记。</p></div>}</section>

    <section className="panel facility-alert-panel"><div className="post-section-head"><div><span>EARLY WARNING</span><h2>贷后风险预警</h2></div><small>{alerts.filter((item) => item.status !== "resolved").length} 条未闭环</small></div>{alerts.length ? <div className="facility-alert-list">{alerts.map((item) => <div className={`facility-alert ${item.severity} ${item.status}`} key={item.id}><span>{item.severity === "critical" ? "!!" : "!"}</span><div><strong>{item.title}</strong><p>{item.counterparty_name} · {item.message}</p><small>{formatDateTime(item.created_at)}{item.disposition_note ? ` · ${item.disposition_note}` : ""}</small></div><div className="alert-command">{canActAlerts && item.status === "open" && <button disabled={busy === item.id} onClick={() => void acknowledge(item)}>确认接收</button>}{canActAlerts && item.status !== "resolved" && <button className="secondary" onClick={() => { setDispositionAlertId(item.id); setDispositionAction("monitor"); }}>处置预警</button>}{item.status === "resolved" && <i>{alertStatus(item.status)}</i>}</div></div>)}</div> : <div className="post-credit-empty compact"><strong>暂无贷后预警</strong></div>}
      {dispositionAlert && <div className="alert-disposition-form"><header><div><span>DISPOSITION</span><strong>处置：{dispositionAlert.title}</strong></div><button onClick={() => setDispositionAlertId("")}>取消</button></header><div className="action-form-grid"><select value={dispositionAction} onChange={(event) => setDispositionAction(event.target.value as "monitor" | "freeze" | "reduce_limit" | "close")}><option value="monitor">持续监控并闭环</option>{canControl && <option value="freeze">冻结授信</option>}{canControl && <option value="reduce_limit">压降额度</option>}{canControl && <option value="close">关闭授信</option>}</select>{dispositionAction === "reduce_limit" && <input type="number" min="0" step="0.01" value={dispositionTarget} onChange={(event) => setDispositionTarget(Number(event.target.value))} placeholder="目标额度" />}<input className="wide" value={dispositionConclusion} onChange={(event) => setDispositionConclusion(event.target.value)} placeholder="核查结论、控制依据与后续安排" /></div><button disabled={busy === "disposition" || dispositionConclusion.trim().length < 2 || (dispositionAction === "reduce_limit" && dispositionTarget <= 0)} onClick={() => void disposeAlert()}>{busy === "disposition" ? "处置中…" : "提交处置结论"}</button></div>}
    </section>
  </div>;
}

function Metric({ label, value, suffix, tone = "blue" }: { label: string; value: string; suffix: string; tone?: string }) { return <div className={`facility-metric ${tone}`}><span>{label}</span><strong>{value}<small>{suffix}</small></strong><i /></div>; }
function formatWan(value: number): string { return (value / 10000).toFixed(value >= 1000000 ? 0 : 1); }
function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value)) : "—"; }
function formatDateTime(value: string | null): string { return value ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "—"; }
function statusLabel(status: string): string { return ({ active: "生效中", expired: "已到期", frozen: "已冻结", closed: "已关闭" } as Record<string, string>)[status] ?? status; }
function alertStatus(status: string): string { return status === "resolved" ? "已闭环" : status === "acknowledged" ? "已确认" : "待处理"; }
function eventTypeLabel(type: string): string { return ({ payment_overdue: "回款逾期", litigation: "诉讼风险", business_abnormal: "经营异常", negative_public_opinion: "负面舆情", financial_deterioration: "财务恶化", ownership_change: "股权变更", other: "其他风险" } as Record<string, string>)[type] ?? type; }
