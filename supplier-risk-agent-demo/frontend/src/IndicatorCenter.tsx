import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "./api";
import type { IndicatorCatalogItem, RuleCenterReplayDataset, RuleCenterReplaySnapshot, ScorecardAsset, ScorecardBin, ScorecardChange, ScorecardDefinitionPayload, ScorecardDependencyGraph, ScorecardDependencyNode, ScorecardDevelopmentExclusionRule, ScorecardDevelopmentRun, ScorecardDevelopmentTrendMetricKey, ScorecardDevelopmentTrends, ScorecardIndicatorBinding, ScorecardMonitoringEvent, ScorecardMonitoringEventFilters, ScorecardMonitoringEventType, ScorecardMonitoringPlan, ScorecardMonitoringRunConfig, ScorecardMonitoringSavedView, ScorecardMonitoringSchedulerHealth, ScorecardMonitoringSlaPolicy, ScorecardPortfolioStability, ScorecardPortfolioStatus, ScorecardValidationPolicy, ScorecardValidationThresholds } from "./types";
import type { CreditCalibrationCandidate, CreditCalibrationComparison, CreditCalibrationConfig, CreditCalibrationDistribution, CreditCalibrationPlan, CreditCalibrationResult } from "./types";

type Notice = { kind: "success" | "error"; text: string };
const emptyDefinition = (): ScorecardDefinitionPayload => ({ code: "", name: "", description: "", score_scale: { min: 300, max: 900, higher_is_better: true }, indicators: [] });
const defaultValidationThresholds: ScorecardValidationThresholds = { require_validation_snapshot: true, require_oot_snapshot: true, require_probability_evidence: false, require_sensitive_attribute_evidence: false, min_auc: 0.6, min_ks: 0.2, max_brier: 0.25, max_score_psi: 0.25, min_segment_coverage: 0.8, max_event_rate_gap: 0.2, max_average_score_gap: 15, max_auc_gap: 0.15, max_ks_gap: 0.15, max_false_positive_rate_gap: 0.15, max_false_negative_rate_gap: 0.15 };
const emptyValidationPolicy = () => ({ code: "INSTITUTION_STANDARD", name: "机构标准验证策略", description: "统一约束评分卡开发验证的最低上线标准", applicable_scorecard_codes: "", is_default: true, thresholds: { ...defaultValidationThresholds } });
const emptySlaPolicy = () => ({ code: "MONITORING_SLA_STANDARD", name: "持续验证标准 SLA", description: "统一约束持续验证预警的响应、临期和升级窗口", applicable_scorecard_codes: "", applicable_event_types: [] as ScorecardMonitoringEventType[], is_default: true, severity_rules: { critical: { response_hours: 24, due_soon_ratio: .25, escalation_after_hours: 4 }, warning: { response_hours: 72, due_soon_ratio: .25, escalation_after_hours: 4 } } });

