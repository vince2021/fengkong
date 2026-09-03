import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import ModelGovernancePanel from "./ModelGovernancePanel";
import type { Counterparty, EditableIndicator, EnterpriseIndicatorObservation, EnterpriseRiskIndicator, ModelDetail, ModelImpact, ModelSummary, RatingTrace } from "./types";

const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 });

type Notice = { kind: "error" | "success"; text: string };

export default function ModelLab({ focus, counterparties, canView, canSimulate, canManage, canReview, canManageIndicatorData, canReviewIndicatorData, onNotice }: { focus?: { modelKey: string; requestId: number } | null; counterparties: Counterparty[]; canView: boolean; canSimulate: boolean; canManage: boolean; canReview: boolean; canManageIndicatorData: boolean; canReviewIndicatorData: boolean; onNotice: (notice: Notice | null) => void }) {
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [modelKey, setModelKey] = useState("general");
  const [counterpartyId, setCounterpartyId] = useState(counterparties[0]?.id ?? "");
  const [model, setModel] = useState<ModelDetail | null>(null);
  const [trace, setTrace] = useState<RatingTrace | null>(null);
  const [impact, setImpact] = useState<ModelImpact | null>(null);
  const [indicatorPath, setIndicatorPath] = useState("");
  const [newValue, setNewValue] = useState(0);
  const [loading, setLoading] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [observations, setObservations] = useState<EnterpriseIndicatorObservation[]>([]);
  const [observationIndicatorId, setObservationIndicatorId] = useState("");
  const [observationValues, setObservationValues] = useState<Record<string, number | boolean>>({});
  const [evidenceReference, setEvidenceReference] = useState("");
  const [observedAt, setObservedAt] = useState(new Date().toISOString().slice(0, 10));
  const [observationBusy, setObservationBusy] = useState(false);
  const analysisRequestId = useRef(0);

  useEffect(() => {
    if (!counterparties.some((item) => item.id === counterpartyId)) setCounterpartyId(counterparties[0]?.id ?? "");
  }, [counterparties, counterpartyId]);

  useEffect(() => {
    if (!canView) return;
    void api.models().then((rows) => {
      setModels(rows);
      setModelKey((current) => rows.some((item) => item.key === current) ? current : rows[0]?.key ?? "");
    }).catch((error: Error) => onNotice({ kind: "error", text: error.message }));
  }, [canView, onNotice]);

  useEffect(() => {
    if (focus?.modelKey) setModelKey(focus.modelKey);
  }, [focus]);

  const loadAnalysis = useCallback(async () => {
    if (!canView || !modelKey || !counterpartyId) return;
    const requestId = ++analysisRequestId.current;
    setLoading(true);
    setImpact(null);
    setModel(null);
    setTrace(null);
    setAnalysisError("");
    try {
      const [detail, calculation, observationRows] = await Promise.all([api.model(modelKey), api.ratingTrace(counterpartyId, modelKey), api.indicatorObservations(counterpartyId)]);
      if (requestId !== analysisRequestId.current) return;
      setModel(detail);
      setTrace(calculation);
      setObservations(observationRows);
      onNotice(null);
      const first = detail.editable_indicators[0];
      setIndicatorPath((current) => detail.editable_indicators.some((item) => item.path === current) ? current : first?.path ?? "");
      setObservationIndicatorId((current) => detail.indicator_selection.some((item) => item.id === current && item.enabled !== false) ? current : detail.indicator_selection.find((item) => item.enabled !== false)?.id ?? "");
    } catch (error) {
      if (requestId !== analysisRequestId.current) return;
      const message = error instanceof Error ? error.message : "模型分析加载失败";
      setAnalysisError(message);
      onNotice({ kind: "error", text: message });
    } finally {
      if (requestId === analysisRequestId.current) setLoading(false);
    }
  }, [canView, counterpartyId, modelKey, onNotice]);

  useEffect(() => { void loadAnalysis(); }, [loadAnalysis]);
  useEffect(() => {
    if (!focus || focus.modelKey !== modelKey || !model) return;
    window.setTimeout(() => document.getElementById("model-governance")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
  }, [focus, model, modelKey]);

  const selectedCounterparty = counterparties.find((item) => item.id === counterpartyId);
  const selectedIndicator = model?.editable_indicators.find((item) => item.path === indicatorPath);
  const observationIndicator = model?.indicator_selection.find((item) => item.id === observationIndicatorId);
  const observationPaths = observationIndicator?.scoring.input_fields ?? (observationIndicator ? [observationIndicator.field_path] : []);
  const currentValue = useMemo(() => selectedCounterparty && indicatorPath ? readPath(selectedCounterparty, indicatorPath) : 0, [selectedCounterparty, indicatorPath]);

  useEffect(() => setNewValue(currentValue), [currentValue]);
  useEffect(() => {
    if (!observationIndicator) return setObservationValues({});
    const detail = trace?.enterprise_risk_screening.details.find((item) => item.indicator_id === observationIndicator.id);
    setObservationValues(Object.fromEntries(observationPaths.map((path) => [path, observationIndicator.scoring.type === "boolean_hit" ? Boolean(detail?.actual_value ?? false) : observationPaths.length === 1 && typeof detail?.actual_value === "number" ? detail.actual_value : 0])));
  }, [observationIndicatorId, model, trace]);

  async function simulate() {
    if (!selectedIndicator) return;
    setSimulating(true);
    try {
      const result = await api.modelImpact(counterpartyId, modelKey, selectedIndicator.path, newValue);
      setImpact(result);
      onNotice({ kind: "success", text: `${selectedIndicator.label}影响模拟已完成` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "影响模拟失败" });
    } finally {
      setSimulating(false);
    }
  }

  async function submitObservation() {
    if (!observationIndicator || evidenceReference.trim().length < 5) return onNotice({ kind: "error", text: "请填写不少于 5 个字的证据说明" });
    setObservationBusy(true);
    try {
      await api.createIndicatorObservation({ counterparty_id: counterpartyId, indicator_id: observationIndicator.id, values: observationValues, evidence_reference: evidenceReference, as_of_date: observedAt });
      await loadAnalysis();
      setEvidenceReference("");
      onNotice({ kind: "success", text: `${observationIndicator.name}数据已提交独立复核` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "指标数据提交失败" }); }
    finally { setObservationBusy(false); }
  }

  async function reviewObservation(item: EnterpriseIndicatorObservation, decision: "verify" | "reject") {
    setObservationBusy(true);
    try {
      await api.reviewIndicatorObservation(item.id, { expected_row_version: item.row_version, decision, comment: decision === "verify" ? "已核对指标口径、截止日期和证据来源" : "指标口径或证据不足，退回重新补充" });
      await loadAnalysis();
      onNotice({ kind: "success", text: decision === "verify" ? `${item.indicator_name}已复核生效并重算` : `${item.indicator_name}已驳回` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "指标数据复核失败" }); }
    finally { setObservationBusy(false); }
  }

  if (!canView) return <div className="panel model-empty"><strong>当前身份无模型查看权限</strong><p>请切换为风控、模型管理、审批或审计角色。</p></div>;
  if (!counterparties.length) return <div className="panel model-empty"><strong>暂无可分析客商</strong><p>当前身份的数据范围内没有可用样本。</p></div>;

  return <div className="model-lab">
    <section className="panel model-toolbar">
      <div><span>MODEL GOVERNANCE</span><h2>模型运算链与指标影响实验室</h2><p>从原始指标、维度扣分、权重汇总到规则覆盖，完整解释最终授信策略。</p></div>
      <div className="model-selectors"><label><span>模型模板</span><select value={modelKey} onChange={(event) => setModelKey(event.target.value)}>{models.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label><label><span>模拟客商</span><select value={counterpartyId} onChange={(event) => setCounterpartyId(event.target.value)}>{counterparties.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>
    </section>

    {analysisError ? <div className="panel model-empty"><strong>当前组合无法生成计算链</strong><p>{analysisError}</p><button className="mini-button" onClick={() => void loadAnalysis()}>重新加载</button></div> : loading || !model || !trace ? <div className="panel model-loading">正在生成计算链…</div> : <>
      <nav className="panel model-section-nav" aria-label="模型实验室功能分区"><span>功能导航</span><a href="#model-overview"><b>01</b>结果概览</a><a href="#model-explanation"><b>02</b>评分与模拟</a><a href="#model-risk-data"><b>03</b>风险指标</a><a href="#model-policy"><b>04</b>决策规则</a><a href="#model-governance"><b>05</b>治理发布</a></nav>

      <section id="model-overview" className="model-zone overview-zone">
        <ModelZoneHeader index="01" eyebrow="RESULT OVERVIEW" title="当前模型结果概览" description="先看模型版本、综合评分、建议额度与规则命中，再向下追溯计算依据。" tags={["结果", "版本", "授信建议"]} />
        <div className="model-summary-grid">
        <div className="model-title-card"><div><span className="live-dot" /> 已生效</div><h3>{model.name}</h3><p>{model.version}</p><small>{model.change_reason}</small></div>
        <SummaryCard label="当前综合评分" value={trace.result.total_score.toFixed(1)} suffix="分" detail={`${trace.result.rating} 级 · ${trace.result.risk_segment}${trace.result.data_completeness === undefined ? "" : ` · 完整度 ${(trace.result.data_completeness * 100).toFixed(1)}%`}`} tone="teal" />
        <SummaryCard label="建议授信额度" value={(trace.result.suggested_limit / 10_000).toFixed(0)} suffix="万元" detail={`建议账期 ${trace.result.suggested_payment_term_days} 天`} tone="blue" />
        <SummaryCard label="强规则命中" value={String(trace.result.strong_rule_hits.length)} suffix="条" detail={trace.result.access_strategy} tone={trace.result.strong_rule_hits.length ? "red" : "green"} />
        </div>
        {trace.result.scorecard_execution && <ScorecardExecutionEvidence result={trace.result} />}
      </section>

      <section id="model-explanation" className="model-zone explanation-zone">
        <ModelZoneHeader index="02" eyebrow="SCORE EXPLAINABILITY" title="评分运算与敏感性分析" description="解释指标如何进入维度、矩阵、规则与最终策略，并模拟局部指标变化带来的全链路影响。" tags={["运算链", "指标明细", "What-if"]} />

      <section className="panel calculation-panel">
        <div className="section-title"><div><span>CALCULATION GRAPH</span><h2>评分运算链</h2></div><code>{trace.formula}</code></div>
        <div className="calculation-flow"><FlowNode index="01" label="原始指标" detail={`${trace.indicator_deductions.length} 项指标`} /><FlowArrow /><FlowNode index="02" label={trace.matrix_inputs ? "分层子模型" : "维度得分"} detail={trace.matrix_inputs ? "组内分箱 × 层级权重" : "100 - Σ 指标扣分"} /><FlowArrow /><FlowNode index="03" label={trace.matrix_inputs ? "业务财务矩阵" : "权重汇总"} detail={trace.matrix_inputs ? `B${trace.result.business_risk_band} × F${trace.result.financial_risk_band}` : "Σ 维度分 × 权重"} /><FlowArrow /><FlowNode index="04" label="强规则调整" detail={`${trace.result.strong_rule_hits.length} 条命中`} alert={trace.result.strong_rule_hits.length > 0} /><FlowArrow /><FlowNode index="05" label="风险贷策收紧" detail={`${trace.result.risk_screening_policy?.hits.length ?? 0} 条命中`} alert={Boolean(trace.result.risk_screening_policy?.hits.length)} /><FlowArrow /><FlowNode index="06" label="最终策略" detail={`${trace.result.rating} / ${trace.result.access_strategy}`} final /></div>
        {trace.matrix_inputs && <div className="matrix-review"><div>{trace.matrix_inputs.map((item) => <span key={item.子模型}><small>{item.子模型}</small><strong>{item.得分.toFixed(1)}</strong><i>{item.档位}</i></span>)}</div>{trace.data_quality && <aside><small>数据完整度</small><strong>{trace.data_quality.整体完整度}</strong><p>财务 {trace.data_quality.财务风险} · 交易 {trace.data_quality.交易行为}</p></aside>}</div>}
        {trace.limit_calculation && <div className="limit-chain"><div><small>LIMIT CONSTRAINTS</small><strong>建议额度约束链</strong><p>{trace.limit_calculation.公式}</p></div>{Object.entries(trace.limit_calculation.候选上限).map(([label, value]) => <span key={label}><small>{label}</small><b>{money.format(value)}</b></span>)}<aside><small>最终约束</small><strong>{trace.limit_calculation.约束项}</strong><b>{money.format(trace.limit_calculation.规则调整后额度)}</b></aside></div>}
        <div className="dimension-grid">{trace.dimension_contributions.map((item) => <div className="dimension-card" key={item.维度}><div><strong>{item.维度}</strong><span>权重 {item.权重}</span></div><div className="score-line"><b>{item.维度得分.toFixed(1)}</b><div><i style={{ width: `${item.维度得分}%` }} /></div></div><code>{item.计算公式}</code><p>贡献最终得分 <strong>{item.加权贡献}</strong></p></div>)}</div>
      </section>

      <section className="model-main-grid">
        <div className="panel deductions-panel"><div className="section-title"><div><span>INDICATOR CALCULATION</span><h2>指标运算明细</h2></div><span className="soft-chip">共 {trace.indicator_deductions.length} 项</span></div><div className="deduction-list">{trace.indicator_deductions.map((item, index) => <div key={`${item.指标}-${index}`}><div className={`deduction-rank ${item.数据状态 === "待补充" ? "missing" : ""}`}>{item.数据状态 === "待补充" ? "待补" : item.标准分 !== undefined ? `${item.标准分 > 0 ? "+" : ""}${item.标准分}` : `-${item.扣分}`}</div><div><strong>{item.指标}</strong><span>{item.维度}{item.指标组 ? ` / ${item.指标组}` : ""} · {item.证据}</span><code>{item.运算}</code></div></div>)}</div></div>

        <div className="panel simulator-panel"><div className="section-title"><div><span>WHAT-IF ANALYSIS</span><h2>单指标影响模拟</h2></div></div><p className="simulator-help">调整主模型或企业风险池的任一局部指标，平台将同时重算主评级、额度策略与独立风险筛查分。</p><label><span>模拟指标</span><select value={indicatorPath} onChange={(event) => setIndicatorPath(event.target.value)}>{model.editable_indicators.map((item) => <option key={item.path} value={item.path}>{item.label}</option>)}</select></label><div className="value-comparison"><label><span>当前值</span><div>{formatIndicator(currentValue, selectedIndicator)}</div></label><span>→</span><label><span>模拟值</span><input type="number" step={selectedIndicator?.step ?? 1} min={selectedIndicator?.min} max={selectedIndicator?.max} value={newValue} onChange={(event) => setNewValue(Number(event.target.value))} /><small>{selectedIndicator?.unit}</small></label></div><p className="value-range">允许范围：{selectedIndicator ? `${formatIndicator(selectedIndicator.min, selectedIndicator)} 至 ${formatIndicator(selectedIndicator.max, selectedIndicator)}` : "—"}</p><button className="primary-button full" disabled={!canSimulate || simulating} onClick={() => void simulate()}>{!canSimulate ? "当前身份无模拟权限" : simulating ? "正在重算全链路…" : "运行影响模拟"}</button>{impact ? <ImpactResult impact={impact} /> : <div className="impact-placeholder"><span>↗</span><p>运行后将在此对比基线与模拟结果</p></div>}</div>
      </section>
      </section>

      <section id="model-risk-data" className="model-zone risk-data-zone">
        <ModelZoneHeader index="03" eyebrow="RISK DATA & EVIDENCE" title="企业风险指标与证据数据" description="查看模型选用了哪些企业风险指标、当前得分与数据完整度，并对缺失指标补充可复核证据。" tags={["指标池", "数据完整度", "证据复核"]} />

      <section className="panel enterprise-risk-screening-panel"><div className="section-title"><div><span>ENTERPRISE RISK SUBMODEL</span><h2>企业风险指标组合计算</h2></div><span className="soft-chip">{trace.enterprise_risk_screening.selected_count} 项已选</span></div><div className="risk-screening-summary"><div><span>风险筛查标准分</span><strong>{trace.enterprise_risk_screening.normalized_score.toFixed(1)}</strong><small>原始加权分 {trace.enterprise_risk_screening.weighted_score.toFixed(2)} / 3</small></div><div><span>数据完整度</span><strong>{(trace.enterprise_risk_screening.completeness * 100).toFixed(1)}%</strong><small>{trace.enterprise_risk_screening.available_count} 已取得 · {trace.enterprise_risk_screening.missing_count} 待补充</small></div><p>{trace.enterprise_risk_screening.formula}</p></div>{trace.result.risk_screening_policy && <RiskPolicyResult policy={trace.result.risk_screening_policy} />}<div className="risk-screening-list">{trace.enterprise_risk_screening.details.map((item) => <article className={item.data_status === "待补充" ? "missing" : item.score <= 1 ? "critical" : item.score < 3 ? "warning" : "pass"} key={item.indicator_id}><div><span>{item.category}</span><strong>{item.name}</strong><small>{item.actual_display} · {item.data_status}</small></div><b>{item.score.toFixed(0)}<small>/3</small></b><code>{item.formula}</code></article>)}</div></section>

      <IndicatorObservationWorkbench indicators={model.indicator_selection.filter((item) => item.enabled !== false)} selected={observationIndicator} selectedId={observationIndicatorId} onSelect={setObservationIndicatorId} values={observationValues} onValue={(path, value) => setObservationValues((current) => ({ ...current, [path]: value }))} evidenceReference={evidenceReference} onEvidenceReference={setEvidenceReference} observedAt={observedAt} onObservedAt={setObservedAt} observations={observations} canManage={canManageIndicatorData} canReview={canReviewIndicatorData} busy={observationBusy} onSubmit={() => void submitObservation()} onReview={(item, decision) => void reviewObservation(item, decision)} />
      </section>

      <section id="model-policy" className="model-zone policy-zone">
        <ModelZoneHeader index="04" eyebrow="DECISION POLICY" title="决策规则与策略覆盖" description="集中查看硬性禁入、人工复核和策略收紧规则，明确主评分之后还会发生哪些决策覆盖。" tags={["强规则", "准入", "策略覆盖"]} />

      <section className="panel rule-panel"><div className="section-title"><div><span>DECISION RULES</span><h2>强规则与策略覆盖</h2></div><span className="soft-chip">{model.strong_rules.filter((item) => item.enabled).length} 条启用</span></div><div className="rule-grid">{model.strong_rules.map((rule) => <div className="rule-card" key={rule.id}><div><span>{rule.id}</span><i className={rule.enabled ? "enabled" : ""}>{rule.enabled ? "启用" : "停用"}</i></div><h3>{rule.name}</h3><p>{rule.conditions.map((condition) => condition.label).join(rule.condition_relation === "all" ? " 且 " : " 或 ")}</p><footer><span>条件关系：{rule.condition_relation === "all" ? "全部满足" : "任一满足"}</span><strong>{String(rule.action.access_strategy ?? rule.action.rating_override ?? "策略收紧")}</strong></footer></div>)}</div></section>
      </section>

      <section id="model-governance" className="model-zone governance-zone">
        <ModelZoneHeader index="05" eyebrow="MODEL GOVERNANCE" title="模型配置、验证与发布治理" description="模型管理员在此组合指标、调整配置和提交版本；独立复核角色负责验证、发布、监控与回滚。" tags={["配置", "验证", "发布", "监控"]} />
      <ModelGovernancePanel model={model} modelKey={modelKey} canManage={canManage} canReview={canReview} onPublished={async () => { await loadAnalysis(); const rows = await api.models(); setModels(rows); }} onNotice={onNotice} />
      </section>
    </>}
  </div>;
}

function IndicatorObservationWorkbench({ indicators, selected, selectedId, onSelect, values, onValue, evidenceReference, onEvidenceReference, observedAt, onObservedAt, observations, canManage, canReview, busy, onSubmit, onReview }: { indicators: EnterpriseRiskIndicator[]; selected?: EnterpriseRiskIndicator; selectedId: string; onSelect: (value: string) => void; values: Record<string, number | boolean>; onValue: (path: string, value: number | boolean) => void; evidenceReference: string; onEvidenceReference: (value: string) => void; observedAt: string; onObservedAt: (value: string) => void; observations: EnterpriseIndicatorObservation[]; canManage: boolean; canReview: boolean; busy: boolean; onSubmit: () => void; onReview: (item: EnterpriseIndicatorObservation, decision: "verify" | "reject") => void }) {
  const paths = selected?.scoring.input_fields ?? (selected ? [selected.field_path] : []);
  return <section className="panel indicator-observation-panel"><div className="section-title"><div><span>INDICATOR EVIDENCE</span><h2>指标数据补充与复核</h2></div><span className="soft-chip">{observations.filter((item) => item.status === "verified").length} 项已生效</span></div><p className="indicator-observation-help">业务人员录入实际值和证据，复核人确认后才覆盖原始指标并触发风险筛查重算；提交人与复核人必须分离。</p><div className="indicator-observation-layout">{canManage ? <div className="indicator-observation-form"><label><span>待补充指标</span><select value={selectedId} onChange={(event) => onSelect(event.target.value)}>{indicators.map((item) => <option value={item.id} key={item.id}>{item.category} · {item.name}</option>)}</select></label>{selected && paths.map((path) => <label key={path}><span>{paths.length > 1 ? fieldLabel(path) : "实际值"}</span>{selected.scoring.type === "boolean_hit" ? <select value={String(Boolean(values[path]))} onChange={(event) => onValue(path, event.target.value === "true")}><option value="false">未触发</option><option value="true">已触发</option></select> : <input type="number" min="0" step="1" value={Number(values[path] ?? 0)} onChange={(event) => onValue(path, Number(event.target.value))} />}</label>)}<label><span>数据截止日期</span><input type="date" max={new Date().toISOString().slice(0, 10)} value={observedAt} onChange={(event) => onObservedAt(event.target.value)} /></label><label className="wide"><span>证据来源与定位</span><textarea value={evidenceReference} onChange={(event) => onEvidenceReference(event.target.value)} placeholder="例如：国家企业信用信息公示系统，变更记录第 1 页；或已核验材料名称及页码" /></label><button disabled={busy || !selected || evidenceReference.trim().length < 5} onClick={onSubmit}>{busy ? "正在处理…" : "提交独立复核"}</button>{selected && <small className="observation-formula">评分逻辑：{selected.scoring.formula}</small>}</div> : <div className="indicator-observation-readonly">当前身份仅可查看指标证据台账</div>}<div className="indicator-observation-history"><header><strong>证据与版本记录</strong><span>{observations.length} 条</span></header>{observations.length ? observations.map((item) => <article key={item.id} className={item.status}><div><span>{observationStatus(item.status)}</span><strong>{item.indicator_name}</strong><small>{Object.entries(item.values).map(([path, value]) => `${fieldLabel(path)}=${typeof value === "boolean" ? value ? "是" : "否" : value}`).join("；")}</small><p>{item.evidence_reference}</p><code>{item.observed_at.slice(0, 10)} · {item.created_by_name}{item.reviewed_by_name ? ` → ${item.reviewed_by_name}` : ""}</code></div>{canReview && item.status === "pending_review" && <footer><button className="reject" disabled={busy} onClick={() => onReview(item, "reject")}>驳回</button><button disabled={busy} onClick={() => onReview(item, "verify")}>复核生效</button></footer>}</article>) : <div className="indicator-observation-empty">尚无补充记录；模型继续使用原始数据，缺失项按 2 分处理。</div>}</div></div></section>;
}

function ModelZoneHeader({ index, eyebrow, title, description, tags }: { index: string; eyebrow: string; title: string; description: string; tags: string[] }) {
  return <header className="model-zone-header"><span>{index}</span><div><small>{eyebrow}</small><h2>{title}</h2><p>{description}</p></div><aside>{tags.map((item) => <i key={item}>{item}</i>)}</aside></header>;
}

function SummaryCard({ label, value, suffix, detail, tone }: { label: string; value: string; suffix: string; detail: string; tone: string }) { return <div className={`model-summary-card ${tone}`}><span>{label}</span><strong>{value}<small>{suffix}</small></strong><p>{detail}</p></div>; }
function ScorecardExecutionEvidence({ result }: { result: RatingTrace["result"] }) {
  const execution = result.scorecard_execution;
  if (!execution) return null;
  return <div className="scorecard-runtime-evidence">
    <header><div><span>GOVERNED SCORECARD</span><strong>{execution.code} @ v{execution.version}</strong></div><small>固定资产 {execution.scorecard_asset_id}</small></header>
    <div>
      <span><small>业务刻度分</small><strong>{execution.scaled_score.toFixed(2)}</strong><b>{execution.score_scale.min} - {execution.score_scale.max}</b></span>
      <span><small>标准分</small><strong>{execution.normalized_score.toFixed(1)}</strong><b>用于评级与策略映射</b></span>
      <span><small>分箱原始分</small><strong>{execution.raw_score.toFixed(2)}</strong><b>{execution.details.length} 项指标</b></span>
      <span><small>缺失指标</small><strong>{execution.missing_count}</strong><b>明确命中缺失箱</b></span>
      <span className="scorecard-runtime-hash"><small>评分卡配置哈希</small><code>{execution.config_hash}</code></span>
    </div>
  </div>;
}
function FlowNode({ index, label, detail, alert, final }: { index: string; label: string; detail: string; alert?: boolean; final?: boolean }) { return <div className={`flow-node ${alert ? "alert" : ""} ${final ? "final" : ""}`}><span>{index}</span><strong>{label}</strong><small>{detail}</small></div>; }
function FlowArrow() { return <div className="flow-arrow">→</div>; }

function ImpactResult({ impact }: { impact: ModelImpact }) {
  const rows = [
    ["综合评分", impact.before.total_score.toFixed(1), impact.after.total_score.toFixed(1), signed(impact.impact.总分变化)],
    ["信用等级", impact.before.rating, impact.after.rating, impact.impact.评级变化],
    ["建议额度", money.format(impact.before.suggested_limit), money.format(impact.after.suggested_limit), signedMoney(impact.impact.额度变化)],
    ["建议账期", `${impact.before.suggested_payment_term_days} 天`, `${impact.after.suggested_payment_term_days} 天`, `${signed(impact.impact.账期变化)} 天`],
    ["强规则", String(impact.before.strong_rule_hits.length), String(impact.after.strong_rule_hits.length), impact.impact.强规则变化],
    ["风险筛查分", impact.before_enterprise_risk_screening.normalized_score.toFixed(1), impact.after_enterprise_risk_screening.normalized_score.toFixed(1), signed(impact.impact.企业风险筛查分变化)],
    ["贷策命中", String(impact.before.risk_screening_policy?.hits.length ?? 0), String(impact.after.risk_screening_policy?.hits.length ?? 0), impact.impact.企业风险贷策命中变化],
  ];
  return <div className="impact-result"><div className="impact-head"><span>指标变动</span><strong>{formatRaw(impact.old_value)} → {formatRaw(impact.new_value)}</strong></div>{rows.map(([label, before, after, delta]) => <div className="impact-row" key={label}><span>{label}</span><b>{before}</b><i>→</i><strong>{after}</strong><small className={String(delta).startsWith("-") ? "negative" : String(delta).startsWith("+") ? "positive" : ""}>{delta}</small></div>)}<div className="strategy-change"><span>最终策略</span><strong>{impact.impact.策略变化}</strong></div></div>;
}

function RiskPolicyResult({ policy }: { policy: NonNullable<RatingTrace["result"]["risk_screening_policy"]> }) {
  return <div className={`risk-policy-result ${policy.changed ? "changed" : "stable"}`}><header><div><span>POST-SCORE POLICY</span><strong>企业风险贷策收紧</strong></div><b>{policy.hits.length ? `${policy.hits.length} 条命中` : "未命中"}</b></header><div className="risk-policy-before-after"><span><small>调整前</small><strong>{policy.before.rating} · {policy.before.access_strategy}</strong><b>{money.format(policy.before.suggested_limit)} / {policy.before.suggested_payment_term_days} 天</b></span><i>→</i><span><small>调整后</small><strong>{policy.after.rating} · {policy.after.access_strategy}</strong><b>{money.format(policy.after.suggested_limit)} / {policy.after.suggested_payment_term_days} 天</b></span></div>{policy.hits.length > 0 && <div className="risk-policy-hits">{policy.hits.map((hit) => <article key={hit.id}><span>{hit.id}</span><strong>{hit.name}</strong><code>{hit.expression}</code><small>评级下调 {hit.action.rating_notch_down} 档 · 额度上限 {(hit.action.limit_cap_ratio * 100).toFixed(0)}% · 账期上限 {hit.action.term_cap_days} 天 · {hit.action.access_strategy}</small></article>)}</div>}<p>{policy.formula}</p></div>;
}

function readPath(source: Counterparty, path: string): number {
  let current: unknown = source;
  for (const part of path.split(".")) {
    if (!current || typeof current !== "object" || !(part in current)) return 0;
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === "number" ? current : Number(current ?? 0);
}
function formatIndicator(value: number, indicator?: EditableIndicator): string { return indicator?.unit === "%" ? `${(indicator.value_scale === "whole" ? value : value * 100).toFixed(1)}%` : `${value.toLocaleString("zh-CN")} ${indicator?.unit ?? ""}`; }
function formatRaw(value: number | null): string { return value === null ? "待补充" : Number.isInteger(value) ? String(value) : value.toFixed(2); }
function signed(value: number): string { return value > 0 ? `+${value}` : String(value); }
function signedMoney(value: number): string { return `${value > 0 ? "+" : ""}${money.format(value)}`; }
function observationStatus(value: EnterpriseIndicatorObservation["status"]): string { return ({ pending_review: "待复核", verified: "已生效", rejected: "已驳回", superseded: "历史版本" } as const)[value]; }
function fieldLabel(path: string): string { const labels: Record<string, string> = { "external.established_years": "注册年限", "external.dishonesty_count": "失信记录次数", "external.operating_abnormal_count": "经营异常次数", "external.legal_cases_count": "重大纠纷次数", "external.shareholder_change_count_1y": "近一年股东变更次数", "external.legal_representative_change_count_12m": "近一年法人变更次数", "external.key_personnel_change_count_12m": "近一年主要人员变更次数", "external.admin_penalty_count": "行政处罚次数", "external.environmental_penalty_count": "环保处罚次数", "external.negative_news_count_3y": "近三年负面新闻次数" }; return labels[path] ?? path.split(".").pop()?.replaceAll("_", " ") ?? path; }