export default function IndicatorCenter({ currentSubject, focusMonitoringEventId, focusRunId, canView, canManage, canReview, onOpenModelGovernance, onNotice }: { currentSubject: string; focusMonitoringEventId?: string; focusRunId?: string | null; canView: boolean; canManage: boolean; canReview: boolean; onOpenModelGovernance: (modelKey: string) => void; onNotice: (notice: Notice) => void }) {
  const [catalog, setCatalog] = useState<IndicatorCatalogItem[]>([]);
  const [assets, setAssets] = useState<ScorecardAsset[]>([]);
  const [changes, setChanges] = useState<ScorecardChange[]>([]);
  const [snapshots, setSnapshots] = useState<RuleCenterReplaySnapshot[]>([]);
  const [datasets, setDatasets] = useState<RuleCenterReplayDataset[]>([]);
  const [developmentRuns, setDevelopmentRuns] = useState<ScorecardDevelopmentRun[]>([]);
  const [developmentTrends, setDevelopmentTrends] = useState<ScorecardDevelopmentTrends | null>(null);
  const [portfolioStability, setPortfolioStability] = useState<ScorecardPortfolioStability | null>(null);
  const [validationPolicies, setValidationPolicies] = useState<ScorecardValidationPolicy[]>([]);
  const [monitoringPlans, setMonitoringPlans] = useState<ScorecardMonitoringPlan[]>([]);
  const [monitoringEvents, setMonitoringEvents] = useState<ScorecardMonitoringEvent[]>([]);
  const [monitoringScheduler, setMonitoringScheduler] = useState<ScorecardMonitoringSchedulerHealth | null>(null);
  const [monitoringSlaPolicies, setMonitoringSlaPolicies] = useState<ScorecardMonitoringSlaPolicy[]>([]);
  const [definition, setDefinition] = useState(emptyDefinition);
  const [editing, setEditing] = useState<ScorecardChange | null>(null);
  const [reason, setReason] = useState("配置评分卡指标分箱与权重");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<"design" | "calibration" | "governance" | "policies" | "sla-policies" | "development" | "assets">("design");
  const [busy, setBusy] = useState(false);
  const [reviewComments, setReviewComments] = useState<Record<string, string>>({});
  const [development, setDevelopment] = useState({ scorecard_asset_id: "", validation_policy_id: "", dataset_snapshot_id: "", validation_snapshot_id: "", oot_snapshot_id: "", subject_id_field: "id", predicted_probability_field: "", segment_fields: "", sensitive_attribute_fields: "", min_segment_sample_count: 30, classification_threshold: 0.5, validation_thresholds: { ...defaultValidationThresholds }, positive_labels: "bad,default,reject", observation_start: "", observation_end: "", performance_window_days: 180, maturity_days: 90, min_sample_count: 100, min_event_count: 20, min_non_event_count: 20 });
  const [exclusionRules, setExclusionRules] = useState<ScorecardDevelopmentExclusionRule[]>([]);
  const [policyDraft, setPolicyDraft] = useState(emptyValidationPolicy);
  const [editingPolicy, setEditingPolicy] = useState<ScorecardValidationPolicy | null>(null);
  const [policyReason, setPolicyReason] = useState("建立机构统一验证门槛");
  const [developmentView, setDevelopmentView] = useState<"portfolio" | "trends" | "runs" | "monitoring">("portfolio");

  async function refresh() {
    const [catalogResult, assetRows, changeRows, datasetRows, snapshotRows, developmentRows, policyRows, slaPolicyRows, trendResult, portfolioResult, planRows, eventRows, schedulerHealth] = await Promise.all([api.indicatorCatalog(), api.scorecards(), api.scorecardChanges(), api.ruleCenterReplayDatasets(), api.ruleCenterReplaySnapshots(), api.scorecardDevelopmentRuns(), api.validationPolicies(), api.scorecardMonitoringSlaPolicies(), api.scorecardDevelopmentTrends(), api.scorecardPortfolioStability(), api.scorecardMonitoringPlans(), api.scorecardMonitoringEvents(), api.scorecardMonitoringSchedulerHealth()]);
    setCatalog(catalogResult.items); setAssets(assetRows); setChanges(changeRows); setDatasets(datasetRows); setSnapshots(snapshotRows); setDevelopmentRuns(developmentRows); setValidationPolicies(policyRows); setMonitoringSlaPolicies(slaPolicyRows); setDevelopmentTrends(trendResult); setPortfolioStability(portfolioResult); setMonitoringPlans(planRows); setMonitoringEvents(eventRows); setMonitoringScheduler(schedulerHealth);
    setDevelopment((current) => ({ ...current, scorecard_asset_id: current.scorecard_asset_id || assetRows.find((item) => item.is_active)?.id || assetRows[0]?.id || "", validation_policy_id: current.validation_policy_id || policyRows.find((item) => item.is_active && item.is_default)?.id || "", dataset_snapshot_id: current.dataset_snapshot_id || snapshotRows[0]?.id || "" }));
  }
  useEffect(() => { if (canView) void refresh().catch((error: Error) => onNotice({ kind: "error", text: error.message })); }, [canView]);
  useEffect(() => {
    if (!focusMonitoringEventId && !focusRunId) return;
    setTab("development");
    setDevelopmentView(focusMonitoringEventId ? "monitoring" : "runs");
    const target = focusMonitoringEventId ? `monitoring-event-${focusMonitoringEventId}` : `development-run-${focusRunId}`;
    window.setTimeout(() => document.getElementById(target)?.scrollIntoView({ behavior: "smooth", block: "center" }), 80);
  }, [focusMonitoringEventId, focusRunId]);

  const filtered = useMemo(() => catalog.filter((item) => `${item.name} ${item.code} ${item.category}`.toLowerCase().includes(query.trim().toLowerCase())), [catalog, query]);
  const totalWeight = definition.indicators.reduce((sum, item) => sum + item.weight, 0);
  const rawMinimum = weightedEdge(definition.indicators, "min");
  const rawMaximum = weightedEdge(definition.indicators, "max");
  const selectedValidationPolicy = validationPolicies.find((item) => item.id === development.validation_policy_id);
  const selectedScorecardCode = assets.find((item) => item.id === development.scorecard_asset_id)?.code;
  const applicableValidationPolicies = validationPolicies.filter((item) => item.is_active && (!item.applicable_scorecard_codes.length || item.applicable_scorecard_codes.includes(selectedScorecardCode ?? "")));

  function addIndicator(item: IndicatorCatalogItem) {
    if (definition.indicators.some((binding) => binding.indicator_code === item.code)) return;
    if (!item.field_path) return onNotice({ kind: "error", text: `指标 ${item.name} 缺少治理字段路径，暂不能加入评分卡` });
    const binding: ScorecardIndicatorBinding = { indicator_code: item.code, indicator_version: item.version, indicator_name: item.name, field_path: item.field_path, data_type: item.data_type, weight: item.default_weight || 1, bins: starterBins(item.data_type) };
    setDefinition({ ...definition, indicators: [...definition.indicators, binding] });
  }
  function updateBinding(index: number, next: ScorecardIndicatorBinding) { setDefinition({ ...definition, indicators: definition.indicators.map((item, itemIndex) => itemIndex === index ? next : item) }); }
  function loadDraft(change: ScorecardChange) { setEditing(change); setDefinition(change.definition); setReason(change.change_reason); setTab("design"); }
  function reset() { setEditing(null); setDefinition(emptyDefinition()); setReason("配置评分卡指标分箱与权重"); }

  async function save() {
    setBusy(true);
    try {
      const result = editing ? await api.updateScorecardChange(editing.id, editing.row_version, definition, reason) : await api.createScorecardChange(definition, reason);
      setEditing(result); await refresh(); onNotice({ kind: "success", text: `评分卡 ${result.code} v${result.candidate_version} 草稿已保存` });
    } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  async function submit(change: ScorecardChange) { await act(async () => api.submitScorecardChange(change.id, change.row_version), "评分卡已提交独立复核"); }
  async function review(change: ScorecardChange, decision: "publish" | "reject") {
    const comment = reviewComments[change.id]?.trim();
    if (!comment || comment.trim().length < 5) return;
    await act(async () => api.reviewScorecardChange(change.id, change.row_version, decision, comment), decision === "publish" ? "评分卡已发布" : "评分卡已驳回");
  }
  async function act(action: () => Promise<ScorecardChange>, message: string) { setBusy(true); try { await action(); await refresh(); onNotice({ kind: "success", text: message }); } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); } }
  function loadPolicyDraft(policy: ScorecardValidationPolicy, asNewVersion = false) {
    setEditingPolicy(asNewVersion ? null : policy);
    setPolicyDraft({ code: policy.code, name: policy.name, description: policy.description, applicable_scorecard_codes: policy.applicable_scorecard_codes.join(","), is_default: policy.is_default, thresholds: { ...policy.thresholds } });
    setPolicyReason(asNewVersion ? `基于 ${policy.code} v${policy.version} 调整验证门槛` : policy.change_reason);
    setTab("policies");
  }
  function resetPolicyDraft() {
    setEditingPolicy(null); setPolicyDraft(emptyValidationPolicy()); setPolicyReason("建立机构统一验证门槛");
  }
  async function savePolicy() {
    setBusy(true);
    try {
      const payload = { code: policyDraft.code, name: policyDraft.name, description: policyDraft.description, applicable_scorecard_codes: csvFields(policyDraft.applicable_scorecard_codes).map((item) => item.toUpperCase()), is_default: policyDraft.is_default, thresholds: policyDraft.thresholds };
      const result = editingPolicy ? await api.updateValidationPolicy(editingPolicy.id, editingPolicy.row_version, payload, policyReason) : await api.createValidationPolicy(payload, policyReason);
      setEditingPolicy(result); setPolicyDraft({ code: result.code, name: result.name, description: result.description, applicable_scorecard_codes: result.applicable_scorecard_codes.join(","), is_default: result.is_default, thresholds: { ...result.thresholds } });
      await refresh(); onNotice({ kind: "success", text: `验证策略 ${result.code} v${result.version} 草稿已保存` });
    } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  async function policyAction(action: () => Promise<ScorecardValidationPolicy>, message: string) { setBusy(true); try { await action(); await refresh(); onNotice({ kind: "success", text: message }); } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); } }
  async function reviewPolicy(policy: ScorecardValidationPolicy, decision: "publish" | "reject") {
    const comment = reviewComments[policy.id]?.trim(); if (!comment || comment.length < 5) return;
    await policyAction(() => api.reviewValidationPolicy(policy.id, policy.row_version, decision, comment), decision === "publish" ? "验证策略已发布" : "验证策略已驳回");
  }
  async function runDevelopmentAnalysis() {
    setBusy(true);
    try {
      const result = await api.createScorecardDevelopmentRun({ ...development, validation_snapshot_id: development.validation_snapshot_id || undefined, oot_snapshot_id: development.oot_snapshot_id || undefined, predicted_probability_field: development.predicted_probability_field || undefined, segment_fields: csvFields(development.segment_fields), sensitive_attribute_fields: csvFields(development.sensitive_attribute_fields), positive_labels: csvFields(development.positive_labels), observation_start: development.observation_start || undefined, observation_end: development.observation_end || undefined, exclusion_rules: exclusionRules });
      await refresh(); onNotice({ kind: "success", text: `${result.scorecard_code} v${result.scorecard_version} 开发验证证据已固化` });
    } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  async function reviewDevelopment(run: ScorecardDevelopmentRun, decision: "approve" | "reject") {
    const comment = reviewComments[run.id]?.trim();
    if (!comment || comment.length < 5) return;
    setBusy(true);
    try {
      await api.reviewScorecardDevelopmentRun(run.id, run.row_version, decision, comment);
      await refresh(); onNotice({ kind: "success", text: decision === "approve" ? "验证证据已独立批准" : "验证证据已驳回" });
    } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  function openTrendRun(runId: string) {
    setDevelopmentView("runs");
    window.setTimeout(() => document.getElementById(`development-run-${runId}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  if (!canView) return <section className="panel"><h2>无权查看指标配置中心</h2></section>;
  return <div className="indicator-center">
    <section className="indicator-center-head"><div><span>INDICATOR & SCORECARD</span><h2>指标配置与评分卡设计</h2><p>固定指标版本，配置分箱、分值与权重，经独立复核后形成可绑定模型的评分卡资产。</p></div><div className="indicator-center-metrics"><div><b>{catalog.length}</b><span>可用指标</span></div><div><b>{assets.filter((item) => item.is_active).length}</b><span>生效评分卡</span></div><div><b>{changes.filter((item) => ["draft", "submitted"].includes(item.status)).length}</b><span>在途变更</span></div></div></section>
    <div className="workspace-tabs"><button className={tab === "design" ? "active" : ""} onClick={() => setTab("design")}>评分卡设计</button><button className={tab === "calibration" ? "active" : ""} onClick={() => setTab("calibration")}>授信校准</button><button className={tab === "governance" ? "active" : ""} onClick={() => setTab("governance")}>变更治理 <span>{changes.filter((item) => item.status === "submitted").length}</span></button><button className={tab === "policies" ? "active" : ""} onClick={() => setTab("policies")}>验证策略 <span>{validationPolicies.filter((item) => item.status === "submitted").length}</span></button><button className={tab === "sla-policies" ? "active" : ""} onClick={() => setTab("sla-policies")}>SLA 策略 <span>{monitoringSlaPolicies.filter((item) => item.status === "submitted").length}</span></button><button className={tab === "development" ? "active" : ""} onClick={() => setTab("development")}>开发验证 <span>{developmentRuns.length}</span></button><button className={tab === "assets" ? "active" : ""} onClick={() => setTab("assets")}>已发布资产</button></div>
    {tab === "design" && <div className="scorecard-workbench">
      <aside className="indicator-catalog"><header><div><span>指标目录</span><b>{filtered.length}</b></div><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、编码、分类" /></header><div className="catalog-list">{filtered.map((item) => { const selected = definition.indicators.some((binding) => binding.indicator_code === item.code); return <button key={`${item.code}-${item.version}`} className={selected ? "selected" : ""} onClick={() => addIndicator(item)} disabled={!canManage || selected}><strong>{item.name}</strong><span>{item.category} · {item.data_type}</span><small>{item.version_source === "indicator_factory" ? "指标工厂" : "企业指标池"} / {item.version}</small></button>; })}</div></aside>
      <main className="scorecard-designer"><div className="scorecard-fields"><label><span>评分卡编码</span><input disabled={Boolean(editing)} value={definition.code} onChange={(event) => setDefinition({ ...definition, code: event.target.value.toUpperCase() })} placeholder="如 SME_CREDIT_SCORE" /></label><label><span>评分卡名称</span><input value={definition.name} onChange={(event) => setDefinition({ ...definition, name: event.target.value })} /></label><label className="wide"><span>用途与口径</span><input value={definition.description} onChange={(event) => setDefinition({ ...definition, description: event.target.value })} /></label><label><span>最低总分</span><input type="number" value={definition.score_scale.min} onChange={(event) => setDefinition({ ...definition, score_scale: { ...definition.score_scale, min: Number(event.target.value) } })} /></label><label><span>最高总分</span><input type="number" value={definition.score_scale.max} onChange={(event) => setDefinition({ ...definition, score_scale: { ...definition.score_scale, max: Number(event.target.value) } })} /></label></div>
        <section className="score-preview"><div><span>指标数</span><b>{definition.indicators.length}</b></div><div className={Math.abs(totalWeight - 100) > .01 ? "warning" : "pass"}><span>权重合计</span><b>{totalWeight.toFixed(2)}%</b></div><div><span>原始分范围</span><b>{rawMinimum.toFixed(1)} - {rawMaximum.toFixed(1)}</b></div><div><span>映射总分</span><b>{definition.score_scale.min} - {definition.score_scale.max}</b></div></section>
        <div className="binding-list">{definition.indicators.length ? definition.indicators.map((binding, index) => <BindingEditor key={`${binding.indicator_code}-${binding.indicator_version}`} binding={binding} onChange={(next) => updateBinding(index, next)} onRemove={() => setDefinition({ ...definition, indicators: definition.indicators.filter((_, itemIndex) => itemIndex !== index) })} editable={canManage} />) : <div className="scorecard-empty"><strong>从左侧选择指标</strong><span>每个指标会固定当前版本，并自动建立可编辑的初始分箱。</span></div>}</div>
        <footer className="scorecard-actions"><label><span>变更原因</span><input value={reason} onChange={(event) => setReason(event.target.value)} /></label><button className="secondary-button" onClick={reset}>新建</button><button className="primary-button" disabled={!canManage || busy || definition.indicators.length === 0 || definition.code.length < 2 || definition.name.length < 2 || definition.description.length < 5 || reason.length < 5} onClick={() => void save()}>{busy ? "保存中…" : editing ? "更新草稿" : "保存草稿"}</button></footer>
      </main>
    </div>}
    {tab === "calibration" && <CreditCalibrationWorkbench snapshots={snapshots} datasets={datasets} currentSubject={currentSubject} canManage={canManage} canReview={canReview} onOpenModelGovernance={onOpenModelGovernance} onNotice={onNotice} />}
{tab === "governance" && <section className="scorecard-governance-list">{changes.map((change) => <article key={change.id}><header><div><span className={`status-pill ${change.status}`}>{statusLabel(change.status)}</span><h3>{change.definition.name}</h3><small>{change.code} · v{change.candidate_version} · {change.created_by_name}</small></div><div className="governance-actions">{change.status === "draft" && <button onClick={() => loadDraft(change)}>编辑</button>}{change.status === "draft" && canManage && <button className="primary-button" disabled={!change.validation.valid || busy} onClick={() => void submit(change)}>提交复核</button>}{change.status === "submitted" && canReview && change.created_by !== currentSubject && <><input aria-label={`复核意见 ${change.code}`} value={reviewComments[change.id] ?? ""} onChange={(event) => setReviewComments({ ...reviewComments, [change.id]: event.target.value })} placeholder="填写独立复核结论" /><button disabled={(reviewComments[change.id]?.trim().length ?? 0) < 5} onClick={() => void review(change, "reject")}>驳回</button><button className="primary-button" title={change.impact.dependency_graph_drifted ? "依赖图已变化，必须由创建人重新提交" : undefined} disabled={(reviewComments[change.id]?.trim().length ?? 0) < 5 || change.impact.dependency_graph_drifted} onClick={() => void review(change, "publish")}>批准发布</button></>}</div></header><div className="governance-evidence"><div><span>配置证据</span><b>{change.validation.summary.indicator_count} 指标 / {change.validation.summary.bin_count} 分箱</b><small>权重 {change.validation.summary.total_weight.toFixed(2)}%</small></div><div><span>模型影响</span><b>{change.impact.affected_models.length ? change.impact.affected_models.join("、") : "暂未绑定模型"}</b><small>{change.impact.inflight_model_drafts.length} 个在途模型草稿</small></div><div className={change.validation.valid && !change.impact.dependency_graph_drifted ? "pass" : "blocked"}><span>校验结果</span><b>{change.impact.dependency_graph_drifted ? "依赖已漂移" : change.validation.valid ? "通过" : `${change.validation.errors.length} 项阻断`}</b><small>{change.impact.dependency_graph_drifted ? "重新提交后才能批准发布" : change.validation.warnings[0] ?? "无额外警告"}</small></div></div><ScorecardDependencyGraphView graph={change.impact.dependency_graph} drifted={change.impact.dependency_graph_drifted} legacy={change.impact.dependency_graph_legacy} currentHash={change.impact.dependency_graph_current_hash} /></article>)}</section>}
    {tab === "policies" && <section className="validation-policy-workspace">
      {canManage && <div className="validation-policy-editor"><header><div><span>VALIDATION POLICY GOVERNANCE</span><h3>{editingPolicy ? `编辑 ${editingPolicy.code} v${editingPolicy.version}` : "机构验证策略模板"}</h3><p>发布后门槛由服务端固定，单次开发运行不能自行放宽。</p></div><div className="policy-editor-actions"><button className="secondary-button" disabled={busy} onClick={resetPolicyDraft}>{editingPolicy ? "取消编辑" : "重置"}</button><button className="primary-button" disabled={busy || policyDraft.code.length < 2 || policyDraft.name.length < 2 || policyDraft.description.length < 5 || policyReason.length < 5} onClick={() => void savePolicy()}>{editingPolicy ? "更新策略草稿" : "保存策略草稿"}</button></div></header><div className="policy-fields"><label><span>策略编码</span><input disabled={Boolean(editingPolicy)} value={policyDraft.code} onChange={(event) => setPolicyDraft({ ...policyDraft, code: event.target.value.toUpperCase() })} /></label><label><span>策略名称</span><input value={policyDraft.name} onChange={(event) => setPolicyDraft({ ...policyDraft, name: event.target.value })} /></label><label className="wide"><span>治理说明</span><input value={policyDraft.description} onChange={(event) => setPolicyDraft({ ...policyDraft, description: event.target.value })} /></label><label><span>适用评分卡编码</span><input disabled={policyDraft.is_default} value={policyDraft.applicable_scorecard_codes} onChange={(event) => setPolicyDraft({ ...policyDraft, applicable_scorecard_codes: event.target.value })} placeholder="留空表示全部" /></label><label className="policy-default"><input type="checkbox" checked={policyDraft.is_default} onChange={(event) => setPolicyDraft({ ...policyDraft, is_default: event.target.checked, applicable_scorecard_codes: event.target.checked ? "" : policyDraft.applicable_scorecard_codes })} /><span>设为机构默认</span></label><label className="wide"><span>变更原因</span><input value={policyReason} onChange={(event) => setPolicyReason(event.target.value)} /></label></div><ThresholdEditor thresholds={policyDraft.thresholds} onChange={(thresholds) => setPolicyDraft({ ...policyDraft, thresholds })} /></div>}
      <div className="validation-policy-list">{validationPolicies.length ? validationPolicies.map((policy) => <article key={policy.id}><header><div><span className={`status-pill ${policy.status}`}>{policyStatusLabel(policy.status)}</span><h3>{policy.name}</h3><small>{policy.code} · v{policy.version} · {policy.created_by_name}</small></div><div className="governance-actions">{policy.status === "draft" && canManage && policy.created_by === currentSubject && <><button disabled={busy} onClick={() => loadPolicyDraft(policy)}>编辑草稿</button><button className="primary-button" disabled={busy} onClick={() => void policyAction(() => api.submitValidationPolicy(policy.id, policy.row_version), "验证策略已提交独立复核")}>提交复核</button></>}{policy.status === "published" && canManage && <button disabled={busy} onClick={() => loadPolicyDraft(policy, true)}>创建新版本</button>}{policy.status === "submitted" && canReview && policy.created_by !== currentSubject && <><input aria-label={`策略复核意见 ${policy.code}`} value={reviewComments[policy.id] ?? ""} onChange={(event) => setReviewComments({ ...reviewComments, [policy.id]: event.target.value })} placeholder="填写独立复核结论" /><button disabled={(reviewComments[policy.id]?.trim().length ?? 0) < 5} onClick={() => void reviewPolicy(policy, "reject")}>驳回</button><button className="primary-button" disabled={(reviewComments[policy.id]?.trim().length ?? 0) < 5} onClick={() => void reviewPolicy(policy, "publish")}>批准发布</button></>}</div></header><div className="policy-meta"><div><span>适用范围</span><b>{policy.applicable_scorecard_codes.length ? policy.applicable_scorecard_codes.join("、") : "全部评分卡"}</b></div><div><span>默认策略</span><b>{policy.is_default ? policy.is_active ? "机构当前默认" : "默认候选/历史" : "显式选择"}</b></div><div><span>配置哈希</span><code>{policy.config_hash.slice(0, 16)}</code></div></div><PolicyThresholdSummary thresholds={policy.thresholds} /></article>) : <div className="scorecard-empty"><strong>暂无验证策略模板</strong><span>创建并独立发布机构默认策略后，开发运行将强制使用固定门槛。</span></div>}</div>
    </section>}
    {tab === "sla-policies" && <SlaPolicyWorkspace policies={monitoringSlaPolicies} currentSubject={currentSubject} canManage={canManage} canReview={canReview} onRefresh={refresh} onNotice={onNotice} />}
    {tab === "development" && <section className="scorecard-development">
      <div className="development-view-toolbar"><div className="segmented-control" aria-label="开发验证视图"><button className={developmentView === "portfolio" ? "active" : ""} onClick={() => setDevelopmentView("portfolio")}>组合稳定性</button><button className={developmentView === "trends" ? "active" : ""} onClick={() => setDevelopmentView("trends")}>趋势监控</button><button className={developmentView === "runs" ? "active" : ""} onClick={() => setDevelopmentView("runs")}>运行与证据</button><button className={developmentView === "monitoring" ? "active" : ""} onClick={() => setDevelopmentView("monitoring")}>监控计划 <span>{monitoringEvents.filter((item) => item.status !== "closed").length}</span></button></div><span>{developmentTrends?.summary.run_count ?? 0} 次固定运行 · {developmentTrends?.summary.pending_review_count ?? 0} 条待复核</span></div>
      {developmentView === "portfolio" ? <PortfolioStabilityDashboard portfolio={portfolioStability} onOpenRun={openTrendRun} onOpenMonitoring={() => setDevelopmentView("monitoring")} /> : developmentView === "trends" ? <DevelopmentTrendDashboard trends={developmentTrends} onOpenRun={openTrendRun} /> : developmentView === "monitoring" ? <ScorecardMonitoringWorkbench assets={assets} policies={validationPolicies} datasets={datasets} developmentRuns={developmentRuns} plans={monitoringPlans} events={monitoringEvents} schedulerHealth={monitoringScheduler} currentSubject={currentSubject} canManage={canManage} canReview={canReview} onRefresh={refresh} onNotice={onNotice} onOpenRun={openTrendRun} /> : <>
      <div className="development-config"><header><div><span>SCORECARD DEVELOPMENT DATASET</span><h3>训练、验证与时间外检验</h3><p>固定评分卡及三套不可变快照，阻断主体跨集合泄漏，并固化 WOE/IV、区分度、校准与稳定性证据。</p></div><button className="primary-button" disabled={!canManage || busy || !development.scorecard_asset_id || !development.dataset_snapshot_id || !development.subject_id_field.trim() || !development.positive_labels.trim()} onClick={() => void runDevelopmentAnalysis()}>{busy ? "分析中…" : "运行并固化证据"}</button></header>
        <div className="development-fields">
          <label><span>已发布评分卡</span><select value={development.scorecard_asset_id} onChange={(event) => setDevelopment({ ...development, scorecard_asset_id: event.target.value, validation_policy_id: "" })}><option value="">请选择评分卡</option>{assets.map((item) => <option key={item.id} value={item.id}>{item.code} · v{item.version}{item.is_active ? " · 当前生效" : " · 历史版本"}</option>)}</select></label>
          <label><span>验证策略模板</span><select value={development.validation_policy_id} onChange={(event) => setDevelopment({ ...development, validation_policy_id: event.target.value })}><option value="">{applicableValidationPolicies.some((item) => item.is_default) ? "自动使用机构默认" : "兼容内置默认"}</option>{applicableValidationPolicies.map((item) => <option key={item.id} value={item.id}>{item.code} · v{item.version}{item.is_default ? " · 机构默认" : ""}</option>)}</select></label>
          <label><span>训练集快照</span><select value={development.dataset_snapshot_id} onChange={(event) => setDevelopment({ ...development, dataset_snapshot_id: event.target.value })}><option value="">请选择快照</option>{snapshots.map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.as_of_date} · {item.sample_count} 条 · 标签 {(item.coverage.label_coverage_rate * 100).toFixed(0)}%</option>)}</select></label>
          <label><span>验证集快照（可选）</span><select value={development.validation_snapshot_id} onChange={(event) => setDevelopment({ ...development, validation_snapshot_id: event.target.value })}><option value="">暂不配置</option>{snapshots.filter((item) => item.id !== development.dataset_snapshot_id).map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.as_of_date} · {item.sample_count} 条</option>)}</select></label>
          <label><span>时间外快照（可选）</span><select value={development.oot_snapshot_id} onChange={(event) => setDevelopment({ ...development, oot_snapshot_id: event.target.value })}><option value="">暂不配置</option>{snapshots.filter((item) => item.id !== development.dataset_snapshot_id && item.id !== development.validation_snapshot_id).map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.as_of_date} · {item.sample_count} 条</option>)}</select></label>
          <label><span>主体标识字段</span><input value={development.subject_id_field} onChange={(event) => setDevelopment({ ...development, subject_id_field: event.target.value })} placeholder="id" /></label>
          <label><span>预测事件概率字段（可选）</span><input value={development.predicted_probability_field} onChange={(event) => setDevelopment({ ...development, predicted_probability_field: event.target.value })} placeholder="predicted_pd" /></label>
          <label><span>分群字段（逗号分隔）</span><input value={development.segment_fields} onChange={(event) => setDevelopment({ ...development, segment_fields: event.target.value })} placeholder="region,enterprise_type" /></label>
          <label><span>敏感属性字段（可选）</span><input value={development.sensitive_attribute_fields} onChange={(event) => setDevelopment({ ...development, sensitive_attribute_fields: event.target.value })} placeholder="必须同时属于分群字段" /></label>
          <label><span>最低分群样本</span><input type="number" min="2" max="5000" value={development.min_segment_sample_count} onChange={(event) => setDevelopment({ ...development, min_segment_sample_count: Number(event.target.value) })} /></label>
          <label><span>事件分类阈值</span><input type="number" min="0" max="1" step="0.01" value={development.classification_threshold} onChange={(event) => setDevelopment({ ...development, classification_threshold: Number(event.target.value) })} /></label>
          <label><span>事件标签</span><input value={development.positive_labels} onChange={(event) => setDevelopment({ ...development, positive_labels: event.target.value })} placeholder="bad,default,reject" /></label>
          <label><span>观察窗口开始</span><input type="date" value={development.observation_start} onChange={(event) => setDevelopment({ ...development, observation_start: event.target.value })} /></label>
          <label><span>观察窗口结束</span><input type="date" value={development.observation_end} onChange={(event) => setDevelopment({ ...development, observation_end: event.target.value })} /></label>
          <label><span>表现窗口（天）</span><input type="number" min="1" max="3650" value={development.performance_window_days} onChange={(event) => setDevelopment({ ...development, performance_window_days: Number(event.target.value) })} /></label>
          <label><span>成熟期（天）</span><input type="number" min="0" max="3650" value={development.maturity_days} onChange={(event) => setDevelopment({ ...development, maturity_days: Number(event.target.value) })} /></label>
          <label><span>最低有效样本</span><input type="number" min="1" max="5000" value={development.min_sample_count} onChange={(event) => setDevelopment({ ...development, min_sample_count: Number(event.target.value) })} /></label>
          <label><span>最低事件样本</span><input type="number" min="1" max="5000" value={development.min_event_count} onChange={(event) => setDevelopment({ ...development, min_event_count: Number(event.target.value) })} /></label>
          <label><span>最低非事件样本</span><input type="number" min="1" max="5000" value={development.min_non_event_count} onChange={(event) => setDevelopment({ ...development, min_non_event_count: Number(event.target.value) })} /></label>
        </div>
        {selectedValidationPolicy ? <section className="selected-validation-policy"><header><div><span>GOVERNED POLICY</span><strong>{selectedValidationPolicy.name} · v{selectedValidationPolicy.version}</strong><small>{selectedValidationPolicy.is_default ? "机构默认" : "显式适用"} · 配置哈希 {selectedValidationPolicy.config_hash.slice(0, 16)}</small></div><b>门槛只读</b></header><PolicyThresholdSummary thresholds={selectedValidationPolicy.thresholds} /></section> : <ThresholdEditor thresholds={development.validation_thresholds} onChange={(validation_thresholds) => setDevelopment({ ...development, validation_thresholds })} />}
        <div className="development-exclusions"><div><strong>样本排除规则</strong><button className="secondary-button" onClick={() => setExclusionRules([...exclusionRules, { field_path: "", operator: "equals", value: "", reason: "" }])}>新增规则</button></div>{exclusionRules.map((rule, index) => <div className="exclusion-row" key={index}><input aria-label={`排除字段 ${index + 1}`} placeholder="字段路径" value={rule.field_path} onChange={(event) => setExclusionRules(exclusionRules.map((item, itemIndex) => itemIndex === index ? { ...item, field_path: event.target.value } : item))} /><select aria-label={`排除运算符 ${index + 1}`} value={rule.operator} onChange={(event) => setExclusionRules(exclusionRules.map((item, itemIndex) => itemIndex === index ? { ...item, operator: event.target.value as ScorecardDevelopmentExclusionRule["operator"] } : item))}><option value="equals">等于</option><option value="not_equals">不等于</option><option value="in">属于</option><option value="is_missing">缺失</option><option value="not_missing">非缺失</option></select><input aria-label={`排除值 ${index + 1}`} placeholder="比较值" disabled={["is_missing", "not_missing"].includes(rule.operator)} value={String(rule.value ?? "")} onChange={(event) => setExclusionRules(exclusionRules.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item))} /><input aria-label={`排除原因 ${index + 1}`} placeholder="排除原因" value={rule.reason} onChange={(event) => setExclusionRules(exclusionRules.map((item, itemIndex) => itemIndex === index ? { ...item, reason: event.target.value } : item))} /><button aria-label={`删除排除规则 ${index + 1}`} title="删除排除规则" onClick={() => setExclusionRules(exclusionRules.filter((_, itemIndex) => itemIndex !== index))}>×</button></div>)}</div>
      </div>
      <div className="development-run-list">{developmentRuns.length ? developmentRuns.map((run) => <article id={`development-run-${run.id}`} key={run.id} className={run.integrity_valid ? "" : "invalid"}><header><div><span className={`development-level ${run.evidence_level}`}>{run.evidence_level === "labeled" ? "监督证据" : run.evidence_level === "degraded" ? "样本降级" : "无标签降级"}</span><h3>{run.scorecard_code} @ v{run.scorecard_version}</h3><small>{run.created_by_name} · {run.created_at ? new Date(run.created_at).toLocaleString("zh-CN") : ""}</small></div><div><span>{reviewStatusLabel(run.review_status)}</span><strong>{run.integrity_valid ? "证据可复算" : "校验失败"}</strong><code>{run.evidence_hash.slice(0, 16)}</code></div></header>
        {run.validation_policy && <div className={`run-validation-policy ${run.validation_policy_integrity_valid ? "valid" : "invalid"}`}><div><span>固定验证策略</span><strong>{run.validation_policy.name} · {run.validation_policy.code} @ v{run.validation_policy.version}</strong></div><div><span>{run.validation_policy_integrity_valid ? "策略证据可复算" : "策略证据漂移"}</span><code>{run.validation_policy.config_hash.slice(0, 16)}</code></div></div>}
        <div className="development-summary"><div><span>有效样本</span><b>{run.report.summary.eligible_sample_count}</b><small>快照 {run.report.summary.snapshot_sample_count}</small></div><div><span>事件 / 非事件</span><b>{run.report.summary.event_count} / {run.report.summary.non_event_count}</b><small>未标注 {run.report.summary.unlabeled_count}</small></div><div><span>排除 / 未成熟</span><b>{run.report.summary.excluded_count} / {run.report.summary.immature_count}</b><small>窗口外 {run.report.summary.outside_window_count}</small></div><div><span>总 IV</span><b>{run.report.summary.total_information_value.toFixed(4)}</b><small>样本计算，不覆盖人工 WOE</small></div></div>
        {run.report.validation_gate && <DevelopmentValidationGate run={run} />}
        {run.report.performance && <DevelopmentPerformance run={run} />}
        {run.report.performance && <DevelopmentEvidenceVisuals run={run} />}
        {run.report.fairness && <DevelopmentFairness run={run} />}
        <div className="development-gates">{Object.entries(run.report.gates).map(([key, gate]) => <span className={gate.passed ? "pass" : "blocked"} key={key}><b>{gate.passed ? "通过" : "不足"}</b>{gate.actual} / {gate.required}</span>)}</div>
        {run.report.warnings.map((warning) => <p className="development-warning" key={warning}>{warning}</p>)}
        <DevelopmentReview run={run} currentSubject={currentSubject} canReview={canReview} busy={busy} comment={reviewComments[run.id] ?? ""} onComment={(value) => setReviewComments({ ...reviewComments, [run.id]: value })} onReview={(decision) => void reviewDevelopment(run, decision)} />
        <div className="development-indicators">{run.report.indicators.map((indicator) => <details key={indicator.indicator_code}><summary><div><strong>{indicator.indicator_name}</strong><span>{indicator.indicator_code} @ {indicator.indicator_version}</span></div><div><span>IV</span><b>{indicator.information_value.toFixed(4)}</b></div><div><span>事件率单调</span><b>{indicator.event_rate_monotonic === null ? "N/A" : indicator.event_rate_monotonic ? "是" : "否"}</b></div></summary><div className="development-bin-table"><div><b>分箱</b><b>样本</b><b>事件率</b><b>人工 WOE</b><b>计算 WOE</b><b>IV 贡献</b></div>{indicator.bins.map((bin) => <div key={bin.bin_index}><span>{bin.bin_label}</span><span>{bin.sample_count}</span><span>{bin.event_rate === null ? "N/A" : `${(bin.event_rate * 100).toFixed(1)}%`}</span><span>{bin.configured_woe ?? "未配置"}</span><span>{bin.calculated_woe === null ? "N/A" : bin.calculated_woe.toFixed(4)}</span><span>{bin.iv_contribution === null ? "N/A" : bin.iv_contribution.toFixed(4)}</span></div>)}</div></details>)}</div>
      </article>) : <div className="scorecard-empty"><strong>暂无开发验证证据</strong><span>先在决策规则的数据集区导入带标签和观察时间的不可变快照。</span></div>}</div></>}
    </section>}
    {tab === "assets" && <section className="scorecard-assets">{assets.length ? assets.map((asset) => <article key={asset.id}><div><span>{asset.is_active ? "当前生效" : "历史版本"}</span><h3>{asset.name}</h3><p>{asset.description}</p></div><dl><div><dt>版本</dt><dd>v{asset.version}</dd></div><div><dt>指标 / 分箱</dt><dd>{asset.config.indicators.length} / {asset.config.indicators.reduce((sum, item) => sum + item.bins.length, 0)}</dd></div><div><dt>配置哈希</dt><dd><code>{asset.config_hash.slice(0, 12)}</code></dd></div><div><dt>发布人</dt><dd>{asset.created_by_name}</dd></div></dl></article>) : <div className="scorecard-empty"><strong>暂无已发布评分卡</strong><span>提交草稿并由独立复核人批准后，资产将在这里生效。</span></div>}</section>}
  </div>;
}

const calibrationParameterSpecs: Array<{ key: keyof CreditCalibrationCandidate; label: string; unit: string; scale: number; min: number; max: number; step: number; help: string }> = [
  { key: "score_threshold_shift", label: "评级门槛偏移", unit: "分", scale: 1, min: -5, max: 5, step: 1, help: "同时平移 AAA 至 B 的最低分门槛。正数会收紧评级，负数会放宽评级，适合验证风险偏好变化对客户迁移的影响。" },
  { key: "limit_multiplier_scale", label: "等级额度系数", unit: "倍", scale: 1, min: .1, max: 2, step: .05, help: "按比例调整评级对应的额度系数。最终建议额度仍取申请额度、收入、交易规模和强规则上限中的最小值。" },
  { key: "revenue_limit_scale", label: "收入承载额度", unit: "倍", scale: 1, min: .1, max: 2, step: .05, help: "调整营业收入可承载的额度比例，用于避免授信规模超过企业经营体量。" },
  { key: "order_amount_scale", label: "交易规模承载", unit: "倍", scale: 1, min: .1, max: 2, step: .05, help: "调整近 12 个月真实交易规模可承载的额度，仅在内部交易资料完整时参与计算。" },
  { key: "payment_term_scale", label: "账期系数", unit: "倍", scale: 1, min: .5, max: 1.5, step: .05, help: "按比例调整各评级建议账期，强规则仍可把账期进一步收紧或降为 0 天。" },
  { key: "overdue_rate_high", label: "应收逾期率阈值", unit: "%", scale: 100, min: 0, max: 100, step: 1, help: "实际应收逾期率超过该值时触发高风险规则，收紧额度并转人工复核。" },
  { key: "limit_utilization_high", label: "额度使用率阈值", unit: "%", scale: 100, min: 0, max: 100, step: 1, help: "实际额度使用率超过该值时触发限额和关注策略，用于控制敞口集中与透支风险。" },
  { key: "invoice_match_rate_low", label: "发票匹配率下限", unit: "%", scale: 100, min: 0, max: 100, step: 1, help: "发票与交易匹配率低于该值时转人工复核，用于识别贸易背景和数据一致性风险。" },
  { key: "delivery_fulfillment_rate_low", label: "交付达成率下限", unit: "%", scale: 100, min: 0, max: 100, step: 1, help: "交付达成率低于该值时限制准入并收紧账期，用于控制履约风险。" },
];

function CreditCalibrationWorkbench({ snapshots, datasets, currentSubject, canManage, canReview, onOpenModelGovernance, onNotice }: { snapshots: RuleCenterReplaySnapshot[]; datasets: RuleCenterReplayDataset[]; currentSubject: string; canManage: boolean; canReview: boolean; onOpenModelGovernance: (modelKey: string) => void; onNotice: (notice: Notice) => void }) {
  const [config, setConfig] = useState<CreditCalibrationConfig | null>(null);
  const [candidate, setCandidate] = useState<CreditCalibrationCandidate | null>(null);
  const [plans, setPlans] = useState<CreditCalibrationPlan[]>([]);
  const [snapshotId, setSnapshotId] = useState(snapshots[0]?.id ?? "");
  const [positiveLabels, setPositiveLabels] = useState("bad,default,reject");
  const [sampleLimit, setSampleLimit] = useState(500);
  const [result, setResult] = useState<CreditCalibrationResult | null>(null);
  const [planCode, setPlanCode] = useState("CORP_CREDIT_CALIBRATION");
  const [planName, setPlanName] = useState("企业授信稳健校准方案");
  const [businessBasis, setBusinessBasis] = useState("基于固定企业样本校准评级、额度、账期及交易规则阈值");
  const [candidateVersion, setCandidateVersion] = useState("");
  const [changeReason, setChangeReason] = useState("基于固定企业样本校准评级、额度、账期及交易规则阈值");
  const [createdDraft, setCreatedDraft] = useState<{ id: string; candidate_version: string } | null>(null);
  const [reviewComments, setReviewComments] = useState<Record<string, string>>({});
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<CreditCalibrationComparison | null>(null);
  const [busy, setBusy] = useState(false);
  async function refreshPlans() { setPlans(await api.creditCalibrationPlans()); }
  useEffect(() => {
    void Promise.all([api.creditCalibrationConfig(), api.creditCalibrationPlans()]).then(([value, planRows]) => { setConfig(value); setCandidate({ ...value.default_candidate }); setCandidateVersion(`${value.model_version}-CAL1`); setPlans(planRows); }).catch((error: Error) => onNotice({ kind: "error", text: error.message }));
  }, []);
  useEffect(() => { if (!snapshotId && snapshots[0]) setSnapshotId(snapshots[0].id); }, [snapshots, snapshotId]);
  const selectedSnapshot = snapshots.find((item) => item.id === snapshotId);
  const selectedDataset = datasets.find((item) => item.id === selectedSnapshot?.dataset_id);
  async function analyze() {
    if (!candidate || !snapshotId) return;
    setBusy(true);
    try {
      const analysis = await api.analyzeCreditCalibration({ dataset_snapshot_id: snapshotId, template_key: "corporate_credit_v2", positive_labels: csvFields(positiveLabels), sample_limit: sampleLimit, candidate });
      setResult(analysis); setCreatedDraft(null); onNotice({ kind: "success", text: "基线与候选授信方案已完成成对回放" });
    } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  async function savePlan() {
    if (!result) return;
    setBusy(true);
    try {
      const plan = await api.createCreditCalibrationPlan({
        code: planCode.toUpperCase(), name: planName, template_key: "corporate_credit_v2",
        positive_labels: csvFields(positiveLabels), sample_limit: sampleLimit,
        candidate: result.candidate_parameters, business_basis: businessBasis,
      });
      const run = await api.runCreditCalibrationPlan(plan.id, plan.row_version, result.snapshot.id);
      setResult(run.report); await refreshPlans();
      onNotice({ kind: "success", text: `校准方案 ${plan.code} v${plan.version} 已保存并固化运行证据` });
    } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  async function planAction(action: () => Promise<unknown>, message: string) {
    setBusy(true); try { await action(); await refreshPlans(); onNotice({ kind: "success", text: message }); }
    catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  async function reviewPlan(plan: CreditCalibrationPlan, decision: "approve" | "reject") {
    const comment = reviewComments[plan.id]?.trim(); if (!comment || comment.length < 5) return;
    await planAction(() => api.reviewCreditCalibrationPlan(plan.id, plan.row_version, decision, comment), decision === "approve" ? "校准方案已批准，可生成模型草稿" : "校准方案已驳回");
  }
  async function comparePlans() {
    if (comparisonIds.length < 2) return;
    setBusy(true); try { setComparison(await api.compareCreditCalibrationPlans(comparisonIds)); }
    catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  async function createModelChange(plan: CreditCalibrationPlan) {
    if (!plan.latest_valid_run_id) return;
    setBusy(true);
    try {
      const change = await api.createGovernedCreditCalibrationModelChange(plan.id, { expected_row_version: plan.row_version, run_id: plan.latest_valid_run_id, candidate_version: candidateVersion, change_reason: changeReason });
      setCreatedDraft({ id: change.id, candidate_version: change.candidate_version });
      onNotice({ kind: "success", text: `模型变更草稿 ${change.candidate_version} 已生成` });
    } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  function loadAsVersion(plan: CreditCalibrationPlan) {
    setCandidate({ ...plan.candidate }); setPositiveLabels(plan.positive_labels.join(",")); setSampleLimit(plan.sample_limit);
    setPlanCode(plan.code); setPlanName(plan.name); setBusinessBasis(`基于 ${plan.code} v${plan.version} 调整：${plan.business_basis}`);
    setResult(null); setCreatedDraft(null); window.scrollTo({ top: 0, behavior: "smooth" });
  }
  if (!config || !candidate) return <section className="calibration-workbench"><div className="scorecard-empty"><strong>正在读取模型基线</strong><span>固定模型配置后才能开始参数校准。</span></div></section>;
  const hasCandidateChange = result ? calibrationParameterSpecs.some((spec) => result.candidate_parameters[spec.key] !== config.default_candidate[spec.key]) : false;
  return <section className="calibration-workbench">
    <header className="calibration-head"><div><span>CREDIT POLICY CALIBRATION</span><h3>企业评级、额度与账期校准</h3><p>在同一不可变样本快照上成对回放基线与候选方案，观察风险收益和客户迁移。分析结果只读，不直接修改生产模型。</p></div><div><span>{config.model_name}</span><strong>{config.model_version}</strong><code>{config.model_config_hash.slice(0, 16)}</code></div></header>
    <div className="calibration-layout">
      <aside className="calibration-controls">
        <div className="calibration-section-title"><div><b>01</b><strong>固定分析样本</strong></div><FeatureHelp label="不可变快照说明" text="每次分析固定快照版本与内容哈希，确保基线和候选使用完全相同的客户样本，结果可复算、可审计。" /></div>
        <div className="calibration-source-fields">
          <label><span>回放快照 <FeatureHelp label="回放快照说明" text="选择已导入的数据集快照。快照创建后内容不可编辑，避免样本变化导致方案比较失真。" /></span><select aria-label="回放快照" value={snapshotId} onChange={(event) => { setSnapshotId(event.target.value); setResult(null); }}><option value="">请选择快照</option>{snapshots.map((item) => <option key={item.id} value={item.id}>{datasets.find((dataset) => dataset.id === item.dataset_id)?.name ?? "回放数据集"} · v{item.version} · {item.sample_count} 条</option>)}</select></label>
          <label><span>事件标签 <FeatureHelp label="事件标签说明" text="逗号分隔的坏样本标签，如 bad、default、reject。命中这些值的样本视为风险事件；没有标签时平台只输出非监督分布证据。" /></span><input aria-label="事件标签" value={positiveLabels} onChange={(event) => { setPositiveLabels(event.target.value); setResult(null); setCreatedDraft(null); }} placeholder="bad,default,reject" /></label>
          <label><span>样本上限 <FeatureHelp label="样本上限说明" text="限制本次回放最多处理的样本数量。平台会按快照固定顺序取样，不随机抽取。" /></span><input aria-label="样本上限" type="number" min="1" max="1000" value={sampleLimit} onChange={(event) => { setSampleLimit(Number(event.target.value)); setResult(null); setCreatedDraft(null); }} /></label>
        </div>
        {selectedSnapshot && <div className="calibration-snapshot"><div><span>{selectedDataset?.code ?? "DATASET"}</span><strong>{selectedSnapshot.as_of_date}</strong></div><dl><div><dt>样本</dt><dd>{selectedSnapshot.sample_count}</dd></div><div><dt>标签覆盖</dt><dd>{calibrationPct(selectedSnapshot.coverage.label_coverage_rate)}</dd></div><div><dt>字段覆盖</dt><dd>{calibrationPct(selectedSnapshot.coverage.overall_field_coverage_rate)}</dd></div></dl><code>{selectedSnapshot.content_hash.slice(0, 20)}</code></div>}
        <div className="calibration-section-title"><div><b>02</b><strong>候选策略参数</strong></div><button className="text-button" onClick={() => { setCandidate({ ...config.default_candidate }); setResult(null); setCreatedDraft(null); }}>恢复基线</button></div>
        <div className="calibration-parameter-grid">{calibrationParameterSpecs.map((spec) => <label key={spec.key}><span>{spec.label} <FeatureHelp label={`${spec.label}说明`} text={spec.help} /></span><div><input aria-label={spec.label} type="number" min={spec.min} max={spec.max} step={spec.step} value={Number((candidate[spec.key] * spec.scale).toFixed(4))} onChange={(event) => { setCandidate({ ...candidate, [spec.key]: Number(event.target.value) / spec.scale }); setResult(null); setCreatedDraft(null); }} /><i>{spec.unit}</i></div></label>)}</div>
        <details className="calibration-baseline"><summary>查看当前评级、额度与账期基线</summary><div>{config.rating_bands.map((band) => <div key={band.rating}><b>{band.rating}</b><span>{band.score_min} - {band.score_max} 分</span><span>额度 {band.limit_multiplier} 倍</span><span>{band.payment_term_days} 天</span><em>{band.access_strategy}</em></div>)}</div><p>{config.policy_status}</p></details>
        <button className="primary-button calibration-run" disabled={!canManage || busy || !snapshotId || !positiveLabels.trim()} onClick={() => void analyze()}>{busy ? "成对回放中…" : "运行基线 / 候选校准"}</button>
      </aside>
      <main className="calibration-results">{result ? <><CalibrationEvidence result={result} /><section className="calibration-adoption"><header><div><span>03</span><div><strong>保存为校准方案</strong><p>保存后自动固化本次运行；方案需提交并由另一位复核人批准，才能进入模型治理。</p></div></div><FeatureHelp label="版本化方案说明" text="同一方案编码每次保存会自动生成递增版本。参数、样本口径和业务依据共同形成配置哈希，修改后旧运行不会被删除，但会明确失效。" /></header><div className="calibration-plan-fields"><label><span>方案编码</span><input aria-label="校准方案编码" value={planCode} onChange={(event) => setPlanCode(event.target.value.toUpperCase())} /></label><label><span>方案名称</span><input aria-label="校准方案名称" value={planName} onChange={(event) => setPlanName(event.target.value)} /></label><label className="wide"><span>业务依据</span><input aria-label="校准业务依据" value={businessBasis} onChange={(event) => setBusinessBasis(event.target.value)} /></label></div><footer><div><span>待固化证据</span><code>{result.evidence_hash.slice(0, 20)}</code><small>{hasCandidateChange ? "参数已区别于当前基线" : "参数与基线一致，不建议保存"}</small></div><button className="primary-button" disabled={!canManage || busy || !hasCandidateChange || planCode.trim().length < 3 || planName.trim().length < 3 || businessBasis.trim().length < 5} onClick={() => void savePlan()}>{busy ? "保存中…" : "保存方案并固化运行"}</button></footer></section></> : <div className="calibration-empty"><span>CALIBRATION EVIDENCE</span><strong>配置候选参数后运行成对回放</strong><p>结果将展示准入结构、额度敞口、账期、评级迁移和五档门槛敏感性。没有有效标签时，平台会明确降级为非监督证据。</p></div>}</main>
    </div>
    <section className="calibration-plan-workspace">
      <header><div><span>GOVERNED CALIBRATION PLANS</span><h3>方案版本与复核台账</h3><p>比较方案必须使用相同不可变快照和模型基线；无标签运行会保留，但明确标记为非监督证据。</p></div><div><span>{plans.length} 个版本</span><button disabled={busy || comparisonIds.length < 2} onClick={() => void comparePlans()}>比较已选方案（{comparisonIds.length}）</button></div></header>
      {comparison && <CalibrationPlanComparison comparison={comparison} onClose={() => setComparison(null)} />}
      <div className="calibration-plan-list">{plans.length ? plans.map((plan) => {
        const run = plan.runs.find((item) => item.id === plan.latest_valid_run_id);
        const checked = comparisonIds.includes(plan.id);
        return <article key={plan.id} className={plan.status === "approved" ? "approved" : ""}>
          <header><label className="calibration-compare-check"><input type="checkbox" checked={checked} disabled={!run || (!checked && comparisonIds.length >= 5)} onChange={(event) => { setComparison(null); setComparisonIds(event.target.checked ? [...comparisonIds, plan.id] : comparisonIds.filter((id) => id !== plan.id)); }} /><span>加入比较</span></label><div><span className={`status-pill ${plan.status}`}>{calibrationPlanStatus(plan.status)}</span><h4>{plan.name}</h4><small>{plan.code} · v{plan.version} · {plan.created_by_name}</small></div><code>{plan.config_hash.slice(0, 14)}</code></header>
          <div className="calibration-plan-evidence"><div><span>当前运行</span><b>{run ? `${run.report.sample.paired_success_count} 条成对样本` : "尚未运行"}</b><small>{run ? `${run.evidence_level === "supervised" ? "监督证据" : "非监督证据"} · ${run.evidence_hash.slice(0, 12)}` : "选择快照后运行"}</small></div><div><span>组合变化</span><b>{run ? `额度 ${calibrationDelta(run.report.deltas.total_limit, "money")}` : "N/A"}</b><small>{run ? `评级迁移 ${calibrationPct(run.report.migration.rating_change_rate)}` : "没有可用证据"}</small></div><div><span>独立复核</span><b>{plan.reviewed_by_name ?? "待处理"}</b><small>{plan.review_comment ?? "创建人与复核人必须分离"}</small></div></div>
          <p>{plan.business_basis}</p>
          <footer><div><button disabled={busy} onClick={() => loadAsVersion(plan)}>载入为新版本</button>{["draft", "rejected"].includes(plan.status) && canManage && <button disabled={busy || !snapshotId} onClick={() => void planAction(() => api.runCreditCalibrationPlan(plan.id, plan.row_version, snapshotId), "校准运行已固化")} >重新运行</button>}{["draft", "rejected"].includes(plan.status) && canManage && <button className="primary-button" disabled={busy || !plan.latest_valid_run_id} onClick={() => void planAction(() => api.submitCreditCalibrationPlan(plan.id, plan.row_version), "校准方案已提交独立复核")}>提交复核</button>}</div>{plan.status === "pending_review" && canReview && plan.created_by !== currentSubject && <div className="calibration-review"><input aria-label={`复核意见 ${plan.code} v${plan.version}`} value={reviewComments[plan.id] ?? ""} onChange={(event) => setReviewComments({ ...reviewComments, [plan.id]: event.target.value })} placeholder="填写独立复核意见" /><button disabled={(reviewComments[plan.id]?.trim().length ?? 0) < 5} onClick={() => void reviewPlan(plan, "reject")}>驳回</button><button className="primary-button" disabled={(reviewComments[plan.id]?.trim().length ?? 0) < 5} onClick={() => void reviewPlan(plan, "approve")}>批准方案</button></div>}{plan.status === "approved" && canManage && <div className="calibration-model-action"><input aria-label={`模型候选版本 ${plan.code}`} value={candidateVersion} onChange={(event) => setCandidateVersion(event.target.value)} placeholder="模型候选版本" /><input aria-label={`模型变更原因 ${plan.code}`} value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder="模型变更原因" /><button className="primary-button" disabled={busy || !run || candidateVersion.trim().length < 3 || changeReason.trim().length < 5} onClick={() => void createModelChange(plan)}>生成模型草稿</button></div>}</footer>
        </article>;
      }) : <div className="scorecard-empty"><strong>暂无校准方案</strong><span>先完成上方成对回放，再保存首个版本化方案。</span></div>}</div>
      {createdDraft && <div className="calibration-draft-created"><div><span>模型治理草稿已生成</span><strong>{createdDraft.candidate_version}</strong><small>方案审批和运行证据均已绑定，下一步执行 Champion/Challenger 候选比较。</small></div><button onClick={() => onOpenModelGovernance("corporate_credit_v2")}>前往模型治理</button></div>}
    </section>
  </section>;
}

function CalibrationPlanComparison({ comparison, onClose }: { comparison: CreditCalibrationComparison; onClose: () => void }) {
  return <section className={`calibration-plan-comparison ${comparison.comparable ? "pass" : "blocked"}`}><header><div><strong>{comparison.comparable ? "方案具备直接可比性" : "方案不可直接排序"}</strong><span>{comparison.message}</span></div><button aria-label="关闭方案比较" title="关闭方案比较" onClick={onClose}>×</button></header><div className="calibration-comparison-table"><div><b>方案</b><b>自动准入</b><b>拒绝率</b><b>平均额度</b><b>总敞口</b><b>平均账期</b><b>事件敞口</b></div>{comparison.items.map((item) => <div key={item.plan_id}><strong>{item.name}<small>{item.code} v{item.version}</small></strong><span>{calibrationPct(item.metrics.automatic_approval_rate)}</span><span>{calibrationPct(item.metrics.reject_rate)}</span><span>{calibrationMoney(item.metrics.average_limit)}</span><span>{calibrationMoney(item.metrics.total_limit)}</span><span>{item.metrics.average_payment_term_days.toFixed(1)} 天</span><span>{item.metrics.event_exposure_ratio === null ? "N/A" : calibrationPct(item.metrics.event_exposure_ratio)}</span></div>)}</div></section>;
}

function calibrationPlanStatus(status: CreditCalibrationPlan["status"]) { return ({ draft: "草稿", pending_review: "待独立复核", approved: "已批准", rejected: "已驳回" })[status]; }

function CalibrationEvidence({ result }: { result: CreditCalibrationResult }) {
  const metrics: Array<[string, keyof CreditCalibrationResult["baseline"], "pct" | "money" | "days" | "number"]> = [
    ["自动准入率", "automatic_approval_rate", "pct"], ["人工复核率", "manual_review_rate", "pct"], ["拒绝率", "reject_rate", "pct"],
    ["平均额度", "average_limit", "money"], ["额度总敞口", "total_limit", "money"], ["平均账期", "average_payment_term_days", "days"],
    ["事件敞口占比", "event_exposure_ratio", "pct"], ["风险事件限制捕获率", "restricted_event_capture_rate", "pct"],
  ];
  return <>
    <header className="calibration-result-head"><div><span className={result.sample.evidence_level}>{result.sample.evidence_level === "supervised" ? "监督校准证据" : "非监督降级证据"}</span><h3>基线与候选组合影响</h3><p>{result.sample.paired_success_count} 条成对成功 · {result.sample.labeled_count} 条有效标签 · {result.sample.failure_count} 条失败</p></div><div><span>证据哈希</span><code>{result.evidence_hash.slice(0, 20)}</code></div></header>
    {result.warnings.map((warning) => <p className="calibration-warning" key={warning}>{warning}</p>)}
    <div className="calibration-metric-table"><div className="metric-head"><b>指标</b><b>基线</b><b>候选</b><b>变化</b></div>{metrics.map(([label, key, format]) => <div key={key}><span>{label}</span><strong>{calibrationValue(result.baseline[key] as number | null, format)}</strong><strong>{calibrationValue(result.candidate[key] as number | null, format)}</strong><em className={(result.deltas[key] ?? 0) > 0 ? "up" : (result.deltas[key] ?? 0) < 0 ? "down" : "flat"}>{calibrationDelta(result.deltas[key], format)}</em></div>)}</div>
    <div className="calibration-migration-kpis"><div><span>评级迁移</span><b>{result.migration.rating_changed_count}</b><small>{calibrationPct(result.migration.rating_change_rate)} · 上调 {result.migration.rating_improved_count} / 下调 {result.migration.rating_worsened_count}</small></div><div><span>准入迁移</span><b>{result.migration.admission_changed_count}</b><small>{calibrationPct(result.migration.admission_change_rate)} 的客户策略发生变化</small></div><div><span>样本证据</span><b>{result.sample.event_count} / {result.sample.non_event_count}</b><small>事件 / 非事件 · 标签覆盖 {calibrationPct(result.sample.label_coverage_rate)}</small></div></div>
    <div className="calibration-distributions"><DistributionComparison title="评级分布" baseline={result.baseline.rating_distribution} candidate={result.candidate.rating_distribution} /><DistributionComparison title="准入分布" baseline={result.baseline.admission_distribution} candidate={result.candidate.admission_distribution} /><DistributionComparison title="额度分布" baseline={result.baseline.limit_distribution} candidate={result.candidate.limit_distribution} /></div>
    <section className="calibration-sensitivity"><header><div><strong>评级门槛敏感性</strong><span>统一平移门槛后，查看风险收益指标如何变化</span></div><FeatureHelp label="敏感性分析说明" text="固定其他候选参数，只分别测试 -5、-2、0、+2、+5 分门槛偏移。它用于寻找变化拐点，不代表系统自动推荐生产参数。" /></header><div className="sensitivity-table"><div><b>门槛偏移</b><b>自动准入</b><b>人工复核</b><b>拒绝</b><b>平均额度</b><b>事件敞口</b></div>{result.sensitivity.map((row) => <div key={row.score_threshold_shift}><strong>{row.score_threshold_shift > 0 ? "+" : ""}{row.score_threshold_shift} 分</strong><span>{calibrationPct(row.automatic_approval_rate)}</span><span>{calibrationPct(row.manual_review_rate)}</span><span>{calibrationPct(row.reject_rate)}</span><span>{calibrationMoney(row.average_limit)}</span><span>{row.event_exposure_ratio === null ? "N/A" : calibrationPct(row.event_exposure_ratio)}</span></div>)}</div></section>
    <footer className="calibration-governance"><div><span>固定快照</span><code>{result.snapshot.content_hash.slice(0, 16)}</code></div><div><span>基线配置</span><code>{result.model.baseline_config_hash.slice(0, 16)}</code></div><div><span>候选配置</span><code>{result.model.candidate_config_hash.slice(0, 16)}</code></div><p>{result.governance_note}</p></footer>
  </>;
}

function DistributionComparison({ title, baseline, candidate }: { title: string; baseline: CreditCalibrationDistribution[]; candidate: CreditCalibrationDistribution[] }) {
  const keys = Array.from(new Set([...baseline.map((item) => item.key), ...candidate.map((item) => item.key)]));
  return <article><header><strong>{title}</strong><span>基线 / 候选</span></header><div>{keys.map((key) => { const before = baseline.find((item) => item.key === key); const after = candidate.find((item) => item.key === key); return <div className="distribution-row" key={key}><span>{after?.label ?? before?.label ?? key}</span><div><i style={{ width: `${(before?.rate ?? 0) * 100}%` }} /><b style={{ width: `${(after?.rate ?? 0) * 100}%` }} /></div><em>{calibrationPct(before?.rate ?? 0)} / {calibrationPct(after?.rate ?? 0)}</em></div>; })}</div></article>;
}

function FeatureHelp({ label, text }: { label: string; text: string }) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLSpanElement>(null);
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  const [locked, setLocked] = useState(false);
  const [position, setPosition] = useState({ left: 12, top: 12, width: 280 });
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const anchor = buttonRef.current?.getBoundingClientRect();
      if (!anchor) return;
      if (anchor.bottom < 0 || anchor.top > window.innerHeight || anchor.right < 0 || anchor.left > window.innerWidth) {
        setLocked(false);
        setOpen(false);
        return;
      }
      const viewportPadding = 12;
      const gap = 8;
      const width = Math.min(280, window.innerWidth - 24);
      const height = tooltipRef.current?.getBoundingClientRect().height ?? 0;
      const left = Math.min(Math.max(anchor.left + anchor.width / 2 - width / 2, viewportPadding), window.innerWidth - width - viewportPadding);
      const spaceAbove = anchor.top - gap - viewportPadding;
      const spaceBelow = window.innerHeight - anchor.bottom - gap - viewportPadding;
      const placeAbove = spaceAbove >= height || spaceAbove > spaceBelow;
      const desiredTop = placeAbove ? anchor.top - gap - height : anchor.bottom + gap;
      const top = Math.min(Math.max(desiredTop, viewportPadding), Math.max(viewportPadding, window.innerHeight - height - viewportPadding));
      setPosition({ left, top, width });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open]);
  useEffect(() => {
    if (!locked) return;
    const close = () => { setLocked(false); setOpen(false); };
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    document.addEventListener("pointerdown", close, true);
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("pointerdown", close, true); document.removeEventListener("keydown", onKeyDown); };
  }, [locked]);
  return <span className="feature-help">
    <button ref={buttonRef} type="button" aria-label={label} aria-describedby={open ? tooltipId : undefined} aria-expanded={open} title={text}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => { if (!locked) setOpen(false); }} onFocus={() => setOpen(true)} onBlur={() => { if (!locked) setOpen(false); }}
      onClick={(event) => { event.preventDefault(); event.stopPropagation(); const next = !locked; setLocked(next); setOpen(next); }}>?</button>
    {open && createPortal(<span ref={tooltipRef} id={tooltipId} className="feature-help-popover" role="tooltip" style={{ left: position.left, top: position.top, width: position.width }}>{text}</span>, document.body)}
  </span>;
}

function calibrationPct(value: number) { return `${(value * 100).toFixed(1)}%`; }
function calibrationMoney(value: number) { const absolute = Math.abs(value); const prefix = value < 0 ? "-" : ""; return absolute >= 100_000_000 ? `${prefix}${(absolute / 100_000_000).toFixed(2)} 亿` : absolute >= 10_000 ? `${prefix}${(absolute / 10_000).toFixed(1)} 万` : `${prefix}${absolute.toFixed(0)} 元`; }
function calibrationValue(value: number | null, format: "pct" | "money" | "days" | "number") { if (value === null) return "N/A"; if (format === "pct") return calibrationPct(value); if (format === "money") return calibrationMoney(value); if (format === "days") return `${value.toFixed(1)} 天`; return value.toFixed(2); }
function calibrationDelta(value: number | null, format: "pct" | "money" | "days" | "number") { if (value === null) return "N/A"; const prefix = value > 0 ? "+" : ""; if (format === "pct") return `${prefix}${(value * 100).toFixed(1)}pp`; if (format === "money") return `${prefix}${calibrationMoney(value)}`; if (format === "days") return `${prefix}${value.toFixed(1)} 天`; return `${prefix}${value.toFixed(2)}`; }

const monitoringRunDefaults: ScorecardMonitoringRunConfig = { subject_id_field: "id", predicted_probability_field: "predicted_pd", segment_fields: [], sensitive_attribute_fields: [], min_segment_sample_count: 30, classification_threshold: .5, positive_labels: ["bad", "default", "reject"], performance_window_days: 180, maturity_days: 90, min_sample_count: 100, min_event_count: 20, min_non_event_count: 20, exclusion_rules: [] };

const slaEventOptions: Array<[ScorecardMonitoringEventType, string]> = [["gate_failed", "门禁失败"], ["consecutive_deterioration", "连续恶化"], ["evidence_integrity_failed", "证据异常"], ["policy_integrity_failed", "策略异常"], ["scheduled_run_failed", "调度失败"]];

function SlaPolicyWorkspace({ policies, currentSubject, canManage, canReview, onRefresh, onNotice }: { policies: ScorecardMonitoringSlaPolicy[]; currentSubject: string; canManage: boolean; canReview: boolean; onRefresh: () => Promise<void>; onNotice: (notice: Notice) => void }) {
  const [draft, setDraft] = useState(emptySlaPolicy);
  const [editing, setEditing] = useState<ScorecardMonitoringSlaPolicy | null>(null);
  const [reason, setReason] = useState("建立持续验证预警分级 SLA");
  const [reviews, setReviews] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  function load(policy: ScorecardMonitoringSlaPolicy, asNew = false) {
    setEditing(asNew ? null : policy); setDraft({ code: policy.code, name: policy.name, description: policy.description, applicable_scorecard_codes: policy.applicable_scorecard_codes.join(","), applicable_event_types: [...policy.applicable_event_types], is_default: policy.is_default, severity_rules: { critical: { ...policy.severity_rules.critical }, warning: { ...policy.severity_rules.warning } } }); setReason(asNew ? `基于 ${policy.code} v${policy.version} 调整 SLA` : policy.change_reason);
  }
  function reset() { setEditing(null); setDraft(emptySlaPolicy()); setReason("建立持续验证预警分级 SLA"); }
  async function perform(action: () => Promise<unknown>, message: string) { setBusy(true); try { await action(); await onRefresh(); onNotice({ kind: "success", text: message }); } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); } }
  function payload() { return { code: draft.code, name: draft.name, description: draft.description, applicable_scorecard_codes: csvFields(draft.applicable_scorecard_codes).map((item) => item.toUpperCase()), applicable_event_types: draft.applicable_event_types, is_default: draft.is_default, severity_rules: draft.severity_rules }; }
  async function save() { await perform(() => editing ? api.updateScorecardMonitoringSlaPolicy(editing.id, editing.row_version, payload(), reason) : api.createScorecardMonitoringSlaPolicy(payload(), reason), editing ? "SLA 策略草稿已更新" : "SLA 策略草稿已创建"); }
  function setRule(severity: "critical" | "warning", key: "response_hours" | "due_soon_ratio" | "escalation_after_hours", value: number) { setDraft({ ...draft, severity_rules: { ...draft.severity_rules, [severity]: { ...draft.severity_rules[severity], [key]: value } } }); }
  return <section className="sla-policy-workspace">
    {canManage && <div className="sla-policy-editor"><header><div><span>MONITORING SLA GOVERNANCE</span><h3>{editing ? `编辑 ${editing.code} v${editing.version}` : "持续验证 SLA 策略"}</h3><p>按评分卡与预警类型匹配策略，事件创建时固定版本、时限、升级窗口和配置哈希。</p></div><div className="policy-editor-actions"><button disabled={busy} onClick={reset}>{editing ? "取消编辑" : "重置"}</button><button className="primary-button" disabled={busy || draft.code.length < 2 || draft.name.length < 2 || draft.description.length < 5 || reason.length < 5} onClick={() => void save()}>{editing ? "更新策略草稿" : "保存策略草稿"}</button></div></header>
      <div className="sla-policy-fields"><label><span>策略编码</span><input disabled={Boolean(editing)} value={draft.code} onChange={(event) => setDraft({ ...draft, code: event.target.value.toUpperCase() })} /></label><label><span>策略名称</span><input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label><label className="wide"><span>治理说明</span><input value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label><label><span>适用评分卡</span><input disabled={draft.is_default} value={draft.applicable_scorecard_codes} onChange={(event) => setDraft({ ...draft, applicable_scorecard_codes: event.target.value })} placeholder="逗号分隔；留空表示全部" /></label><label className="policy-default"><input type="checkbox" checked={draft.is_default} onChange={(event) => setDraft({ ...draft, is_default: event.target.checked, applicable_scorecard_codes: event.target.checked ? "" : draft.applicable_scorecard_codes, applicable_event_types: event.target.checked ? [] : draft.applicable_event_types })} /><span>机构默认策略</span></label><label className="wide"><span>变更原因</span><input value={reason} onChange={(event) => setReason(event.target.value)} /></label></div>
      <div className="sla-event-scope"><strong>适用预警类型</strong><span>{draft.is_default ? "默认策略覆盖全部类型" : "留空表示全部类型"}</span><div>{slaEventOptions.map(([value, label]) => <label key={value}><input type="checkbox" disabled={draft.is_default} checked={draft.applicable_event_types.includes(value)} onChange={(event) => setDraft({ ...draft, applicable_event_types: event.target.checked ? [...draft.applicable_event_types, value] : draft.applicable_event_types.filter((item) => item !== value) })} />{label}</label>)}</div></div>
      <div className="sla-rule-grid">{(["critical", "warning"] as const).map((severity) => <article key={severity}><header><span className={severity}>{severity === "critical" ? "严重预警" : "一般预警"}</span><strong>{draft.severity_rules[severity].response_hours} 小时处置</strong></header><label><span>响应时限（小时）</span><input type="number" min="1" max="720" value={draft.severity_rules[severity].response_hours} onChange={(event) => setRule(severity, "response_hours", Number(event.target.value))} /></label><label><span>临期比例</span><input type="number" min="0.05" max="0.9" step="0.05" value={draft.severity_rules[severity].due_soon_ratio} onChange={(event) => setRule(severity, "due_soon_ratio", Number(event.target.value))} /></label><label><span>逾期升级（小时）</span><input type="number" min="1" max="168" value={draft.severity_rules[severity].escalation_after_hours} onChange={(event) => setRule(severity, "escalation_after_hours", Number(event.target.value))} /></label></article>)}</div>
    </div>}
    <div className="sla-policy-list">{policies.length ? policies.map((policy) => <article key={policy.id}><header><div><span className={`status-pill ${policy.status}`}>{policyStatusLabel(policy.status)}</span><h3>{policy.name}</h3><small>{policy.code} · v{policy.version} · {policy.created_by_name}</small></div><div className="governance-actions">{policy.status === "draft" && canManage && policy.created_by === currentSubject && <><button disabled={busy} onClick={() => load(policy)}>编辑草稿</button><button className="primary-button" disabled={busy} onClick={() => void perform(() => api.submitScorecardMonitoringSlaPolicy(policy.id, policy.row_version), "SLA 策略已提交独立复核")}>提交复核</button></>}{policy.status === "published" && canManage && <button disabled={busy} onClick={() => load(policy, true)}>创建新版本</button>}{policy.status === "submitted" && canReview && policy.created_by !== currentSubject && <><input aria-label={`SLA 策略复核意见 ${policy.code}`} value={reviews[policy.id] ?? ""} onChange={(event) => setReviews({ ...reviews, [policy.id]: event.target.value })} placeholder="填写独立复核结论" /><button disabled={(reviews[policy.id]?.trim().length ?? 0) < 5} onClick={() => void perform(() => api.reviewScorecardMonitoringSlaPolicy(policy.id, policy.row_version, "reject", reviews[policy.id]), "SLA 策略已驳回")}>驳回</button><button className="primary-button" disabled={(reviews[policy.id]?.trim().length ?? 0) < 5} onClick={() => void perform(() => api.reviewScorecardMonitoringSlaPolicy(policy.id, policy.row_version, "publish", reviews[policy.id]), "SLA 策略已发布")}>批准发布</button></>}</div></header>
      <div className="sla-policy-scope"><div><span>业务范围</span><b>{policy.applicable_scorecard_codes.length ? policy.applicable_scorecard_codes.join("、") : "全部评分卡"}</b><small>{policy.applicable_event_types.length ? policy.applicable_event_types.map(monitoringEventTypeLabel).join("、") : "全部预警类型"}</small></div><div><span>严重预警</span><b>{policy.severity_rules.critical.response_hours}h / +{policy.severity_rules.critical.escalation_after_hours}h</b><small>临期 {(policy.severity_rules.critical.due_soon_ratio * 100).toFixed(0)}%</small></div><div><span>一般预警</span><b>{policy.severity_rules.warning.response_hours}h / +{policy.severity_rules.warning.escalation_after_hours}h</b><small>临期 {(policy.severity_rules.warning.due_soon_ratio * 100).toFixed(0)}%</small></div><div><span>配置证据</span><code>{policy.config_hash.slice(0, 16)}</code><small>{policy.is_default ? policy.is_active ? "当前机构默认" : "默认候选/历史" : "范围策略"}</small></div></div>
    </article>) : <div className="scorecard-empty"><strong>暂无 SLA 策略</strong><span>未发布策略时继续使用兼容内置的 24/72 小时口径。</span></div>}</div>
  </section>;
}

function ScorecardMonitoringWorkbench({ assets, policies, datasets, developmentRuns, plans, events, schedulerHealth, currentSubject, canManage, canReview, onRefresh, onNotice, onOpenRun }: { assets: ScorecardAsset[]; policies: ScorecardValidationPolicy[]; datasets: RuleCenterReplayDataset[]; developmentRuns: ScorecardDevelopmentRun[]; plans: ScorecardMonitoringPlan[]; events: ScorecardMonitoringEvent[]; schedulerHealth: ScorecardMonitoringSchedulerHealth | null; currentSubject: string; canManage: boolean; canReview: boolean; onRefresh: () => Promise<void>; onNotice: (notice: Notice) => void; onOpenRun: (runId: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [recoveryReasons, setRecoveryReasons] = useState<Record<string, string>>({});
  const [eventInputs, setEventInputs] = useState<Record<string, { assignee: string; note: string; runId: string }>>({});
  const [filters, setFilters] = useState<ScorecardMonitoringEventFilters>({});
  const [filteredEvents, setFilteredEvents] = useState<ScorecardMonitoringEvent[]>(events);
  const [savedViews, setSavedViews] = useState<ScorecardMonitoringSavedView[]>([]);
  const [selectedViewId, setSelectedViewId] = useState("");
  const [viewName, setViewName] = useState("");
  const [viewDefault, setViewDefault] = useState(false);
  const [selectedEventIds, setSelectedEventIds] = useState<string[]>([]);
  const [bulkAssignee, setBulkAssignee] = useState("");
  const [bulkReason, setBulkReason] = useState("");
  const [draft, setDraft] = useState({ code: "", name: "", description: "", scorecard_asset_id: "", validation_policy_id: "", training_dataset_id: "", validation_dataset_id: "", oot_dataset_id: "", cadence: "monthly" as "monthly" | "quarterly", timezone_name: "Asia/Shanghai" as "Asia/Shanghai" | "UTC", enabled: true, next_run_at: new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 16), owner: "model-risk-owner", run_config: { ...monitoringRunDefaults }, segment_fields: "", sensitive_attribute_fields: "", positive_labels: "bad,default,reject" });
  useEffect(() => {
    setDraft((current) => ({ ...current, scorecard_asset_id: current.scorecard_asset_id || assets.find((item) => item.is_active)?.id || assets[0]?.id || "", validation_policy_id: current.validation_policy_id || policies.find((item) => item.is_active && item.is_default)?.id || policies.find((item) => item.is_active)?.id || "", training_dataset_id: current.training_dataset_id || datasets[0]?.id || "" }));
  }, [assets, policies, datasets]);
  useEffect(() => {
    let active = true;
    setSavedViews([]); setSelectedViewId(""); setViewName(""); setViewDefault(false); setFilters({}); setSelectedEventIds([]);
    void api.scorecardMonitoringSavedViews().then((rows) => {
      if (!active) return;
      setSavedViews(rows);
      const defaultView = rows.find((item) => item.is_default);
      if (defaultView) { setSelectedViewId(defaultView.id); setViewName(defaultView.name); setViewDefault(true); setFilters(defaultView.filters); }
    }).catch((error: Error) => onNotice({ kind: "error", text: error.message }));
    return () => { active = false; };
  }, [currentSubject]);
  useEffect(() => {
    let active = true;
    void api.scorecardMonitoringEvents(filters).then((rows) => {
      if (!active) return;
      setFilteredEvents(rows);
      const available = new Set(rows.filter((item) => item.status !== "closed").map((item) => item.id));
      setSelectedEventIds((current) => current.filter((id) => available.has(id)));
    }).catch((error: Error) => onNotice({ kind: "error", text: error.message }));
    return () => { active = false; };
  }, [events, filters.status, filters.severity, filters.event_type, filters.assignee, filters.plan_id, filters.scorecard_code, filters.sla_status]);

  async function perform(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    try { await action(); await onRefresh(); onNotice({ kind: "success", text: message }); }
    catch (error) { onNotice({ kind: "error", text: (error as Error).message }); }
    finally { setBusy(false); }
  }
  async function createPlan() {
    await perform(() => api.createScorecardMonitoringPlan({
      code: draft.code, name: draft.name, description: draft.description, scorecard_asset_id: draft.scorecard_asset_id,
      validation_policy_id: draft.validation_policy_id, training_dataset_id: draft.training_dataset_id,
      validation_dataset_id: draft.validation_dataset_id || undefined, oot_dataset_id: draft.oot_dataset_id || undefined,
      cadence: draft.cadence, timezone_name: draft.timezone_name, enabled: draft.enabled,
      next_run_at: new Date(draft.next_run_at).toISOString(), owner: draft.owner,
      run_config: { ...draft.run_config, segment_fields: csvFields(draft.segment_fields), sensitive_attribute_fields: csvFields(draft.sensitive_attribute_fields), positive_labels: csvFields(draft.positive_labels) },
    }), "持续验证计划已创建");
  }
  function planPayload(plan: ScorecardMonitoringPlan, enabled = plan.enabled) {
    return { code: plan.code, name: plan.name, description: plan.description, scorecard_asset_id: plan.scorecard_asset_id, validation_policy_id: plan.validation_policy_id, training_dataset_id: plan.training_dataset_id, validation_dataset_id: plan.validation_dataset_id || undefined, oot_dataset_id: plan.oot_dataset_id || undefined, run_config: plan.run_config, cadence: plan.cadence, timezone_name: plan.timezone_name, enabled, next_run_at: plan.next_run_at, owner: plan.owner };
  }
  async function runPlan(plan: ScorecardMonitoringPlan) {
    setBusy(true);
    try { const result = await api.runScorecardMonitoringPlan(plan.id, plan.row_version); await onRefresh(); onNotice({ kind: "success", text: result.run ? `验证运行已固化，生成 ${result.events.length} 条预警` : "运行失败，已生成调度预警" }); if (result.run) onOpenRun(result.run.id); }
    catch (error) { onNotice({ kind: "error", text: (error as Error).message }); }
    finally { setBusy(false); }
  }
  async function recoverSchedulerRun(runId: string, deadLetter: boolean) {
    const reason = recoveryReasons[runId]?.trim() ?? "";
    if (reason.length < 5) return;
    await perform(
      () => api.retryScorecardMonitoringSchedulerRun(runId, reason),
      deadLetter ? "死信运行已发起人工恢复" : "失败运行已发起受控重试",
    );
  }
  async function eventAction(event: ScorecardMonitoringEvent, action: "assign" | "acknowledge" | "remediate" | "submit_revalidation" | "review_revalidation", decision?: "pass" | "fail") {
    const input = eventInputs[event.id] ?? { assignee: event.assignee ?? "", note: "", runId: "" };
    const payload = {
      expected_row_version: event.row_version, action, assignee: input.assignee || undefined,
      remediation_plan: action === "remediate" ? input.note : undefined,
      remediation_result: action === "submit_revalidation" ? input.note : undefined,
      revalidation_run_id: action === "submit_revalidation" ? input.runId : undefined,
      decision: action === "review_revalidation" ? decision : undefined,
      conclusion: action === "review_revalidation" ? input.note : undefined,
    };
    const messages = { assign: "预警已分派", acknowledge: "预警已确认", remediate: "预警已进入处置", submit_revalidation: "整改已提交独立复验", review_revalidation: decision === "pass" ? "独立复验通过，预警已闭环" : "独立复验未通过，已退回整改" };
    await perform(() => api.actionScorecardMonitoringEvent(event.id, payload), messages[action]);
  }
  function applySavedView(id: string) {
    setSelectedViewId(id);
    const view = savedViews.find((item) => item.id === id);
    setFilters(view?.filters ?? {}); setViewName(view?.name ?? ""); setViewDefault(view?.is_default ?? false); setSelectedEventIds([]);
  }
  async function saveView() {
    const name = viewName.trim();
    if (name.length < 2) return;
    setBusy(true);
    try {
      const selected = savedViews.find((item) => item.id === selectedViewId);
      const saved = selected
        ? await api.updateScorecardMonitoringSavedView(selected.id, selected.row_version, { name, filters, is_default: viewDefault })
        : await api.createScorecardMonitoringSavedView({ name, filters, is_default: viewDefault });
      const rows = await api.scorecardMonitoringSavedViews(); setSavedViews(rows); setSelectedViewId(saved.id);
      onNotice({ kind: "success", text: selected ? "个人视图已更新" : "个人视图已保存" });
    } catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  async function bulkAssign() {
    const targets = filteredEvents.filter((item) => selectedEventIds.includes(item.id) && item.status !== "closed");
    await perform(() => api.bulkAssignScorecardMonitoringEvents(targets.map((item) => ({ event_id: item.id, expected_row_version: item.row_version })), bulkAssignee.trim(), bulkReason.trim()), `已将 ${targets.length} 条预警分派给 ${bulkAssignee.trim()}`);
    setSelectedEventIds([]); setBulkReason("");
  }
  async function exportEvents() {
    setBusy(true);
    try { await api.exportScorecardMonitoringEvents(filters); onNotice({ kind: "success", text: `已导出当前 ${filteredEvents.length} 条筛选结果` }); }
    catch (error) { onNotice({ kind: "error", text: (error as Error).message }); } finally { setBusy(false); }
  }
  const openEvents = events.filter((item) => item.status !== "closed");
  const activePolicyOptions = policies.filter((item) => item.is_active);
  return <div className="scorecard-monitoring-workbench">
    <section className="monitoring-overview"><div><span>CONTINUOUS VALIDATION</span><h3>持续验证与预警处置</h3><p>计划固定评分卡和策略版本，执行时自动选择各数据集最新可用快照，并将异常回链到不可变验证证据。</p></div><dl><div><dt>启用计划</dt><dd>{plans.filter((item) => item.enabled).length}</dd></div><div><dt>待处置预警</dt><dd>{openEvents.length}</dd></div><div><dt>严重预警</dt><dd>{openEvents.filter((item) => item.severity === "critical").length}</dd></div><div><dt>最近失败</dt><dd>{plans.filter((item) => item.last_status === "failed").length}</dd></div></dl><button className="primary-button" disabled={!canManage || busy} onClick={() => void perform(() => api.runDueScorecardMonitoringPlans(), "到期计划扫描已完成")}>扫描到期计划</button></section>
    <section className={`monitoring-scheduler-health ${schedulerHealth?.health ?? "never"}`}>
      <header><div><span>SCHEDULER GOVERNANCE</span><strong>调度健康与失败恢复</strong><p>数据库租约保证多实例单执行，运行台账保留心跳、积压、重试和死信恢复证据。</p></div><b>{monitoringSchedulerHealthLabel(schedulerHealth?.health ?? "never")}</b></header>
      <div className="scheduler-health-metrics">
        <div><span>到期积压</span><strong>{schedulerHealth?.backlog.count ?? 0}</strong><small>{schedulerHealth?.backlog.oldest_due_at ? `最早 ${formatDateTime(schedulerHealth.backlog.oldest_due_at)}` : "无到期计划"}</small></div>
        <div><span>执行租约</span><strong>{monitoringLeaseLabel(schedulerHealth?.lease.status ?? "idle")}</strong><small>{schedulerHealth?.lease.status === "active" ? `${schedulerHealth.lease.actor} · 剩余 ${schedulerHealth.lease.remaining_seconds}s` : "当前无占用"}</small></div>
        <div><span>后台心跳</span><strong>{schedulerHealth?.scheduler.minutes_since_last_run === null || schedulerHealth?.scheduler.minutes_since_last_run === undefined ? "未接入" : `${schedulerHealth.scheduler.minutes_since_last_run} 分钟前`}</strong><small>{schedulerHealth?.scheduler.last_status ? monitoringSchedulerRunStatusLabel(schedulerHealth.scheduler.last_status) : `建议每 ${schedulerHealth?.expected_cadence_minutes ?? 5} 分钟执行`}</small></div>
        <div><span>死信运行</span><strong>{schedulerHealth?.summary.dead_letter ?? 0}</strong><small>失败最多 {schedulerHealth?.max_attempts ?? 3} 次后进入死信</small></div>
      </div>
      <div className="scheduler-run-ledger"><header><strong>最近调度运行</strong><span>{schedulerHealth?.runs.length ?? 0} 条证据</span></header>{schedulerHealth?.runs.length ? schedulerHealth.runs.slice(0, 8).map((run) => <article key={run.id} className={run.status}>
        <div><span>{monitoringSchedulerTriggerLabel(run.trigger_type)} · 第 {run.attempt_number}/{run.max_attempts} 次</span><strong>{monitoringSchedulerRunStatusLabel(run.status)}</strong><code>{run.run_key}</code></div>
        <dl><div><dt>计划</dt><dd>{run.completed_count}/{run.due_count}</dd></div><div><dt>失败</dt><dd>{run.failed_count}</dd></div><div><dt>积压</dt><dd>{run.backlog_before} → {run.backlog_after}</dd></div><div><dt>时间</dt><dd>{formatDateTime(run.started_at)}</dd></div></dl>
        <div className="scheduler-run-action">{run.error_message && <small>{run.error_type} · {run.error_message}</small>}{run.recovery_reason && <small>恢复依据：{run.recovery_reason}</small>}{(run.can_retry || run.can_recover) && <><input aria-label={`调度恢复原因 ${run.id}`} value={recoveryReasons[run.id] ?? ""} onChange={(event) => setRecoveryReasons({ ...recoveryReasons, [run.id]: event.target.value })} placeholder={run.can_recover ? "填写死信人工恢复依据" : "填写失败重试依据"} /><button disabled={!canManage || busy || (recoveryReasons[run.id]?.trim().length ?? 0) < 5} onClick={() => void recoverSchedulerRun(run.id, run.can_recover)}>{run.can_recover ? "人工恢复" : "受控重试"}</button></>}</div>
      </article>) : <div className="scorecard-empty"><strong>暂无调度运行</strong><span>人工扫描或后台周期任务执行后，将在这里形成运行与心跳证据。</span></div>}</div>
    </section>
    <section className="monitoring-plan-builder"><header><div><strong>新建监控计划</strong><span>数据集按执行截面取最新版本，运行证据仍固定具体快照与哈希。</span></div><button className="primary-button" disabled={!canManage || busy || draft.code.length < 2 || draft.name.length < 2 || draft.description.length < 5 || !draft.scorecard_asset_id || !draft.validation_policy_id || !draft.training_dataset_id || draft.owner.length < 2} onClick={() => void createPlan()}>保存计划</button></header><div className="monitoring-plan-fields">
      <label><span>计划编码</span><input value={draft.code} onChange={(event) => setDraft({ ...draft, code: event.target.value.toUpperCase() })} placeholder="SME_SCORE_MONTHLY" /></label>
      <label><span>计划名称</span><input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
      <label className="wide"><span>验证目的</span><input value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
      <label><span>评分卡版本</span><select value={draft.scorecard_asset_id} onChange={(event) => setDraft({ ...draft, scorecard_asset_id: event.target.value })}>{assets.map((item) => <option key={item.id} value={item.id}>{item.code} · v{item.version}</option>)}</select></label>
      <label><span>验证策略版本</span><select value={draft.validation_policy_id} onChange={(event) => setDraft({ ...draft, validation_policy_id: event.target.value })}>{activePolicyOptions.map((item) => <option key={item.id} value={item.id}>{item.code} · v{item.version}</option>)}</select></label>
      <DatasetSelect label="训练数据集" value={draft.training_dataset_id} datasets={datasets} excluded={[]} onChange={(value) => setDraft({ ...draft, training_dataset_id: value })} />
      <DatasetSelect label="验证数据集" value={draft.validation_dataset_id} datasets={datasets} excluded={[draft.training_dataset_id]} optional onChange={(value) => setDraft({ ...draft, validation_dataset_id: value })} />
      <DatasetSelect label="时间外数据集" value={draft.oot_dataset_id} datasets={datasets} excluded={[draft.training_dataset_id, draft.validation_dataset_id]} optional onChange={(value) => setDraft({ ...draft, oot_dataset_id: value })} />
      <label><span>运行频率</span><select value={draft.cadence} onChange={(event) => setDraft({ ...draft, cadence: event.target.value as "monthly" | "quarterly" })}><option value="monthly">每月</option><option value="quarterly">每季度</option></select></label>
      <label><span>下次执行</span><input type="datetime-local" value={draft.next_run_at} onChange={(event) => setDraft({ ...draft, next_run_at: event.target.value })} /></label>
      <label><span>责任人</span><input value={draft.owner} onChange={(event) => setDraft({ ...draft, owner: event.target.value })} /></label>
      <label><span>事件标签</span><input value={draft.positive_labels} onChange={(event) => setDraft({ ...draft, positive_labels: event.target.value })} /></label>
      <label><span>分群字段</span><input value={draft.segment_fields} onChange={(event) => setDraft({ ...draft, segment_fields: event.target.value })} placeholder="region,industry" /></label>
      <label><span>敏感属性字段</span><input value={draft.sensitive_attribute_fields} onChange={(event) => setDraft({ ...draft, sensitive_attribute_fields: event.target.value })} /></label>
    </div></section>
    <section className="monitoring-plan-list"><header><strong>计划台账</strong><span>{plans.length} 个计划</span></header>{plans.length ? plans.map((plan) => <article key={plan.id} className={plan.last_status === "failed" ? "failed" : ""}><header><div><span className={plan.enabled ? "enabled" : "disabled"}>{plan.enabled ? "已启用" : "已暂停"}</span><strong>{plan.name}</strong><code>{plan.code}</code></div><div><button disabled={!canManage || busy} onClick={() => void perform(() => api.updateScorecardMonitoringPlan(plan.id, plan.row_version, planPayload(plan, !plan.enabled)), plan.enabled ? "计划已暂停" : "计划已启用")}>{plan.enabled ? "暂停" : "启用"}</button><button className="primary-button" disabled={!canManage || busy} onClick={() => void runPlan(plan)}>立即运行</button></div></header><div className="monitoring-plan-evidence"><div><span>评分卡</span><b>{plan.scorecard?.code} @ v{plan.scorecard?.version}</b><code>{plan.scorecard?.config_hash.slice(0, 12)}</code></div><div><span>验证策略</span><b>{plan.validation_policy?.code} @ v{plan.validation_policy?.version}</b><small>{plan.validation_policy?.active ? "策略生效" : "策略已失效"}</small></div><div><span>数据选择</span><b>{plan.datasets.training?.code} / {plan.datasets.validation?.code ?? "-"} / {plan.datasets.oot?.code ?? "-"}</b><small>训练 / 验证 / 时间外</small></div><div><span>下次执行</span><b>{formatDateTime(plan.next_run_at)}</b><small>{plan.cadence === "monthly" ? "每月" : "每季度"} · {plan.timezone_name}</small></div><div><span>最近状态</span><b className={plan.last_status ?? "pending"}>{plan.last_status === "completed" ? "执行完成" : plan.last_status === "failed" ? "执行失败" : "尚未执行"}</b><small>{plan.last_error ?? plan.owner}</small></div></div></article>) : <div className="scorecard-empty"><strong>暂无持续验证计划</strong><span>创建计划后可手工运行或由到期扫描批量执行。</span></div>}</section>
    <section className="monitoring-event-ledger"><header><div><strong>预警处置台账</strong><span>门禁、趋势、完整性和调度异常</span></div><b>{filteredEvents.length} 条结果</b></header>
      <div className="monitoring-event-operations">
        <div className="monitoring-view-row"><label><span>个人视图</span><select value={selectedViewId} onChange={(event) => applySavedView(event.target.value)}><option value="">全部预警</option>{savedViews.map((view) => <option key={view.id} value={view.id}>{view.name}{view.is_default ? " · 默认" : ""}</option>)}</select></label><label><span>视图名称</span><input value={viewName} onChange={(event) => { setViewName(event.target.value); if (selectedViewId && event.target.value !== savedViews.find((item) => item.id === selectedViewId)?.name) setSelectedViewId(""); }} placeholder="如：严重逾期待办" /></label><label className="monitoring-default-view"><input type="checkbox" checked={viewDefault} onChange={(event) => setViewDefault(event.target.checked)} /><span>设为默认</span></label><button disabled={busy || viewName.trim().length < 2} onClick={() => void saveView()}>{selectedViewId ? "更新视图" : "保存视图"}</button><button disabled={busy} onClick={() => void exportEvents()}>导出 CSV</button></div>
        <div className="monitoring-filter-grid">
          <label><span>处置状态</span><select value={filters.status ?? ""} onChange={(event) => setFilters({ ...filters, status: event.target.value as ScorecardMonitoringEvent["status"] || undefined })}><option value="">全部状态</option><option value="open">待确认</option><option value="acknowledged">已确认</option><option value="in_remediation">处置中</option><option value="pending_revalidation">待独立复验</option><option value="closed">已关闭</option></select></label>
          <label><span>严重级别</span><select value={filters.severity ?? ""} onChange={(event) => setFilters({ ...filters, severity: event.target.value as ScorecardMonitoringEvent["severity"] || undefined })}><option value="">全部级别</option><option value="critical">严重</option><option value="warning">一般</option></select></label>
          <label><span>预警类型</span><select value={filters.event_type ?? ""} onChange={(event) => setFilters({ ...filters, event_type: event.target.value as ScorecardMonitoringEventType || undefined })}><option value="">全部类型</option>{slaEventOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label><span>责任人</span><select value={filters.assignee ?? ""} onChange={(event) => setFilters({ ...filters, assignee: event.target.value || undefined })}><option value="">全部责任人</option>{Array.from(new Set(events.map((item) => item.assignee).filter(Boolean))).sort().map((value) => <option key={value!} value={value!}>{value}</option>)}</select></label>
          <label><span>评分卡</span><select value={filters.scorecard_code ?? ""} onChange={(event) => setFilters({ ...filters, scorecard_code: event.target.value || undefined })}><option value="">全部评分卡</option>{Array.from(new Set(assets.map((item) => item.code))).sort().map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <label><span>SLA 状态</span><select value={filters.sla_status ?? ""} onChange={(event) => setFilters({ ...filters, sla_status: event.target.value as ScorecardMonitoringEvent["sla_status"] || undefined })}><option value="">全部时限</option><option value="normal">时限正常</option><option value="due_soon">即将超时</option><option value="overdue">已超时</option><option value="escalated">升级督办</option></select></label>
          <button className="secondary-button" disabled={!Object.values(filters).some(Boolean)} onClick={() => { setFilters({}); setSelectedViewId(""); setViewName(""); setViewDefault(false); }}>清除筛选</button>
        </div>
        <div className="monitoring-bulk-row"><label className="monitoring-select-all"><input type="checkbox" checked={filteredEvents.some((item) => item.status !== "closed") && filteredEvents.filter((item) => item.status !== "closed").every((item) => selectedEventIds.includes(item.id))} onChange={(event) => setSelectedEventIds(event.target.checked ? filteredEvents.filter((item) => item.status !== "closed").map((item) => item.id) : [])} /><span>全选当前未关闭结果</span></label><strong>已选 {selectedEventIds.length} 条</strong><input aria-label="批量分派责任人" value={bulkAssignee} onChange={(event) => setBulkAssignee(event.target.value)} placeholder="批量责任人" /><input aria-label="批量分派依据" value={bulkReason} onChange={(event) => setBulkReason(event.target.value)} placeholder="填写分派依据（至少 5 字）" /><button className="primary-button" disabled={!canManage || busy || !selectedEventIds.length || bulkAssignee.trim().length < 2 || bulkReason.trim().length < 5} onClick={() => void bulkAssign()}>批量分派</button></div>
      </div>
      {filteredEvents.length ? filteredEvents.map((event) => {
      const input = eventInputs[event.id] ?? { assignee: event.assignee ?? "", note: "", runId: "" };
      const plan = plans.find((item) => item.id === event.plan_id);
      const eligibleRuns = developmentRuns.filter((run) => run.id !== event.run_id && run.scorecard_asset_id === plan?.scorecard_asset_id && run.validation_policy_id === plan?.validation_policy_id && run.integrity_valid && run.validation_policy_integrity_valid && run.report.validation_gate?.passed);
      const isIndependentReviewer = canReview && currentSubject !== event.remediated_by;
      return <article id={`monitoring-event-${event.id}`} key={event.id} className={`${event.severity} ${event.status} ${selectedEventIds.includes(event.id) ? "selected" : ""}`}>
        <div className="event-main"><label className="event-select"><input type="checkbox" disabled={event.status === "closed"} checked={selectedEventIds.includes(event.id)} onChange={(inputEvent) => setSelectedEventIds(inputEvent.target.checked ? [...selectedEventIds, event.id] : selectedEventIds.filter((id) => id !== event.id))} /><span>{event.status === "closed" ? "已闭环" : "选择"}</span></label><span>{monitoringEventTypeLabel(event.event_type)}</span><strong>{event.title}</strong><p>{event.description}</p><small>{formatDateTime(event.created_at)} · {event.evidence_hash ? `原始证据 ${event.evidence_hash.slice(0, 12)}` : "无运行证据"}</small>{event.revalidation_evidence_hash && <small>复验证据 {event.revalidation_evidence_hash.slice(0, 12)}</small>}</div>
        <div className="event-metric"><span>{event.metric_label ?? "运行状态"}</span><b>{event.metric_value === null ? "N/A" : event.metric_value.toFixed(4)}</b><small>{event.threshold_value === null ? event.severity === "critical" ? "严重" : "警告" : `${event.threshold_operator} ${event.threshold_value}`}</small><i className={`event-sla ${event.sla_status}`}>{monitoringSlaLabel(event.sla_status)}</i><small>截止 {formatDateTime(event.sla_due_at)}{event.escalation_level ? ` · L${event.escalation_level}` : ""}</small><small className={event.sla_policy_integrity_valid ? "policy-valid" : "policy-invalid"}>{event.sla_policy_snapshot?.code ?? "兼容 SLA"} · v{event.sla_policy_snapshot?.version ?? 1}</small></div>
        <div className="event-disposition"><span>{monitoringEventStatusLabel(event.status)}</span>
          {event.status !== "closed" && event.status !== "pending_revalidation" && <input aria-label={`预警责任人 ${event.id}`} value={input.assignee} onChange={(e) => setEventInputs({ ...eventInputs, [event.id]: { ...input, assignee: e.target.value } })} placeholder="责任人" />}
          {event.status !== "closed" && <textarea aria-label={`预警处置说明 ${event.id}`} value={input.note} onChange={(e) => setEventInputs({ ...eventInputs, [event.id]: { ...input, note: e.target.value } })} placeholder={event.status === "pending_revalidation" ? "填写独立复验结论" : event.status === "in_remediation" ? "填写整改结果" : "填写整改计划"} />}
          {event.status === "in_remediation" && <select aria-label={`复验运行 ${event.id}`} value={input.runId} onChange={(e) => setEventInputs({ ...eventInputs, [event.id]: { ...input, runId: e.target.value } })}><option value="">选择门禁通过的新验证运行</option>{eligibleRuns.map((run) => <option key={run.id} value={run.id}>{run.scorecard_code} v{run.scorecard_version} · {formatDateTime(run.created_at)} · {run.evidence_hash.slice(0, 10)}</option>)}</select>}
          <div>{event.status === "open" && <button disabled={!canManage || busy} onClick={() => void eventAction(event, "acknowledge")}>确认</button>}{["open", "acknowledged"].includes(event.status) && <button disabled={!canManage || busy || input.note.trim().length < 5} onClick={() => void eventAction(event, "remediate")}>进入处置</button>}{event.status === "in_remediation" && <button className="primary-button" disabled={!canManage || busy || input.note.trim().length < 5 || !input.runId} onClick={() => void eventAction(event, "submit_revalidation")}>提交复验</button>}{event.status === "pending_revalidation" && <><button disabled={!isIndependentReviewer || busy || input.note.trim().length < 5} onClick={() => void eventAction(event, "review_revalidation", "fail")}>退回整改</button><button className="primary-button" disabled={!isIndependentReviewer || busy || input.note.trim().length < 5} onClick={() => void eventAction(event, "review_revalidation", "pass")}>复验通过</button></>}</div>
          {event.run_id && <button className="link-button" onClick={() => onOpenRun(event.run_id!)}>查看原始证据</button>}{event.revalidation_run_id && <button className="link-button" onClick={() => onOpenRun(event.revalidation_run_id!)}>查看复验证据</button>}
          {event.status === "closed" && <small>{event.revalidated_by_name} · {event.revalidation_conclusion}</small>}
        </div>
      </article>;
    }) : <div className="scorecard-empty"><strong>当前筛选无结果</strong><span>可清除筛选查看全部预警，或运行监控计划生成新的事件。</span></div>}</section>
  </div>;
}

function DatasetSelect({ label, value, datasets, excluded, optional = false, onChange }: { label: string; value: string; datasets: RuleCenterReplayDataset[]; excluded: string[]; optional?: boolean; onChange: (value: string) => void }) { return <label><span>{label}</span><select value={value} onChange={(event) => onChange(event.target.value)}>{optional && <option value="">不配置</option>}{datasets.filter((item) => !excluded.includes(item.id)).map((item) => <option key={item.id} value={item.id}>{item.code} · {item.latest_snapshot ? `v${item.latest_snapshot.version} / ${item.latest_snapshot.as_of_date}` : "暂无快照"}</option>)}</select></label>; }
function monitoringEventTypeLabel(value: ScorecardMonitoringEvent["event_type"]) { return ({ gate_failed: "门禁失败", consecutive_deterioration: "连续恶化", evidence_integrity_failed: "证据异常", policy_integrity_failed: "策略异常", scheduled_run_failed: "调度失败" })[value]; }
function monitoringEventStatusLabel(value: ScorecardMonitoringEvent["status"]) { return ({ open: "待确认", acknowledged: "已确认", in_remediation: "处置中", pending_revalidation: "待独立复验", closed: "已关闭" })[value]; }
function monitoringSlaLabel(value: ScorecardMonitoringEvent["sla_status"]) { return ({ normal: "时限正常", due_soon: "即将超时", overdue: "已超时", escalated: "升级督办" })[value]; }
function monitoringSchedulerHealthLabel(value: ScorecardMonitoringSchedulerHealth["health"]) { return ({ healthy: "调度健康", degraded: "需要关注", blocked: "调度阻断", never: "等待后台心跳" })[value]; }
function monitoringLeaseLabel(value: ScorecardMonitoringSchedulerHealth["lease"]["status"]) { return ({ idle: "空闲", active: "执行中", expired: "租约过期" })[value]; }
function monitoringSchedulerRunStatusLabel(value: string) { return ({ running: "执行中", completed: "已完成", partial_failed: "部分失败", failed: "执行失败", dead_letter: "死信待恢复", skipped: "安全跳过" } as Record<string, string>)[value] ?? value; }
function monitoringSchedulerTriggerLabel(value: string) { return ({ manual: "人工扫描", scheduler: "后台周期", retry: "失败重试", recovery: "死信恢复" } as Record<string, string>)[value] ?? value; }
function formatDateTime(value: string | null) { return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-"; }

const thresholdFields: Array<[keyof ScorecardValidationThresholds, string, number]> = [
  ["min_auc", "最低 AUC", .01], ["min_ks", "最低 KS", .01], ["max_brier", "最高 Brier", .01],
  ["max_score_psi", "最高分数 PSI", .01], ["min_segment_coverage", "最低分群覆盖", .01],
  ["max_event_rate_gap", "最大事件率差", .01], ["max_average_score_gap", "最大平均分差", 1],
  ["max_auc_gap", "最大 AUC 差", .01], ["max_ks_gap", "最大 KS 差", .01],
  ["max_false_positive_rate_gap", "最大 FPR 差", .01], ["max_false_negative_rate_gap", "最大 FNR 差", .01],
];

function ThresholdEditor({ thresholds, onChange }: { thresholds: ScorecardValidationThresholds; onChange: (value: ScorecardValidationThresholds) => void }) {
  return <details className="validation-thresholds" open><summary><div><strong>机构验证门槛</strong><span>AUC、KS、Brier、PSI、覆盖率和群体差异</span></div><b>配置模板</b></summary><div className="threshold-switches">{([['require_validation_snapshot','必须有验证集'],['require_oot_snapshot','必须有时间外集'],['require_probability_evidence','必须有概率证据'],['require_sensitive_attribute_evidence','必须有敏感属性证据']] as Array<[keyof ScorecardValidationThresholds,string]>).map(([key,label]) => <label key={key}><input type="checkbox" checked={Boolean(thresholds[key])} onChange={(event) => onChange({ ...thresholds, [key]: event.target.checked })} />{label}</label>)}</div><div className="threshold-fields">{thresholdFields.map(([key,label,step]) => <label key={key}><span>{label}</span><input type="number" min="0" step={step} value={Number(thresholds[key])} onChange={(event) => onChange({ ...thresholds, [key]: Number(event.target.value) })} /></label>)}</div></details>;
}

function PolicyThresholdSummary({ thresholds }: { thresholds: ScorecardValidationThresholds }) {
  const requirements = [["验证集", thresholds.require_validation_snapshot], ["时间外集", thresholds.require_oot_snapshot], ["概率证据", thresholds.require_probability_evidence], ["敏感属性", thresholds.require_sensitive_attribute_evidence]] as const;
  return <div className="policy-threshold-summary"><div className="policy-requirements">{requirements.map(([label, required]) => <span className={required ? "required" : "optional"} key={label}><b>{required ? "必需" : "可选"}</b>{label}</span>)}</div><dl>{thresholdFields.map(([key,label]) => <div key={key}><dt>{label}</dt><dd>{Number(thresholds[key]).toFixed(key === "max_average_score_gap" ? 1 : 2)}</dd></div>)}</dl></div>;
}

const trendMetricOptions: Array<{ key: ScorecardDevelopmentTrendMetricKey; label: string; short: string; direction: "min" | "max" }> = [
  { key: "validation_auc", label: "验证集 AUC", short: "AUC", direction: "min" },
  { key: "validation_ks", label: "验证集 KS", short: "KS", direction: "min" },
  { key: "validation_brier", label: "验证集 Brier", short: "Brier", direction: "max" },
  { key: "validation_score_psi", label: "验证集分数 PSI", short: "PSI", direction: "max" },
  { key: "oot_auc", label: "OOT AUC", short: "AUC", direction: "min" },
  { key: "oot_ks", label: "OOT KS", short: "KS", direction: "min" },
  { key: "oot_brier", label: "OOT Brier", short: "Brier", direction: "max" },
  { key: "oot_score_psi", label: "OOT 分数 PSI", short: "PSI", direction: "max" },
  { key: "max_group_score_psi", label: "最大群体分数 PSI", short: "群体 PSI", direction: "max" },
  { key: "max_event_rate_gap", label: "最大事件率差", short: "事件率差", direction: "max" },
  { key: "max_average_score_gap", label: "最大平均分差", short: "平均分差", direction: "max" },
];

function PortfolioStabilityDashboard({ portfolio, onOpenRun, onOpenMonitoring }: { portfolio: ScorecardPortfolioStability | null; onOpenRun: (runId: string) => void; onOpenMonitoring: () => void }) {
  const [status, setStatus] = useState<ScorecardPortfolioStatus | "all">("all");
  const [query, setQuery] = useState("");
  if (!portfolio) return <div className="scorecard-empty"><strong>正在汇总组合稳定性</strong><span>正在关联评分卡、固定运行、监控计划与预警证据。</span></div>;
  const rows = portfolio.rows.filter((row) => (status === "all" || row.status === status) && `${row.scorecard_code} ${row.scorecard_name}`.toLowerCase().includes(query.trim().toLowerCase()));
  const statusOptions: Array<[ScorecardPortfolioStatus | "all", string, number]> = [
    ["all", "全部", portfolio.summary.scorecard_count], ["healthy", "健康", portfolio.summary.healthy_count],
    ["attention", "关注", portfolio.summary.attention_count], ["blocked", "阻断", portfolio.summary.blocked_count],
    ["invalid", "证据异常", portfolio.summary.invalid_count], ["unmonitored", "未纳管", portfolio.summary.unmonitored_count],
  ];
  return <section className="portfolio-stability-dashboard">
    <header className="portfolio-head"><div><span>PORTFOLIO STABILITY</span><h3>评分卡组合稳定性</h3><p>统一观察最新门禁、性能漂移、证据完整性、持续验证覆盖和预警处置。</p></div><div><strong>{portfolio.summary.healthy_count} / {portfolio.summary.scorecard_count}</strong><span>当前健康</span><small>更新于 {new Date(portfolio.generated_at).toLocaleString("zh-CN")}</small></div></header>
    <div className="portfolio-kpis"><div className="healthy"><span>健康运行</span><strong>{portfolio.summary.healthy_count}</strong><small>门禁通过且无异常</small></div><div className="attention"><span>待关注</span><strong>{portfolio.summary.attention_count}</strong><small>临界指标或运营预警</small></div><div className="blocked"><span>门禁阻断</span><strong>{portfolio.summary.blocked_count}</strong><small>不满足机构上线门槛</small></div><div className="invalid"><span>证据异常</span><strong>{portfolio.summary.invalid_count}</strong><small>哈希或策略完整性异常</small></div><div className="unmonitored"><span>未纳管</span><strong>{portfolio.summary.unmonitored_count}</strong><small>缺运行或持续验证计划</small></div><div><span>开放 / 逾期预警</span><strong>{portfolio.summary.open_event_count} / {portfolio.summary.overdue_event_count}</strong><small>{portfolio.summary.enabled_plan_count} 个启用计划</small></div></div>
    <div className="portfolio-toolbar"><div className="segmented-control" aria-label="组合状态筛选">{statusOptions.map(([value, label, count]) => <button className={status === value ? "active" : ""} onClick={() => setStatus(value)} key={value}>{label}<span>{count}</span></button>)}</div><input aria-label="搜索评分卡组合" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索评分卡编码或名称" /></div>
    <div className="portfolio-table"><div className="portfolio-table-head"><b>评分卡 / 状态</b><b>验证 / OOT 性能</b><b>稳定性</b><b>监控覆盖</b><b>预警</b><b>操作</b></div>{rows.map((row) => <div className={`portfolio-row ${row.status}`} key={row.scorecard_code}>
      <div className="portfolio-identity"><span className={`portfolio-status ${row.status}`}>{portfolioStatusLabel(row.status)}</span><strong>{row.scorecard_name}</strong><code>{row.scorecard_code} · v{row.latest_version ?? "-"}</code><small>{row.status_reason}</small></div>
      <div className="stability-metrics"><span>AUC <b>{metric(row.metrics.validation_auc)} / {metric(row.metrics.oot_auc)}</b><i>{metricDelta(row.deltas.oot_auc)}</i></span><span>KS <b>{metric(row.metrics.validation_ks)} / {metric(row.metrics.oot_ks)}</b><i>{metricDelta(row.deltas.oot_ks)}</i></span><span>Brier <b>{metric(row.metrics.validation_brier)} / {metric(row.metrics.oot_brier)}</b><i>{metricDelta(row.deltas.oot_brier)}</i></span></div>
      <div className="stability-metrics"><span>验证 PSI <b className={row.metric_health.validation_score_psi?.status}>{metric(row.metrics.validation_score_psi)}</b><i>{metricDelta(row.deltas.validation_score_psi)}</i></span><span>OOT PSI <b className={row.metric_health.oot_score_psi?.status}>{metric(row.metrics.oot_score_psi)}</b><i>{metricDelta(row.deltas.oot_score_psi)}</i></span><span>最大分群 PSI <b className={row.metric_health.max_group_score_psi?.status}>{metric(row.metrics.max_group_score_psi)}</b><i>{row.threshold_signal_count} 项临界/超限</i></span></div>
      <div className="portfolio-monitoring"><strong>{row.monitoring.enabled_plan_count} / {row.monitoring.plan_count} 个计划启用</strong><span>{row.monitoring.failed_plan_count ? `${row.monitoring.failed_plan_count} 个最近运行失败` : "最近运行无失败"}</span><small>{row.monitoring.next_run_at ? `下次 ${new Date(row.monitoring.next_run_at).toLocaleDateString("zh-CN")}` : "未安排下次运行"}</small></div>
      <div className="portfolio-events"><strong>{row.open_events.total}</strong><span>严重 {row.open_events.critical} · 一般 {row.open_events.warning}</span><small>逾期 {row.open_events.overdue} · 临期 {row.open_events.due_soon}</small></div>
      <div className="portfolio-actions">{row.latest_run_id && <button className="link-button" onClick={() => onOpenRun(row.latest_run_id!)}>验证证据</button>}<button className="link-button" onClick={onOpenMonitoring}>预警台账</button></div>
    </div>)}{!rows.length && <div className="scorecard-empty"><strong>当前筛选无评分卡</strong><span>调整组合状态或搜索条件。</span></div>}</div>
  </section>;
}

function portfolioStatusLabel(status: ScorecardPortfolioStatus) { return ({ healthy: "健康", attention: "关注", blocked: "门禁阻断", invalid: "证据异常", unmonitored: "未纳管" })[status]; }
function metricDelta(value: number | null | undefined) { return value === null || value === undefined ? "较前次 N/A" : `较前次 ${value > 0 ? "+" : ""}${value.toFixed(4)}`; }

function DevelopmentTrendDashboard({ trends, onOpenRun }: { trends: ScorecardDevelopmentTrends | null; onOpenRun: (runId: string) => void }) {
  const [scorecardCode, setScorecardCode] = useState("");
  const [metricKey, setMetricKey] = useState<ScorecardDevelopmentTrendMetricKey>("oot_score_psi");
  const selectedCode = scorecardCode || trends?.series[0]?.scorecard_code || "";
  const series = trends?.series.find((item) => item.scorecard_code === selectedCode);
  const metricMeta = trendMetricOptions.find((item) => item.key === metricKey)!;
  const points = series?.points ?? [];
  const measured = points.filter((point) => point.metrics[metricKey] !== null);
  const latest = points.at(-1);
  const latestMeasured = measured.at(-1);
  const previousMeasured = measured.at(-2);
  const latestValue = latestMeasured?.metrics[metricKey] ?? null;
  const previousValue = previousMeasured?.metrics[metricKey] ?? null;
  const delta = latestValue !== null && previousValue !== null ? latestValue - previousValue : null;
  if (!trends?.series.length) return <div className="scorecard-empty trend-empty"><strong>暂无可形成趋势的验证运行</strong><span>完成至少一次固定开发验证后，平台会按评分卡和数据截面形成持续证据。</span></div>;
  return <section className="development-trend-dashboard">
    <header className="trend-dashboard-head"><div><span>CONTINUOUS VALIDATION</span><h3>跨运行历史趋势</h3><p>按固定评分卡、策略版本和数据截面观察性能、稳定性与群体差异。</p></div><div className="trend-filters"><label><span>评分卡</span><select aria-label="趋势评分卡" value={selectedCode} onChange={(event) => setScorecardCode(event.target.value)}>{trends.series.map((item) => <option key={item.scorecard_code} value={item.scorecard_code}>{item.scorecard_code} · {item.point_count} 次运行</option>)}</select></label><label><span>监控指标</span><select aria-label="趋势监控指标" value={metricKey} onChange={(event) => setMetricKey(event.target.value as ScorecardDevelopmentTrendMetricKey)}>{trendMetricOptions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label></div></header>
    <div className="trend-kpis"><div><span>固定运行</span><strong>{series?.point_count ?? 0}</strong><small>覆盖版本 {(series?.scorecard_versions ?? []).map((version) => `v${version}`).join(" / ")}</small></div><div className={latest?.status ?? "legacy"}><span>最新门禁</span><strong>{trendStatusLabel(latest?.status)}</strong><small>{latest?.gate_summary ?? "历史运行未配置门禁"}</small></div><div><span>门禁通过率</span><strong>{series?.pass_rate === null || series?.pass_rate === undefined ? "N/A" : `${(series.pass_rate * 100).toFixed(1)}%`}</strong><small>仅统计可复算且具有门禁的运行</small></div><div><span>最新 {metricMeta.short}</span><strong>{metric(latestValue)}</strong><small>{delta === null ? "暂无可比较前序点" : `较前次 ${delta > 0 ? "+" : ""}${delta.toFixed(4)}`}</small></div><div className={(series?.points.filter((point) => point.status === "invalid").length ?? 0) ? "invalid" : "pass"}><span>完整性异常</span><strong>{series?.points.filter((point) => point.status === "invalid").length ?? 0}</strong><small>异常证据不进入指标曲线</small></div></div>
    <div className="trend-chart-panel"><header><div><strong>{metricMeta.label}</strong><span>{metricMeta.direction === "min" ? "不得低于策略门槛" : "不得高于策略门槛"}</span></div><div className="trend-legend"><span><i className="actual" />实际值</span><span><i className="threshold" />策略门槛</span></div></header><TrendLineChart points={points} metricKey={metricKey} /></div>
    <div className="trend-run-table"><div className="trend-run-head"><b>数据截面</b><b>评分卡 / 策略</b><b>{metricMeta.short}</b><b>门禁 / 复核</b><b>证据</b></div>{[...points].reverse().slice(0, 12).map((point) => <div className={`trend-run-row ${point.status}`} key={point.run_id}><span>{trendPointDate(point)}<small>{point.created_at ? new Date(point.created_at).toLocaleDateString("zh-CN") : ""}</small></span><span><strong>{point.scorecard_code} · v{point.scorecard_version}</strong><small>{point.validation_policy ? `${point.validation_policy.code} · v${point.validation_policy.version}` : "兼容单次门槛"}</small></span><span><strong>{metric(point.metrics[metricKey])}</strong><small>门槛 {metric(point.thresholds[metricKey])}</small></span><span><b>{trendStatusLabel(point.status)}</b><small>{reviewStatusLabel(point.review_status)}</small></span><button className="link-button" onClick={() => onOpenRun(point.run_id)}>查看证据</button></div>)}</div>
  </section>;
}

function TrendLineChart({ points, metricKey }: { points: NonNullable<ScorecardDevelopmentTrends["series"][number]>["points"]; metricKey: ScorecardDevelopmentTrendMetricKey }) {
  const width = 760, height = 250, left = 52, right = 18, top = 20, bottom = 42;
  const values = points.flatMap((point) => [point.metrics[metricKey], point.thresholds[metricKey]]).filter((value): value is number => value !== null);
  if (!values.length) return <div className="trend-chart-empty"><strong>该指标暂无可测试数据</strong><span>不可测试或完整性异常的运行不会生成趋势点。</span></div>;
  const rawMin = Math.min(...values), rawMax = Math.max(...values), padding = Math.max((rawMax - rawMin) * .18, Math.abs(rawMax || 1) * .08, .02);
  const minimum = Math.max(0, rawMin - padding), maximum = rawMax + padding;
  const x = (index: number) => left + (points.length === 1 ? (width - left - right) / 2 : index * (width - left - right) / (points.length - 1));
  const y = (value: number) => top + (maximum - value) * (height - top - bottom) / Math.max(maximum - minimum, .0001);
  const pathFor = (key: "metrics" | "thresholds") => { let open = false; return points.reduce((path, point, index) => { const value = point[key][metricKey]; if (value === null) { open = false; return path; } const next = `${open ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`; open = true; return `${path}${next}`; }, ""); };
  const labelEvery = Math.max(1, Math.ceil(points.length / 6));
  return <div className="trend-chart-scroll"><svg className="trend-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${trendMetricOptions.find((item) => item.key === metricKey)?.label}历史趋势`}>
    {[0, .25, .5, .75, 1].map((ratio) => { const value = maximum - (maximum - minimum) * ratio; const position = y(value); return <g key={ratio}><line className="grid" x1={left} x2={width - right} y1={position} y2={position} /><text x={left - 8} y={position + 4} textAnchor="end">{value.toFixed(value >= 10 ? 1 : 3)}</text></g>; })}
    <path className="threshold-line" d={pathFor("thresholds")} /><path className="actual-line" d={pathFor("metrics")} />
    {points.map((point, index) => point.metrics[metricKey] === null ? null : <g key={point.run_id}><circle className={`trend-point ${point.status}`} cx={x(index)} cy={y(point.metrics[metricKey]!)} r="5"><title>{trendPointDate(point)} · {point.metrics[metricKey]!.toFixed(4)} · {trendStatusLabel(point.status)}</title></circle>{(index % labelEvery === 0 || index === points.length - 1) && <text className="x-label" x={x(index)} y={height - 14} textAnchor="middle">{trendPointDate(point).slice(5)}</text>}</g>)}
  </svg></div>;
}

function trendPointDate(point: ScorecardDevelopmentTrends["series"][number]["points"][number]) { return point.snapshot_dates.oot ?? point.snapshot_dates.validation ?? point.snapshot_dates.training ?? point.created_at?.slice(0, 10) ?? "未知截面"; }
function trendStatusLabel(status?: "pass" | "block" | "invalid" | "legacy") { return ({ pass: "PASS", block: "BLOCK", invalid: "完整性异常", legacy: "历史证据" } as const)[status ?? "legacy"]; }

function DevelopmentPerformance({ run }: { run: ScorecardDevelopmentRun }) {
  const performance = run.report.performance;
  if (!performance) return null;
  const splits = [
    ["training", "训练集"],
    ["validation", "验证集"],
    ["oot", "时间外集"],
  ] as const;
  return <section className="development-performance">
    <header><div><strong>模型性能与稳定性</strong><span>固定 0-100 分数区间；验证集与时间外集 PSI 均相对训练集计算</span></div><span className={run.report.split_evidence?.leakage_passed ? "pass" : "blocked"}>{run.report.split_evidence?.leakage_passed ? `主体泄漏检查通过 · ${run.report.split_evidence.subject_id_field}` : "主体泄漏检查不可用"}</span></header>
    <div className="development-performance-grid">
      {splits.map(([key, label]) => { const item = performance[key]; return <div key={key} className={!item ? "unavailable" : ""}><h4>{label}</h4>{item ? <dl><div><dt>有效样本</dt><dd>{item.sample_count}</dd></div><div><dt>AUC</dt><dd>{metric(item.auc)}</dd></div><div><dt>KS</dt><dd>{metric(item.ks)}</dd></div><div><dt>Brier</dt><dd>{metric(item.brier)}</dd></div><div><dt>概率覆盖</dt><dd>{`${(item.probability_coverage_rate * 100).toFixed(1)}%`}</dd></div><div><dt>分数 PSI</dt><dd>{metric(item.score_psi)}</dd></div></dl> : <p>未固定该集合快照</p>}</div>; })}
    </div>
  </section>;
}

const developmentSplits = [
  ["training", "训练集", "#3f6668"],
  ["validation", "验证集", "#b47a24"],
  ["oot", "时间外集", "#a64d45"],
] as const;

function DevelopmentEvidenceVisuals({ run }: { run: ScorecardDevelopmentRun }) {
  const [view, setView] = useState<"distribution" | "calibration" | "drift">("distribution");
  const performance = run.report.performance;
  if (!performance) return null;
  const hasCalibration = developmentSplits.some(([key]) => performance[key]?.calibration.some((point) => point.predicted_rate !== null && point.actual_rate !== null));
  const hasDrift = Boolean(run.report.fairness?.segment_fields.length);
  const activeView = view === "calibration" && !hasCalibration ? "distribution" : view === "drift" && !hasDrift ? "distribution" : view;
  return <section className="development-evidence-visuals">
    <header><div><strong>验证证据图谱</strong><span>固定快照对比 · 图形结论与结构化门禁使用同一证据</span></div><div className="evidence-view-tabs" role="tablist" aria-label="验证证据视图"><button className={activeView === "distribution" ? "active" : ""} role="tab" aria-selected={activeView === "distribution"} onClick={() => setView("distribution")}>分数分布</button><button className={activeView === "calibration" ? "active" : ""} role="tab" aria-selected={activeView === "calibration"} disabled={!hasCalibration} onClick={() => setView("calibration")}>概率校准</button><button className={activeView === "drift" ? "active" : ""} role="tab" aria-selected={activeView === "drift"} disabled={!hasDrift} onClick={() => setView("drift")}>分群漂移</button></div></header>
    {activeView === "distribution" && <ScoreDistributionVisual run={run} />}
    {activeView === "calibration" && <CalibrationVisual run={run} />}
    {activeView === "drift" && <SegmentDriftVisual run={run} />}
  </section>;
}

function ScoreDistributionVisual({ run }: { run: ScorecardDevelopmentRun }) {
  const performance = run.report.performance!;
  const buckets = [...new Set(developmentSplits.flatMap(([key]) => Object.keys(performance[key]?.score_distribution ?? {})))].sort((left, right) => Number(left.split("-")[0]) - Number(right.split("-")[0]));
  const totals = Object.fromEntries(developmentSplits.map(([key]) => [key, Object.values(performance[key]?.score_distribution ?? {}).reduce((sum, count) => sum + count, 0)])) as Record<(typeof developmentSplits)[number][0], number>;
  const maxShare = Math.max(0.01, ...developmentSplits.flatMap(([key]) => buckets.map((bucket) => (performance[key]?.score_distribution[bucket] ?? 0) / Math.max(totals[key], 1))));
  return <div className="score-distribution-visual"><div className="visual-summary"><div><strong>0-100 标准分分布</strong><span>各集合按自身有效样本归一，便于比较分布形态</span></div>{developmentSplits.map(([key, label, color]) => { const item = performance[key]; const check = run.report.validation_gate?.checks.find((candidate) => candidate.key === `${key}.score_psi`); return <div key={key}><i style={{ backgroundColor: color }} /><span>{label}</span><b className={check && !check.passed ? "blocked" : ""}>{key === "training" ? "基准" : `PSI ${metric(item?.score_psi)}`}</b></div>; })}</div><div className="score-distribution-scroll"><div className="score-distribution-plot" role="img" aria-label="训练集、验证集和时间外集标准分分布对比"><div className="plot-head"><b>分数区间</b>{developmentSplits.map(([key, label]) => <b key={key}>{label}</b>)}</div>{buckets.map((bucket) => <div className="plot-row" key={bucket}><strong>{bucket}</strong>{developmentSplits.map(([key, label, color]) => { const count = performance[key]?.score_distribution[bucket] ?? 0; const share = count / Math.max(totals[key], 1); return <div key={key} title={`${label} ${bucket}：${count} 条，占比 ${(share * 100).toFixed(1)}%`}><span style={{ width: `${share / maxShare * 100}%`, backgroundColor: color }} /><small>{count} · {(share * 100).toFixed(1)}%</small></div>; })}</div>)}</div></div></div>;
}

function CalibrationVisual({ run }: { run: ScorecardDevelopmentRun }) {
  const performance = run.report.performance!;
  return <div className="calibration-visual"><div className="visual-summary"><div><strong>预测概率校准</strong><span>横轴预测事件率，纵轴实际事件率；虚线为完全校准</span></div></div><div className="calibration-grid">{developmentSplits.map(([key, label, color]) => { const item = performance[key]; const points = (item?.calibration ?? []).filter((point): point is typeof point & { predicted_rate: number; actual_rate: number } => point.predicted_rate !== null && point.actual_rate !== null); const check = run.report.validation_gate?.checks.find((candidate) => candidate.key === `${key}.brier`); const polyline = points.map((point) => `${20 + point.predicted_rate * 260},${280 - point.actual_rate * 260}`).join(" "); return <article key={key} className={!points.length ? "unavailable" : ""}><header><div><i style={{ backgroundColor: color }} /><strong>{label}</strong></div><span className={check && !check.passed ? "blocked" : ""}>Brier {metric(item?.brier)}</span></header>{points.length ? <svg viewBox="0 0 300 300" role="img" aria-label={`${label}预测概率校准曲线`}><line className="axis" x1="20" y1="280" x2="280" y2="280" /><line className="axis" x1="20" y1="20" x2="20" y2="280" /><line className="perfect" x1="20" y1="280" x2="280" y2="20" /><polyline fill="none" stroke={color} strokeWidth="4" strokeLinejoin="round" points={polyline} />{points.map((point) => <circle key={point.range} cx={20 + point.predicted_rate * 260} cy={280 - point.actual_rate * 260} r="6" fill={color}><title>{point.range}：预测 {rate(point.predicted_rate)}，实际 {rate(point.actual_rate)}，样本 {point.sample_count}</title></circle>)}<text x="150" y="298">预测事件率</text><text transform="translate(9 160) rotate(-90)">实际事件率</text></svg> : <p>当前集合缺少可测试的概率证据</p>}</article>; })}</div></div>;
}

function SegmentDriftVisual({ run }: { run: ScorecardDevelopmentRun }) {
  const fairness = run.report.fairness;
  if (!fairness) return null;
  const gate = run.report.validation_gate;
  const comparisonSplits = ["validation", "oot"] as const;
  return <div className="segment-drift-visual">
    <div className="visual-summary"><div><strong>分群稳定性矩阵</strong><span>构成 PSI 为诊断证据；群体分数 PSI 直接引用机构门槛状态</span></div><div className="drift-legend"><span><i className="stable" />通过</span><span><i className="blocked" />超限</span><span><i className="untestable" />不可测试</span></div></div>
    <div className="drift-field-list">{fairness.segment_fields.map((field) => {
      const trainingGroups = (fairness.splits.training?.[field]?.groups ?? []).map((group) => group.group);
      const comparisonGroups = comparisonSplits.flatMap((split) => (fairness.splits[split]?.[field]?.groups ?? []).map((group) => group.group));
      const groups = [...new Set([...trainingGroups, ...comparisonGroups])];
      return <article key={field}>
        <header><div><strong>{field}</strong><span>{fairness.sensitive_attribute_fields.includes(field) ? "敏感属性" : "业务分群"}</span></div>{comparisonSplits.map((split) => <span key={split}>{split === "validation" ? "验证构成" : "OOT 构成"}<b>{metric(fairness.splits[split]?.[field]?.population_psi)}</b></span>)}</header>
        <div className="drift-matrix"><div className="drift-head"><b>群体</b><b>验证集分数 PSI</b><b>时间外集分数 PSI</b></div>{groups.length ? groups.map((groupName) => <div className="drift-row" key={groupName}><strong>{groupName}</strong>{comparisonSplits.map((split) => {
          const group = fairness.splits[split]?.[field]?.groups.find((candidate) => candidate.group === groupName);
          const check = gate?.checks.find((candidate) => candidate.key === `${split}.${field}.${groupName}.score_psi`);
          const className = group?.score_psi === null || group?.score_psi === undefined ? "untestable" : check && !check.passed ? "blocked" : "stable";
          return <div className={className} key={split} title={`${split === "validation" ? "验证集" : "时间外集"} / ${field} / ${groupName} · ${check?.detail ?? "无独立门禁检查"}`}><b>{metric(group?.score_psi)}</b><small>{check ? check.passed ? `通过 ≤ ${metric(check.threshold)}` : `超限 > ${metric(check.threshold)}` : "诊断证据"}</small></div>;
        })}</div>) : <div className="drift-empty"><strong>属性不可测试</strong><span>当前固定快照没有可比较群体</span></div>}</div>
      </article>;
    })}</div>
  </div>;
}

function DevelopmentValidationGate({ run }: { run: ScorecardDevelopmentRun }) {
  const gate = run.report.validation_gate;
  if (!gate) return null;
  return <section className={`development-validation-gate ${gate.passed ? "pass" : "blocked"}`}><header><div><span>INSTITUTION VALIDATION GATE</span><strong>{gate.passed ? "PASS" : "BLOCK"}</strong><small>{gate.summary}</small></div><b>{gate.checks.filter((item) => item.passed).length} / {gate.checks.length} 项通过</b></header>{gate.violations.length > 0 && <div className="validation-violations">{gate.violations.map((item) => <div key={item.key}><strong>{item.scope} · {item.label}</strong><span>{item.testable ? `实际 ${metric(item.actual)} ${item.operator} 门槛 ${metric(item.threshold)}` : item.detail}</span></div>)}</div>}<details><summary>查看全部门槛检查</summary><div className="validation-check-list">{gate.checks.map((item) => <span className={item.passed ? "pass" : "blocked"} key={item.key}><b>{item.passed ? "通过" : "阻断"}</b>{item.scope} · {item.label}<small>{item.testable ? `${metric(item.actual)} ${item.operator} ${metric(item.threshold)}` : "N/A"}</small></span>)}</div></details></section>;
}

function DevelopmentReview({ run, currentSubject, canReview, busy, comment, onComment, onReview }: { run: ScorecardDevelopmentRun; currentSubject: string; canReview: boolean; busy: boolean; comment: string; onComment: (value: string) => void; onReview: (decision: "approve" | "reject") => void }) {
  const gatePassed = run.report.validation_gate?.passed ?? false;
  if (run.review_status === "not_required") return <section className="development-review legacy"><strong>历史证据</strong><span>该记录生成于独立复核流程启用之前。</span></section>;
  if (run.review_status !== "pending_review") return <section className={`development-review ${run.review_status}`}><div><strong>{run.review_status === "approved" ? "独立复核已批准" : "独立复核已驳回"}</strong><span>{run.reviewed_by_name} · {run.reviewed_at ? new Date(run.reviewed_at).toLocaleString("zh-CN") : ""}</span><p>{run.review_comment}</p></div><code>{run.review_hash?.slice(0, 16)} · {run.review_integrity_valid ? "审核可复算" : "审核校验失败"}</code></section>;
  if (!canReview || run.created_by === currentSubject) return <section className="development-review pending_review"><strong>等待独立复核</strong><span>{run.created_by === currentSubject ? "创建人不能复核自己的验证证据" : "当前角色没有模型复核权限"}</span></section>;
  return <section className="development-review pending_review"><div><strong>独立复核</strong><span>{gatePassed ? "门禁通过，可批准或驳回" : "门禁失败，只能驳回并要求重新验证"}</span></div><input aria-label={`验证复核意见 ${run.id}`} value={comment} onChange={(event) => onComment(event.target.value)} placeholder="填写不少于 5 个字的复核结论" /><button disabled={busy || comment.trim().length < 5} onClick={() => onReview("reject")}>驳回</button><button className="primary-button" disabled={busy || !gatePassed || comment.trim().length < 5} onClick={() => onReview("approve")}>批准</button></section>;
}

function DevelopmentFairness({ run }: { run: ScorecardDevelopmentRun }) {
  const fairness = run.report.fairness;
  if (!fairness) return null;
  const testedFieldCount = fairness.segment_fields.filter((field) => fairness.splits.training?.[field]?.status === "tested").length;
  const splitLabels = { training: "训练集", validation: "验证集", oot: "时间外集" } as const;
  return <section className="development-fairness">
    <header><div><strong>样本代表性与分群公平性</strong><span>诊断证据，不直接修改评级、准入或授信结果</span></div><span className={fairness.status === "tested" ? "pass" : "blocked"}>{fairness.status === "tested" ? `${testedFieldCount} / ${fairness.segment_fields.length} 个字段可测试` : "分群不可测试"}</span></header>
    <div className="fairness-field-list">{fairness.segment_fields.map((field) => <details key={field}><summary><div><strong>{field}</strong><span>{fairness.sensitive_attribute_fields.includes(field) ? "敏感属性" : "业务分群"}</span></div><div><span>训练覆盖</span><b>{fairness.splits.training?.[field] ? `${(fairness.splits.training[field].coverage_rate * 100).toFixed(1)}%` : "N/A"}</b></div><div><span>验证群体 PSI</span><b>{metric(fairness.splits.validation?.[field]?.population_psi)}</b></div><div><span>OOT 群体 PSI</span><b>{metric(fairness.splits.oot?.[field]?.population_psi)}</b></div></summary>
      <div className="fairness-splits">{(["training", "validation", "oot"] as const).map((split) => { const report = fairness.splits[split]?.[field]; return <section key={split}><header><strong>{splitLabels[split]}</strong><span>{report ? report.status === "tested" ? `${report.group_count} 个群体 · 缺失 ${report.missing_count}` : report.status === "untestable" ? "属性缺失，不可测试" : "高基数，不生成结论" : "未配置快照"}</span></header>{report?.status === "tested" && <><div className="fairness-disparities"><span>事件率差 <b>{rate(report.disparities.event_rate_gap)}</b></span><span>平均分差 <b>{metric(report.disparities.average_score_gap)}</b></span><span>AUC / KS 差 <b>{metric(report.disparities.auc_gap)} / {metric(report.disparities.ks_gap)}</b></span><span>FPR / FNR 差 <b>{rate(report.disparities.false_positive_rate_gap)} / {rate(report.disparities.false_negative_rate_gap)}</b></span></div><div className="fairness-group-table"><div><b>群体</b><b>样本 / 占比</b><b>事件率</b><b>平均分</b><b>AUC / KS</b><b>FPR / FNR</b><b>分数 PSI</b></div>{report.groups.map((group) => <div className={group.sample_sufficient ? "" : "insufficient"} key={group.group}><span>{group.group}{group.sample_sufficient ? "" : " · 小样本"}</span><span>{group.sample_count} / {(group.population_share * 100).toFixed(1)}%</span><span>{(group.event_rate * 100).toFixed(1)}%</span><span>{group.average_score.toFixed(1)}</span><span>{metric(group.auc)} / {metric(group.ks)}</span><span>{rate(group.false_positive_rate)} / {rate(group.false_negative_rate)}</span><span>{metric(group.score_psi)}</span></div>)}</div></>}</section>; })}</div>
    </details>)}</div>
  </section>;
}

function metric(value: number | null | undefined) { return value === null || value === undefined ? "N/A" : value.toFixed(4); }
function rate(value: number | null | undefined) { return value === null || value === undefined ? "N/A" : `${(value * 100).toFixed(1)}%`; }
function csvFields(value: string) { return [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))]; }
function reviewStatusLabel(status: ScorecardDevelopmentRun["review_status"]) { return ({ not_required: "历史证据", pending_review: "待独立复核", approved: "验证已批准", rejected: "验证已驳回" })[status]; }
function policyStatusLabel(status: ScorecardValidationPolicy["status"]) { return ({ draft: "草稿", submitted: "待独立复核", published: "已发布", rejected: "已驳回" })[status]; }

function ScorecardDependencyGraphView({ graph, drifted, legacy, currentHash }: { graph: ScorecardDependencyGraph; drifted: boolean; legacy: boolean; currentHash: string }) {
  const stageTypes: Array<ScorecardDependencyNode["type"]> = ["indicator", "model", "pipeline", "rule_set", "rule", "release_package"];
  const labels: Record<ScorecardDependencyNode["type"], string> = { scorecard: "评分卡", indicator: "指标", model: "模型", pipeline: "管线", rule_set: "规则集", rule: "规则", release_package: "发布包" };
  const lifecycleLabels: Record<ScorecardDependencyNode["lifecycle"], string> = { candidate: "候选", dependency: "固定依赖", active: "当前生效", evidence: "历史快照", inflight: "在途" };
  return <section className={`scorecard-dependency-graph ${drifted ? "drifted" : ""}`}>
    <header><div><span>DEPENDENCY IMPACT GRAPH</span><strong>评分卡变更全链路影响</strong><small>{graph.nodes.length} 个节点 · {graph.edges.length} 条关系 · {graph.edges.filter((edge) => edge.direct).length} 条直接依赖</small></div><div><b>{drifted ? "依赖已漂移" : legacy ? "历史动态视图" : "依赖已固定"}</b><code>{graph.graph_hash.slice(0, 12)}</code>{drifted && <small>当前 {currentHash.slice(0, 12)}</small>}{legacy && !drifted && <small>发布时未冻结依赖图</small>}</div></header>
    <div className="dependency-flow" aria-label="评分卡依赖链">
      {stageTypes.map((type, index) => {
        const rows = graph.nodes.filter((node) => node.type === type);
        return <div className={`dependency-stage ${rows.some((node) => node.lifecycle === "inflight") ? "has-inflight" : ""}`} key={type}>
          <div><i>{String(index + 1).padStart(2, "0")}</i><span>{labels[type]}</span><b>{rows.length}</b></div>
          {rows.length ? <ul>{rows.slice(0, 5).map((node) => <li key={node.id}><span>{node.name}</span><code>{node.code}{node.version ? ` @ ${node.version}` : ""}</code><small>{node.directly_bound ? "直接绑定 · " : ""}{lifecycleLabels[node.lifecycle]}</small></li>)}{rows.length > 5 && <li className="more">另有 {rows.length - 5} 项</li>}</ul> : <p>无关联资产</p>}
        </div>;
      })}
    </div>
    <div className="dependency-governance">
      <div><strong>风险与在途冲突</strong>{graph.risks.length ? graph.risks.map((risk) => <p className={risk.severity} key={risk.key}><b>{risk.count}</b><span>{risk.label}</span></p>) : <p className="clear"><b>0</b><span>未发现关联模型或在途决策资产</span></p>}</div>
      <div><strong>发布后续动作</strong>{graph.required_actions.length ? <ol>{graph.required_actions.map((action) => <li key={action}>{action}</li>)}</ol> : <p className="empty">当前评分卡尚未进入模型和决策链，发布后仍需通过模型治理显式绑定。</p>}</div>
    </div>
  </section>;
}

function BindingEditor({ binding, onChange, onRemove, editable }: { binding: ScorecardIndicatorBinding; onChange: (value: ScorecardIndicatorBinding) => void; onRemove: () => void; editable: boolean }) {
  const updateBin = (index: number, patch: Partial<ScorecardBin>) => onChange({ ...binding, bins: binding.bins.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) });
  return <details className="binding-editor" open>
    <summary><div><strong>{binding.indicator_name}</strong><span>{binding.indicator_code} @ {binding.indicator_version}</span></div><label onClick={(event) => event.stopPropagation()}><span>权重 <FeatureHelp label="权重说明" text="表示该指标在评分卡汇总中的相对贡献。全部指标权重通常应合计 100%。" /></span><input disabled={!editable} type="number" min="0.01" step="0.1" value={binding.weight} onChange={(event) => onChange({ ...binding, weight: Number(event.target.value) })} /><em>%</em></label><button disabled={!editable} onClick={(event) => { event.preventDefault(); onRemove(); }} aria-label="移除指标" title="移除指标">×</button></summary>
    <div className="bin-table"><div className="bin-row bin-head"><span>分箱类型 <FeatureHelp label="分箱类型说明" text="决定如何把指标原始值归入风险组：连续区间适合金额、比例等数值；离散枚举适合布尔值、等级、行业等有限取值；缺失箱承接空值。" /></span><span>边界 / 枚举 <FeatureHelp label="边界或枚举说明" text="连续指标填写上下边界；离散指标填写逗号分隔的实际取值。每个取值只能属于一个箱。" /></span><span>标签 <FeatureHelp label="分箱标签说明" text="给分箱一个便于业务阅读的名称，例如正常、关注、高风险。标签不参与计算。" /></span><span>分数 <FeatureHelp label="分箱分数说明" text="样本命中该箱后获得的指标原始分，再结合指标权重映射为评分卡总分。" /></span><span>WOE <FeatureHelp label="WOE说明" text="Weight of Evidence，衡量该分箱对好坏样本的区分方向和强度。没有可靠带标签样本时可留空，不应凭空填写。" /></span></div>
      {binding.bins.map((bin, index) => <div className="bin-row" key={index}><span className="bin-kind-label">{bin.kind === "missing" ? <>缺失箱 <FeatureHelp label="缺失箱说明" text="专门承接空值或未采集数据，使缺失样本仍有明确评分和审计口径。" /></> : bin.kind === "range" ? <>连续区间 <FeatureHelp label="连续区间说明" text="把金额、比例、次数等连续数值按上下边界切成风险区间，例如 0 至 10、10 至 30。" /></> : <>离散枚举 <FeatureHelp label="离散枚举说明" text={binding.data_type === "boolean" ? "把布尔指标的实际取值映射到风险分箱。false 表示条件不成立，true 表示条件成立，它们是数据值，不是功能开关。" : "把等级、行业、状态等有限取值映射到不同风险分箱，例如正常、关注、异常。多个取值用英文逗号分隔。"} /></>}</span><span>{bin.kind === "range" ? <><input disabled={!editable} type="number" placeholder="-∞" value={bin.lower ?? ""} onChange={(event) => updateBin(index, { lower: event.target.value === "" ? null : Number(event.target.value) })} /><i>至</i><input disabled={!editable} type="number" placeholder="+∞" value={bin.upper ?? ""} onChange={(event) => updateBin(index, { upper: event.target.value === "" ? null : Number(event.target.value) })} /></> : bin.kind === "category" ? <input disabled={!editable} aria-label={`${binding.indicator_name}离散枚举值`} placeholder={binding.data_type === "boolean" ? "true 或 false（实际取值）" : "正常,关注,异常"} value={(bin.values ?? []).join(",")} onChange={(event) => updateBin(index, { values: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) })} /> : <i>空值 / 无数据</i>}</span><span><input disabled={!editable} value={bin.label} onChange={(event) => updateBin(index, { label: event.target.value })} /></span><span><input disabled={!editable} type="number" value={bin.score} onChange={(event) => updateBin(index, { score: Number(event.target.value) })} /></span><span><input disabled={!editable} type="number" step="0.01" placeholder="可选" value={bin.woe ?? ""} onChange={(event) => updateBin(index, { woe: event.target.value === "" ? null : Number(event.target.value) })} /></span></div>)}
    </div>
  </details>;
}

function starterBins(type: IndicatorCatalogItem["data_type"]): ScorecardBin[] { return type === "numeric" ? [{ kind: "range", label: "低值", score: 80, woe: null, lower: null, upper: 1, lower_inclusive: true, upper_inclusive: false }, { kind: "range", label: "高值", score: 20, woe: null, lower: 1, upper: null, lower_inclusive: true, upper_inclusive: false }, { kind: "missing", label: "缺失", score: 10, woe: null }] : [{ kind: "category", label: "正常", score: 80, woe: null, values: [type === "boolean" ? "false" : "正常"] }, { kind: "category", label: "异常", score: 20, woe: null, values: [type === "boolean" ? "true" : "异常"] }, { kind: "missing", label: "缺失", score: 10, woe: null }]; }
function weightedEdge(items: ScorecardIndicatorBinding[], edge: "min" | "max") { const total = items.reduce((sum, item) => sum + item.weight, 0); if (!total) return 0; return items.reduce((sum, item) => { const scores = item.bins.map((bin) => bin.score); return sum + (edge === "min" ? Math.min(...scores) : Math.max(...scores)) * item.weight / total; }, 0); }
function statusLabel(status: ScorecardChange["status"]) { return ({ draft: "草稿", submitted: "待独立复核", published: "已发布", rejected: "已驳回" })[status]; }
