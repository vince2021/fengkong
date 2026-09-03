import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { CreditCalibrationCandidate, DecisionPipelineDefinition, EnterpriseRiskIndicator, ModelChangeRecord, ModelDetail, ModelGovernanceNotification, ModelMonitoringRun, ModelMonitoringSchedule, ModelOutcome, ModelOutcomeImport, ModelReleaseRecord, ModelValidationReport, MonitoringIssue, MonitoringSummary, RiskScreeningPolicy, RiskScreeningPolicyRule, RuleCenterReplaySnapshot, ScorecardAsset, ScorecardDevelopmentRun, StrongRule } from "./types";


type Notice = { kind: "error" | "success"; text: string };
type OutcomeForm = { externalId: string; counterpartyId: string; period: string; score: number; pd: number; event: boolean; predictionAt: string; observationEnd: string; evidence: string };
const dimensionLabels: Record<string, string> = { external_risk: "外部风险", internal_performance: "内部履约", financial_credit: "财务信用", relationship_stability: "关联稳定" };
const thresholdLabels: Record<string, string> = { major_litigation_amount: "重大诉讼金额", dishonesty_count: "失信记录数", operating_abnormal_count: "经营异常数", delivery_delay_count: "履约延期次数", invoice_match_rate: "发票匹配率", overdue_rate: "逾期率", contract_dispute_count: "合同争议数" };
const statusLabels: Record<string, string> = { draft: "草稿", pending_review: "待审核", published: "已发布", rejected: "已驳回" };
const riskMetricLabels: Record<RiskScreeningPolicyRule["metric"], string> = { normalized_score: "筛查标准分", completeness: "数据完整度", critical_indicator_count: "关键低分指标数", missing_count: "缺失指标数" };


export default function ModelGovernancePanel({ model, modelKey, canManage, canReview, onPublished, onNotice }: { model: ModelDetail; modelKey: string; canManage: boolean; canReview: boolean; onPublished: () => Promise<void>; onNotice: (notice: Notice) => void }) {
  const [changes, setChanges] = useState<ModelChangeRecord[]>([]);
  const [releases, setReleases] = useState<ModelReleaseRecord[]>([]);
  const [validation, setValidation] = useState<ModelValidationReport | null>(null);
  const [monitoringSummary, setMonitoringSummary] = useState<MonitoringSummary | null>(null);
  const [outcomes, setOutcomes] = useState<ModelOutcome[]>([]);
  const [monitoringIssues, setMonitoringIssues] = useState<MonitoringIssue[]>([]);
  const [monitoringRuns, setMonitoringRuns] = useState<ModelMonitoringRun[]>([]);
  const [governanceNotifications, setGovernanceNotifications] = useState<ModelGovernanceNotification[]>([]);
  const [outcomeImports, setOutcomeImports] = useState<ModelOutcomeImport[]>([]);
  const [monitoringSchedules, setMonitoringSchedules] = useState<ModelMonitoringSchedule[]>([]);
  const [replaySnapshots, setReplaySnapshots] = useState<RuleCenterReplaySnapshot[]>([]);
  const [pipelines, setPipelines] = useState<DecisionPipelineDefinition[]>([]);
  const [scorecards, setScorecards] = useState<ScorecardAsset[]>([]);
  const [scorecardId, setScorecardId] = useState("");
  const [scorecardValidationRuns, setScorecardValidationRuns] = useState<ScorecardDevelopmentRun[]>([]);
  const [scorecardValidationRunId, setScorecardValidationRunId] = useState("");
  const [comparisonSnapshotId, setComparisonSnapshotId] = useState("");
  const [championPipeline, setChampionPipeline] = useState("");
  const [challengerPipeline, setChallengerPipeline] = useState("");
  const [evidenceValidDays, setEvidenceValidDays] = useState(30);
  const [comparisonThresholds, setComparisonThresholds] = useState({ psi: 0.25, rating: 0.25, admission: 0.15, score: 10, segment: 15, ks: 0.05 });
  const [candidateVersion, setCandidateVersion] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [thresholds, setThresholds] = useState<Record<string, number>>({});
  const [rules, setRules] = useState<StrongRule[]>([]);
  const [indicatorPool, setIndicatorPool] = useState<EnterpriseRiskIndicator[]>([]);
  const [indicatorSelection, setIndicatorSelection] = useState<Record<string, { weight: number; enabled: boolean }>>({});
  const [riskPolicy, setRiskPolicy] = useState<RiskScreeningPolicy>({ enabled: true, aggregation: "most_restrictive", rules: [] });
  const [indicatorSearch, setIndicatorSearch] = useState("");
  const [indicatorCategory, setIndicatorCategory] = useState("");
  const [reviewComment, setReviewComment] = useState("组合影响与规则边界已复核");
  const [editingId, setEditingId] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [monitoringOwner, setMonitoringOwner] = useState("模型验证组");
  const [monitoringNote, setMonitoringNote] = useState("补充真实结果样本，核对标签口径并完成模型重算复核");
  const [monitoringPeriod, setMonitoringPeriod] = useState("2026Q3");
  const [batchPayload, setBatchPayload] = useState("");
  const [importKey, setImportKey] = useState(`IMPORT-${Date.now()}`);
  const [importSource, setImportSource] = useState("ERP结果仓");
  const [importPeriod, setImportPeriod] = useState("2026Q2");
  const [importExpectedCount, setImportExpectedCount] = useState(1);
  const [scheduleCadence, setScheduleCadence] = useState<"monthly" | "quarterly">("quarterly");
  const [scheduleTimezone, setScheduleTimezone] = useState<"Asia/Shanghai" | "UTC">("Asia/Shanghai");
  const [scheduleEnabled, setScheduleEnabled] = useState(true);
  const [scheduleNextRun, setScheduleNextRun] = useState(defaultNextRunValue());
  const [outcomeForm, setOutcomeForm] = useState({ externalId: `OBS-${Date.now()}`, counterpartyId: "cp_supplier_low_001", period: "2026Q2", score: 80, pd: 0.05, event: false, predictionAt: "2026-01-01", observationEnd: "2026-07-15", evidence: "待核验的业务系统到期结算状态与应收台账引用" });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [changeRows, releaseRows, validationReport, monitoring, outcomeRows, issueRows, runRows, governanceNoticeRows, importRows, scheduleRows, poolResponse, snapshotRows, pipelineRows, scorecardRows, scorecardDevelopmentRows] = await Promise.all([api.modelChanges(modelKey), api.modelReleases(modelKey), api.modelValidation(modelKey), api.modelMonitoringSummary(modelKey), api.modelOutcomes(modelKey), api.monitoringIssues(modelKey), api.modelMonitoringRuns(modelKey), api.governanceNotifications(), api.outcomeImports(modelKey), api.monitoringSchedules(modelKey), api.indicatorPool(), api.ruleCenterReplaySnapshots(), api.decisionPipelines(), api.scorecards(), api.scorecardDevelopmentRuns()]);
      setChanges(changeRows);
      setReleases(releaseRows);
      setValidation(validationReport);
      setMonitoringSummary(monitoring);
      setOutcomes(outcomeRows);
      setMonitoringIssues(issueRows);
      setMonitoringRuns(runRows);
      setGovernanceNotifications(governanceNoticeRows.filter((item) => item.template_key === modelKey));
      setOutcomeImports(importRows);
      setMonitoringSchedules(scheduleRows);
      setIndicatorPool(poolResponse.indicators);
      setReplaySnapshots(snapshotRows);
      setPipelines(pipelineRows.filter((item) => item.is_active));
      setScorecards(scorecardRows);
      setScorecardValidationRuns(scorecardDevelopmentRows);
      setComparisonSnapshotId((current) => current || snapshotRows[0]?.id || "");
      if (scheduleRows[0]) {
        setScheduleCadence(scheduleRows[0].cadence);
        setScheduleTimezone(scheduleRows[0].timezone_name);
        setScheduleEnabled(scheduleRows[0].enabled);
        setScheduleNextRun(toLocalInputValue(scheduleRows[0].next_run_at));
      }
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "模型治理记录加载失败" });
    } finally { setLoading(false); }
  }, [modelKey, onNotice]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    setCandidateVersion(`${model.version}-NEXT`);
    setWeights({ ...model.weights });
    setThresholds({ ...model.thresholds });
    setRules(model.strong_rules.map((rule) => ({ ...rule, conditions: rule.conditions.map((condition) => ({ ...condition })), action: { ...rule.action } })));
    setIndicatorSelection(Object.fromEntries(model.indicator_selection.map((item) => [item.id, { weight: item.model_weight, enabled: item.enabled }])));
    setRiskPolicy(cloneRiskPolicy(model.risk_screening_policy));
    setScorecardId(model.scorecard_binding?.scorecard_asset_id ?? "");
    setScorecardValidationRunId("");
    setChangeReason("");
  }, [model]);

  async function createDraft() {
    if (!changeReason.trim()) return onNotice({ kind: "error", text: "请填写不少于 5 个字的变更原因" });
    setBusy("create");
    try {
      const editing = changes.find((item) => item.id === editingId);
      const created = editing
        ? await api.updateModelChange(editing.id, { expected_row_version: editing.row_version, change_reason: changeReason, weights, thresholds, strong_rules: rules, strategy_mapping: model.strategy_mapping, indicator_selection: serializeIndicatorSelection(indicatorSelection), risk_screening_policy: riskPolicy, scorecard_id: scorecardId || null, scorecard_validation_run_id: scorecardValidationRunId || null })
        : await api.createModelChange({ template_key: modelKey, candidate_version: candidateVersion, change_reason: changeReason, weights, thresholds, strong_rules: rules, strategy_mapping: model.strategy_mapping, indicator_selection: serializeIndicatorSelection(indicatorSelection), risk_screening_policy: riskPolicy, scorecard_id: scorecardId || null, scorecard_validation_run_id: scorecardValidationRunId || null });
      await reload();
      setEditingId("");
      onNotice({ kind: "success", text: `变更单 ${created.candidate_version} 已${editing ? "更新" : "创建"}，影响 ${created.impact.impacted_count}/${created.impact.sample_count} 个样本` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "变更单创建失败" }); }
    finally { setBusy(""); }
  }

  function editDraft(change: ModelChangeRecord) {
    setEditingId(change.id);
    setCandidateVersion(change.candidate_version);
    setChangeReason(change.change_reason);
    setWeights({ ...change.config.weights });
    setThresholds({ ...change.config.thresholds });
    setRules(change.config.strong_rules.map((rule) => ({ ...rule, conditions: rule.conditions.map((condition) => ({ ...condition })), action: { ...rule.action } })));
    const configured = change.config.indicator_selection ?? model.indicator_selection.map((item) => ({ indicator_id: item.id, weight: item.model_weight, enabled: item.enabled }));
    setIndicatorSelection(Object.fromEntries(configured.map((item) => [item.indicator_id, { weight: item.weight, enabled: item.enabled }])));
    setRiskPolicy(cloneRiskPolicy(change.config.risk_screening_policy ?? model.risk_screening_policy));
    setScorecardId(change.config.scorecard_binding?.scorecard_asset_id ?? "");
    setScorecardValidationRunId(change.scorecard_validation_evidence.validation_run_id ?? "");
  }

  async function submit(change: ModelChangeRecord) {
    setBusy(change.id);
    try { await api.submitModelChange(change.id, change.row_version); await reload(); onNotice({ kind: "success", text: `${change.candidate_version} 已提交风控审核` }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "提交审核失败" }); }
    finally { setBusy(""); }
  }

  async function runComparisonEvidence(change: ModelChangeRecord) {
    if (!comparisonSnapshotId) return onNotice({ kind: "error", text: "请先选择不可变回放快照" });
    setBusy(`comparison-${change.id}`);
    try {
      const result = await api.runModelChangeComparisonEvidence(change.id, {
        expected_row_version: change.row_version,
        dataset_snapshot_id: comparisonSnapshotId,
        champion_pipeline_code: championPipeline || undefined,
        challenger_pipeline_code: challengerPipeline || undefined,
        segment_field: "counterparty_type",
        positive_labels: ["bad", "default", "reject"],
        positive_admissions: ["reject", "禁入"],
        sample_limit: 500,
        max_execution_failure_rate: 0,
        max_psi: comparisonThresholds.psi,
        max_rating_change_rate: comparisonThresholds.rating,
        max_admission_change_rate: comparisonThresholds.admission,
        max_absolute_average_score_delta: comparisonThresholds.score,
        max_segment_absolute_score_delta: comparisonThresholds.segment,
        max_ks_drop: comparisonThresholds.ks,
        require_labeled_evidence: false,
        evidence_valid_days: evidenceValidDays,
      });
      await reload();
      const gate = result.comparison_evidence.gate;
      onNotice({ kind: gate?.passed ? "success" : "error", text: gate?.passed ? "候选比较证据已通过并绑定" : `${gate?.summary ?? "比较门禁阻断"}，可进入限期例外复核` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "候选比较运行失败" }); }
    finally { setBusy(""); }
  }

  async function review(change: ModelChangeRecord, decision: "publish" | "reject") {
    if (reviewComment.trim().length < 2) return onNotice({ kind: "error", text: "请填写评审意见" });
    setBusy(change.id);
    try {
      await api.reviewModelChange(change.id, change.row_version, decision, reviewComment);
      await reload();
      if (decision === "publish") await onPublished();
      onNotice({ kind: "success", text: decision === "publish" ? `${change.candidate_version} 已发布生效` : `${change.candidate_version} 已驳回` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "模型评审失败" }); }
    finally { setBusy(""); }
  }

  async function rollback(release: ModelReleaseRecord) {
    if (reviewComment.trim().length < 2) return onNotice({ kind: "error", text: "请填写回滚原因" });
    setBusy(release.id);
    try { await api.rollbackModelRelease(release.id, reviewComment); await reload(); await onPublished(); onNotice({ kind: "success", text: `已回滚至 ${release.model_version}` }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "版本回滚失败" }); }
    finally { setBusy(""); }
  }

  async function ingestOutcome() {
    if (!outcomeForm.externalId.trim() || !outcomeForm.counterpartyId.trim() || !outcomeForm.evidence.trim()) return onNotice({ kind: "error", text: "请补充观察编号、客商编号和证据引用" });
    setBusy("outcome");
    try {
      const result = await api.createModelOutcome({ external_observation_id: outcomeForm.externalId, source: "模型治理页面", template_key: modelKey, model_version: model.version, counterparty_id: outcomeForm.counterpartyId, population_period: outcomeForm.period, predicted_score: outcomeForm.score, predicted_pd: outcomeForm.pd, observed_event: outcomeForm.event, prediction_at: new Date(`${outcomeForm.predictionAt}T00:00:00+08:00`).toISOString(), observation_end: new Date(`${outcomeForm.observationEnd}T23:59:00+08:00`).toISOString(), evidence_reference: outcomeForm.evidence });
      setOutcomeForm({ ...outcomeForm, externalId: `OBS-${Date.now()}` });
      await reload();
      onNotice({ kind: "success", text: result.idempotent ? "该观察结果已存在，本次按幂等请求返回" : "真实结果观察记录已入库" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "结果观察记录写入失败" }); }
    finally { setBusy(""); }
  }

  async function scanMonitoringIssues() {
    setBusy("issue-scan");
    try { const rows = await api.scanMonitoringIssues(modelKey); await reload(); onNotice({ kind: "success", text: `本轮识别 ${rows.length} 个需要治理的问题` }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "监控问题扫描失败" }); }
    finally { setBusy(""); }
  }

  async function verifyOutcome(outcome: ModelOutcome, decision: "verify" | "reject") {
    if (monitoringNote.trim().length < 5) return onNotice({ kind: "error", text: "请填写不少于 5 个字的证据核验说明" });
    setBusy(outcome.id);
    try { await api.verifyModelOutcome(outcome.id, outcome.row_version, decision, monitoringNote); await reload(); onNotice({ kind: "success", text: decision === "verify" ? "结果证据已核验，将计入真实观察样本" : "结果证据已驳回，不计入模型回溯" }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "结果证据核验失败" }); }
    finally { setBusy(""); }
  }

  async function ingestOutcomeBatch() {
    setBusy("outcome-batch");
    try {
      const rows = JSON.parse(batchPayload) as Parameters<typeof api.createModelOutcomesBatch>[0];
      if (!Array.isArray(rows) || !rows.length) throw new Error("请粘贴至少一条 JSON 数组记录");
      const result = await api.createOutcomeImport({ import_key: importKey, source: importSource, template_key: modelKey, population_period: importPeriod, expected_count: importExpectedCount, outcomes: rows });
      setImportKey(`IMPORT-${Date.now()}`);
      await reload();
      onNotice({ kind: result.status === "completed" ? "success" : "error", text: `导入对账完成：新增 ${result.created_count}、幂等 ${result.idempotent_count}、拒绝 ${result.rejected_count}、数量差异 ${result.count_variance}` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "批量结果接入失败" }); }
    finally { setBusy(""); }
  }

  async function executeMonitoringRun() {
    setBusy("monitoring-run");
    try {
      const run = await api.executeModelMonitoringRun({ run_key: `UI-${modelKey}-${monitoringPeriod}-${Date.now()}`, template_key: modelKey, as_of_period: monitoringPeriod, trigger_type: "manual" });
      await reload();
      onNotice({ kind: "success", text: `监控批次已完成，形成 ${run.issue_ids.length} 个治理问题` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "监控批次执行失败" }); }
    finally { setBusy(""); }
  }

  async function saveMonitoringSchedule() {
    setBusy("monitoring-schedule");
    try {
      const schedule = monitoringSchedules[0];
      const payload = { cadence: scheduleCadence, timezone_name: scheduleTimezone, enabled: scheduleEnabled, next_run_at: new Date(scheduleNextRun).toISOString() };
      if (schedule) await api.updateMonitoringSchedule(schedule.id, { expected_row_version: schedule.row_version, ...payload });
      else await api.createMonitoringSchedule({ template_key: modelKey, ...payload });
      await reload();
      onNotice({ kind: "success", text: schedule ? "模型监控计划已更新" : "模型监控计划已创建" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "模型监控计划保存失败" }); }
    finally { setBusy(""); }
  }

  async function executeDueSchedules() {
    setBusy("schedule-tick");
    try {
      const result = await api.runDueMonitoringSchedules();
      await reload();
      onNotice({ kind: result.failed ? "error" : "success", text: `到期计划扫描完成：到期 ${result.due_count}、成功 ${result.completed}、失败 ${result.failed}` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "到期监控计划执行失败" }); }
    finally { setBusy(""); }
  }

  async function readGovernanceNotification(notification: ModelGovernanceNotification) {
    setBusy(notification.id);
    try { await api.readGovernanceNotification(notification.id); await reload(); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "治理通知确认失败" }); }
    finally { setBusy(""); }
  }

  async function linkIssueToChange(issue: MonitoringIssue, changeId: string) {
    setBusy(issue.id);
    try { await api.linkMonitoringIssueChange(issue.id, issue.row_version, changeId); await reload(); onNotice({ kind: "success", text: "监控问题已关联模型重校准草稿" }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "关联重校准草稿失败" }); }
    finally { setBusy(""); }
  }

  async function actOnMonitoringIssue(issue: MonitoringIssue, action: "remediate" | "submit" | "pass" | "fail") {
    if (monitoringNote.trim().length < 5) return onNotice({ kind: "error", text: "请填写不少于 5 个字的整改或复验说明" });
    setBusy(issue.id);
    try {
      if (action === "remediate") await api.startMonitoringRemediation(issue.id, issue.row_version, monitoringOwner, monitoringNote);
      if (action === "submit") await api.submitMonitoringRevalidation(issue.id, issue.row_version, monitoringNote);
      if (action === "pass" || action === "fail") await api.reviewMonitoringRevalidation(issue.id, issue.row_version, action, monitoringNote);
      await reload();
      onNotice({ kind: "success", text: ({ remediate: "整改计划已启动", submit: "已提交独立复验", pass: "复验通过，问题已关闭", fail: "复验未通过，已退回整改" } as const)[action] });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "监控问题操作失败" }); }
    finally { setBusy(""); }
  }

  const approvedScorecardValidations = scorecardValidationRuns.filter((run) => run.scorecard_asset_id === scorecardId && run.review_status === "approved" && run.integrity_valid && run.review_integrity_valid && run.report.validation_gate?.passed);

  return <section className="panel governance-panel">
    <div className="section-title"><div><span>MODEL LIFECYCLE</span><h2>模型变更、审核与发布治理</h2></div><span className="soft-chip">制作者与审批者分离</span></div>
    <div className="governance-guide"><div><b>01</b><span>配置草稿</span></div><i>→</i><div><b>02</b><span>全样本重算</span></div><i>→</i><div><b>03</b><span>提交风控审核</span></div><i>→</i><div><b>04</b><span>发布或回滚</span></div></div>
    <IndicatorPoolComposer pool={indicatorPool} selection={indicatorSelection} search={indicatorSearch} category={indicatorCategory} editable={canManage} onSearch={setIndicatorSearch} onCategory={setIndicatorCategory} onSelection={setIndicatorSelection} />
    <ModelValidationDashboard report={validation} loading={loading} />
    <MonitoringClosurePanel summary={monitoringSummary} outcomes={outcomes} imports={outcomeImports} issues={monitoringIssues} runs={monitoringRuns} schedules={monitoringSchedules} notifications={governanceNotifications} changes={changes} canManage={canManage} canReview={canReview} busy={busy} owner={monitoringOwner} note={monitoringNote} monitoringPeriod={monitoringPeriod} batchPayload={batchPayload} importKey={importKey} importSource={importSource} importPeriod={importPeriod} importExpectedCount={importExpectedCount} scheduleCadence={scheduleCadence} scheduleTimezone={scheduleTimezone} scheduleEnabled={scheduleEnabled} scheduleNextRun={scheduleNextRun} outcomeForm={outcomeForm} onOwner={setMonitoringOwner} onNote={setMonitoringNote} onMonitoringPeriod={setMonitoringPeriod} onBatchPayload={setBatchPayload} onImportKey={setImportKey} onImportSource={setImportSource} onImportPeriod={setImportPeriod} onImportExpectedCount={setImportExpectedCount} onScheduleCadence={setScheduleCadence} onScheduleTimezone={setScheduleTimezone} onScheduleEnabled={setScheduleEnabled} onScheduleNextRun={setScheduleNextRun} onOutcomeForm={setOutcomeForm} onIngest={() => void ingestOutcome()} onIngestBatch={() => void ingestOutcomeBatch()} onSaveSchedule={() => void saveMonitoringSchedule()} onRunDueSchedules={() => void executeDueSchedules()} onVerifyOutcome={(outcome, decision) => void verifyOutcome(outcome, decision)} onScan={() => void scanMonitoringIssues()} onRun={() => void executeMonitoringRun()} onReadNotification={(notification) => void readGovernanceNotification(notification)} onLinkChange={(issue, changeId) => void linkIssueToChange(issue, changeId)} onAction={(issue, action) => void actOnMonitoringIssue(issue, action)} />

    {canManage && <div className="governance-editor">
      <div className="governance-subhead"><div><strong>{editingId ? "编辑治理草稿" : "新建候选版本"}</strong><span>基于当前生效版本 {model.version}</span></div><button className="primary-button" disabled={busy === "create"} onClick={() => void createDraft()}>{busy === "create" ? "正在校验组合…" : editingId ? "保存并重新评估" : "创建治理草稿"}</button></div>
      <div className="governance-form-row"><label><span>候选版本号</span><input disabled={Boolean(editingId)} value={candidateVersion} onChange={(event) => setCandidateVersion(event.target.value)} /></label><label className="wide"><span>变更原因</span><input value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder="说明业务依据、预期效果与风险边界" /></label></div>
      <div className="config-editor-grid">
        <div><h3>维度权重</h3><div className="config-field-grid">{Object.entries(weights).map(([key, value]) => <label key={key}><span>{dimensionLabels[key] ?? key}</span><div><input type="number" min="0" max="1" step="0.01" value={value} onChange={(event) => setWeights({ ...weights, [key]: Number(event.target.value) })} /><small>{(value * 100).toFixed(0)}%</small></div></label>)}</div><p>当前合计：{(Object.values(weights).reduce((sum, value) => sum + value, 0) * 100).toFixed(1)}%</p></div>
        <div><h3>评分阈值</h3><div className="config-field-grid thresholds">{Object.entries(thresholds).map(([key, value]) => <label key={key}><span>{thresholdLabels[key] ?? key}</span><input type="number" step={key.includes("rate") ? "0.01" : "1"} value={value} onChange={(event) => setThresholds({ ...thresholds, [key]: Number(event.target.value) })} /></label>)}</div></div>
      </div>
      <section className="model-scorecard-binding">
        <header><div><span>GOVERNED SCORECARD</span><h3>评分卡执行绑定</h3><p>模型候选固定已发布评分卡版本和配置哈希；不选择时继续使用当前模型评分逻辑。</p></div><label><span>评分卡资产</span><select value={scorecardId} onChange={(event) => { setScorecardId(event.target.value); setScorecardValidationRunId(""); }}><option value="">不绑定（沿用现有评分逻辑）</option>{scorecards.map((asset) => <option key={asset.id} value={asset.id}>{asset.name} · v{asset.version}{asset.is_active ? " · 当前生效" : " · 历史版本"}</option>)}</select></label></header>
        {scorecardId && (() => { const asset = scorecards.find((item) => item.id === scorecardId); return asset ? <div className="model-scorecard-evidence"><div><span>固定资产</span><b>{asset.code} @ v{asset.version}</b></div><div><span>指标 / 分箱</span><b>{asset.config.indicators.length} / {asset.config.indicators.reduce((sum, item) => sum + item.bins.length, 0)}</b></div><div><span>业务刻度</span><b>{asset.config.score_scale.min} - {asset.config.score_scale.max}</b></div><div><span>配置哈希</span><code>{asset.config_hash.slice(0, 16)}</code></div></div> : null; })()}
        {scorecardId && <div className="model-scorecard-validation-picker"><label><span>已批准开发验证</span><select value={scorecardValidationRunId} onChange={(event) => setScorecardValidationRunId(event.target.value)}><option value="">请选择 PASS 且已独立批准的证据</option>{approvedScorecardValidations.map((run) => <option key={run.id} value={run.id}>{run.created_at ? new Date(run.created_at).toLocaleDateString("zh-CN") : "固定运行"} · {run.report.validation_gate?.summary} · {run.evidence_hash.slice(0, 10)}</option>)}</select></label><span className={scorecardValidationRunId ? "pass" : "blocked"}>{scorecardValidationRunId ? "开发验证证据已选择" : approvedScorecardValidations.length ? "提交前必须选择" : "当前评分卡没有可绑定的批准证据"}</span></div>}
      </section>
      <div className="rule-switches"><h3>强规则启停</h3>{rules.map((rule, index) => <label key={rule.id}><input type="checkbox" checked={rule.enabled} onChange={(event) => setRules(rules.map((item, itemIndex) => itemIndex === index ? { ...item, enabled: event.target.checked } : item))} /><span><strong>{rule.id} · {rule.name}</strong><small>{rule.conditions.map((condition) => condition.label).join(rule.condition_relation === "all" ? " 且 " : " 或 ")}</small></span></label>)}</div>
      <div className="risk-policy-editor">
        <header><div><h3>企业风险贷策收紧层</h3><p>风险指标池命中后，按最严格动作调整评级、额度、账期与准入策略。</p></div><label><input type="checkbox" checked={riskPolicy.enabled} onChange={(event) => setRiskPolicy({ ...riskPolicy, enabled: event.target.checked })} />启用策略层</label></header>
        <div className="risk-policy-rule-list">{riskPolicy.rules.map((rule, index) => <article key={rule.id}>
          <div className="risk-policy-rule-title"><label><input type="checkbox" checked={rule.enabled} onChange={(event) => setRiskPolicy(updateRiskRule(riskPolicy, index, { enabled: event.target.checked }))} /><span><strong>{rule.id}</strong>{rule.name}</span></label></div>
          <div className="risk-policy-fields">
            <label><span>判断指标</span><select value={rule.metric} onChange={(event) => setRiskPolicy(updateRiskRule(riskPolicy, index, { metric: event.target.value as RiskScreeningPolicyRule["metric"] }))}>{Object.entries(riskMetricLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label><span>运算符</span><select value={rule.operator} onChange={(event) => setRiskPolicy(updateRiskRule(riskPolicy, index, { operator: event.target.value as RiskScreeningPolicyRule["operator"] }))}>{["<", "<=", ">", ">=", "=="].map((value) => <option key={value}>{value}</option>)}</select></label>
            <label><span>阈值</span><input type="number" step={rule.metric === "completeness" ? 0.05 : 1} value={rule.value} onChange={(event) => setRiskPolicy(updateRiskRule(riskPolicy, index, { value: Number(event.target.value) }))} /></label>
            <label><span>评级下调</span><input type="number" min="0" max="3" value={rule.action.rating_notch_down} onChange={(event) => setRiskPolicy(updateRiskAction(riskPolicy, index, { rating_notch_down: Number(event.target.value) }))} /></label>
            <label><span>额度上限</span><div><input type="number" min="0" max="1" step="0.05" value={rule.action.limit_cap_ratio} onChange={(event) => setRiskPolicy(updateRiskAction(riskPolicy, index, { limit_cap_ratio: Number(event.target.value) }))} /><small>{(rule.action.limit_cap_ratio * 100).toFixed(0)}%</small></div></label>
            <label><span>账期上限</span><input type="number" min="0" max="3650" value={rule.action.term_cap_days} onChange={(event) => setRiskPolicy(updateRiskAction(riskPolicy, index, { term_cap_days: Number(event.target.value) }))} /></label>
            <label><span>准入策略</span><select value={rule.action.access_strategy} onChange={(event) => setRiskPolicy(updateRiskAction(riskPolicy, index, { access_strategy: event.target.value as RiskScreeningPolicyRule["action"]["access_strategy"] }))}>{["正常准入", "审慎准入", "人工复核", "限制准入", "禁入"].map((value) => <option key={value}>{value}</option>)}</select></label>
            <label><span>监控频率</span><select value={rule.action.monitoring_frequency} onChange={(event) => setRiskPolicy(updateRiskAction(riskPolicy, index, { monitoring_frequency: event.target.value as RiskScreeningPolicyRule["action"]["monitoring_frequency"] }))}>{["年度", "半年度", "季度", "月度", "周度", "实时监控"].map((value) => <option key={value}>{value}</option>)}</select></label>
          </div>
        </article>)}</div>
      </div>
    </div>}

    {canManage && <section className="comparison-evidence-console">
      <div className="governance-subhead"><div><strong>Champion / Challenger 发布证据</strong><span>固定基线、候选配置、快照和管线版本</span></div><small>运行后绑定至对应草稿</small></div>
      <div className="comparison-evidence-fields">
        <label><span>不可变数据快照</span><select value={comparisonSnapshotId} onChange={(event) => setComparisonSnapshotId(event.target.value)}><option value="">请选择快照</option>{replaySnapshots.map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.as_of_date} · {item.sample_count} 条</option>)}</select></label>
        <label><span>Champion 管线</span><select value={championPipeline} onChange={(event) => setChampionPipeline(event.target.value)}><option value="">沿用模型固定管线</option>{pipelines.map((item) => <option key={item.id} value={item.code}>{item.code} · v{item.version}</option>)}</select></label>
        <label><span>Challenger 管线</span><select value={challengerPipeline} onChange={(event) => setChallengerPipeline(event.target.value)}><option value="">沿用候选固定管线</option>{pipelines.map((item) => <option key={item.id} value={item.code}>{item.code} · v{item.version}</option>)}</select></label>
        <label><span>证据有效天数</span><input type="number" min="1" max="180" value={evidenceValidDays} onChange={(event) => setEvidenceValidDays(Number(event.target.value))} /></label>
      </div>
      <div className="comparison-threshold-grid">
        <label><span>PSI 上限</span><input type="number" min="0" step="0.01" value={comparisonThresholds.psi} onChange={(event) => setComparisonThresholds({ ...comparisonThresholds, psi: Number(event.target.value) })} /></label>
        <label><span>评级变化率</span><input type="number" min="0" max="1" step="0.01" value={comparisonThresholds.rating} onChange={(event) => setComparisonThresholds({ ...comparisonThresholds, rating: Number(event.target.value) })} /></label>
        <label><span>准入变化率</span><input type="number" min="0" max="1" step="0.01" value={comparisonThresholds.admission} onChange={(event) => setComparisonThresholds({ ...comparisonThresholds, admission: Number(event.target.value) })} /></label>
        <label><span>平均分绝对差</span><input type="number" min="0" step="1" value={comparisonThresholds.score} onChange={(event) => setComparisonThresholds({ ...comparisonThresholds, score: Number(event.target.value) })} /></label>
        <label><span>分群分差上限</span><input type="number" min="0" step="1" value={comparisonThresholds.segment} onChange={(event) => setComparisonThresholds({ ...comparisonThresholds, segment: Number(event.target.value) })} /></label>
        <label><span>KS 下降上限</span><input type="number" min="0" max="1" step="0.01" value={comparisonThresholds.ks} onChange={(event) => setComparisonThresholds({ ...comparisonThresholds, ks: Number(event.target.value) })} /></label>
      </div>
    </section>}

    {canReview && <label className="review-comment"><span>评审/回滚意见</span><input value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} /></label>}

    <div className="governance-history-grid">
      <div>
        <div className="governance-subhead"><div><strong>变更单</strong><span>{changes.length} 条治理记录</span></div></div>
        {loading ? <div className="governance-empty">正在加载治理记录…</div> : changes.length ? <div className="change-list">{changes.map((change) => {
          const evidence = change.comparison_evidence;
          const evidenceStatus = evidence.current_effective_status ?? evidence.effective_status;
          const evidenceReady = evidenceStatus === "passed" || evidenceStatus === "exception_approved";
          const scorecardValidationReady = !change.config.scorecard_binding || change.scorecard_validation_evidence.current_valid === true;
          const calibrationReady = !change.calibration_evidence.analysis || change.calibration_evidence.current_valid === true;
          const currentGate = evidence.current_gate ?? evidence.gate;
          return <article className="change-card" key={change.id}>
            <header><div><span className={`governance-status ${change.status}`}>{statusLabels[change.status]}</span><strong>{change.candidate_version}</strong>{change.validation.model_risk && <span className={`validation-mini ${change.validation.model_risk.release_gate.status}`}>{change.validation.model_risk.release_gate.passed ? "验证通过" : "发布阻断"}</span>}</div><small>v{change.row_version}</small></header>
            <p>{change.change_reason}</p>
            <div className="impact-stat-row"><span><b>{change.impact.impacted_count}</b>主模型影响</span><span><b>{change.impact.rating_changes}</b>评级迁移</span><span><b>{change.impact.strategy_changes}</b>策略变化</span><span><b>{change.impact.max_abs_score_delta}</b>主模型分差</span><span><b>{change.impact.risk_screening_impacted_count ?? 0}</b>筛查分影响</span></div>
            <CalibrationEvidenceSummary change={change} />
            <ScorecardBindingSummary change={change} />
            <ScorecardValidationEvidenceSummary change={change} />
            <ComparisonEvidenceSummary change={change} />
            <footer><span>{change.created_by_name} · {formatTime(change.created_at)}</span><div>
              {canManage && change.status === "draft" && <><button className="secondary" disabled={Boolean(busy)} onClick={() => editDraft(change)}>编辑</button><button className="secondary" disabled={Boolean(busy) || !comparisonSnapshotId || !calibrationReady} onClick={() => void runComparisonEvidence(change)}>{busy === `comparison-${change.id}` ? "比较运行中…" : evidence.comparison_run_id ? "重新运行比较" : "运行候选比较"}</button><button disabled={Boolean(busy) || change.validation.model_risk?.release_gate.passed === false || !evidenceReady || !scorecardValidationReady || !calibrationReady} title={!calibrationReady ? "校准来源证据已失效" : !scorecardValidationReady ? "缺少与固定评分卡匹配的已批准 PASS 验证证据" : !evidenceReady ? "缺少有效的候选比较证据" : change.validation.model_risk?.release_gate.summary} onClick={() => void submit(change)}>提交审核</button></>}
              {canReview && change.status === "pending_review" && <><button className="reject" disabled={Boolean(busy)} onClick={() => void review(change, "reject")}>驳回</button><button disabled={Boolean(busy) || change.validation.model_risk?.release_gate.passed === false || !evidenceReady || !scorecardValidationReady || !calibrationReady} title={!calibrationReady ? "校准来源证据已失效" : !scorecardValidationReady ? "评分卡开发验证证据已失效" : !evidenceReady ? "比较证据无效、过期或尚未完成例外复核" : currentGate?.summary} onClick={() => void review(change, "publish")}>审核发布</button></>}
            </div></footer>
            {change.validation.model_risk?.release_gate.passed === false && <aside className="validation-blocker">发布阻断：{change.validation.model_risk.release_gate.summary}</aside>}
            {change.review_comment && <aside>评审意见：{change.review_comment}</aside>}
          </article>;
        })}</div> : <div className="governance-empty">暂无模型变更单</div>}
      </div>
      <div><div className="governance-subhead"><div><strong>发布版本</strong><span>生效指针与回滚入口</span></div></div>{releases.length ? <div className="release-list">{releases.map((release) => <div className={`release-row ${release.is_active ? "active" : ""}`} key={release.id}><div><span>{release.is_active ? "当前生效" : "历史版本"}</span><strong>{release.model_version}</strong><small>{release.published_by} · {formatTime(release.published_at)}</small><code>{release.config_hash.slice(0, 12)}</code></div>{canReview && !release.is_active && <button disabled={busy === release.id} onClick={() => void rollback(release)}>回滚至此版本</button>}</div>)}</div> : <div className="governance-empty">首次发布后将生成基线与版本历史</div>}</div>
    </div>
  </section>;
}


function CalibrationEvidenceSummary({ change }: { change: ModelChangeRecord }) {
  const evidence = change.calibration_evidence;
  const analysis = evidence.analysis;
  if (!analysis) return null;
  const changedParameters = calibrationParameterLabels.filter(([key]) => analysis.candidate_parameters[key] !== analysis.baseline_parameters[key]);
  return <div className={`model-calibration-summary ${evidence.current_valid ? "passed" : "invalid"}`}>
    <div><span>校准来源</span><strong>{evidence.current_valid ? "证据可复算" : "证据失效"}</strong><small>{evidence.plan_code ? `${evidence.plan_code} v${evidence.plan_version} · 已独立批准` : analysis.sample.evidence_level === "supervised" ? "监督校准证据" : "非监督降级证据"}</small></div>
    <div><span>固定样本</span><strong>{analysis.snapshot.dataset_code} · v{analysis.snapshot.version}</strong><small>{analysis.sample.paired_success_count} 条成对成功</small></div>
    <div><span>候选调整</span><strong>{changedParameters.length} 项参数</strong><small>{changedParameters.slice(0, 3).map(([, label]) => label).join("、") || "参数与基线一致"}</small></div>
    <div><span>分析 / 配置哈希</span><code>{analysis.evidence_hash.slice(0, 10)} · {evidence.candidate_config_hash?.slice(0, 10)}</code><small>{evidence.calibration_run_id ? `运行 ${evidence.calibration_run_id.slice(0, 8)} · ${evidence.bound_by_name}` : evidence.bound_by_name}</small></div>
    {evidence.current_error && <p>{evidence.current_error}</p>}
  </div>;
}

const calibrationParameterLabels: Array<[keyof CreditCalibrationCandidate, string]> = [
  ["score_threshold_shift", "评级门槛"], ["limit_multiplier_scale", "等级额度"], ["revenue_limit_scale", "收入承载"],
  ["order_amount_scale", "交易承载"], ["payment_term_scale", "账期"], ["overdue_rate_high", "逾期阈值"],
  ["limit_utilization_high", "额度使用"], ["invoice_match_rate_low", "发票匹配"], ["delivery_fulfillment_rate_low", "交付达成"],
];


function ScorecardBindingSummary({ change }: { change: ModelChangeRecord }) {
  const binding = change.config.scorecard_binding;
  if (!binding) return <div className="change-scorecard-summary legacy"><div><span>评分卡执行绑定</span><strong>沿用现有评分逻辑</strong></div><small>{change.impact.scorecard_binding_changed ? "本次候选已解除评分卡绑定" : "未启用治理评分卡运行时"}</small></div>;
  const binCount = binding.config.indicators.reduce((total, item) => total + item.bins.length, 0);
  return <div className="change-scorecard-summary">
    <div><span>固定评分卡</span><strong>{binding.code} @ v{binding.version}</strong></div>
    <div><span>执行资产</span><strong>{binding.config.indicators.length} 项指标 / {binCount} 个分箱</strong></div>
    <div><span>业务刻度</span><strong>{binding.config.score_scale.min} - {binding.config.score_scale.max}</strong></div>
    <div><span>配置哈希</span><code>{binding.config_hash}</code></div>
    {change.impact.scorecard_binding_changed && <small>本次候选变更了评分卡执行绑定，旧比较证据必须重新生成。</small>}
  </div>;
}


function ScorecardValidationEvidenceSummary({ change }: { change: ModelChangeRecord }) {
  if (!change.config.scorecard_binding) return null;
  const evidence = change.scorecard_validation_evidence;
  if (!evidence.validation_run_id) return <div className="scorecard-validation-summary missing"><div><strong>评分卡开发验证待绑定</strong><span>必须选择与固定评分卡版本一致、门禁 PASS 且已独立批准的运行。</span></div></div>;
  return <div className={`scorecard-validation-summary ${evidence.current_valid ? "passed" : "invalid"}`}>
    <div><span>开发验证门禁</span><strong>{evidence.current_valid ? "PASS · 已批准" : "证据失效"}</strong><small>{evidence.validation_gate_summary}</small></div>
    <div><span>固定评分卡</span><strong>{evidence.scorecard_code} @ v{evidence.scorecard_version}</strong><small>{evidence.report_schema_version}</small></div>
    <div><span>三集合快照</span><strong>{evidence.dataset_snapshot_id ? "训练" : "-"} / {evidence.validation_snapshot_id ? "验证" : "-"} / {evidence.oot_snapshot_id ? "OOT" : "-"}</strong><small>{evidence.evidence_level === "labeled" ? "监督验证证据" : "降级证据"}</small></div>
    <div><span>独立复核 / 双哈希</span><strong>{evidence.reviewed_by_name}</strong><code>{evidence.evidence_hash?.slice(0, 8)} · {evidence.review_hash?.slice(0, 8)}</code></div>
    {evidence.current_error && <p>{evidence.current_error}</p>}
  </div>;
}


function ComparisonEvidenceSummary({ change }: { change: ModelChangeRecord }) {
  const evidence = change.comparison_evidence;
  if (!evidence.comparison_run_id) return <div className="comparison-evidence-summary missing"><strong>候选比较证据待生成</strong><span>提交前必须固定基线、候选配置、快照与管线版本。</span></div>;
  const gate = evidence.current_gate ?? evidence.gate;
  const effectiveStatus = evidence.current_effective_status ?? evidence.effective_status;
  const effectiveLabels: Record<string, string> = { passed: "可发布", blocked: "门禁阻断", exception_pending: "例外待复核", exception_approved: "限期例外有效", invalid: "证据失效" };
  return <div className={`comparison-evidence-summary ${effectiveStatus ?? "invalid"}`}>
    <div><span>原始比较门禁</span><strong>{gate?.passed ? "通过" : "失败"}</strong><small>{gate?.summary}</small></div>
    <div><span>当前处置状态</span><strong>{effectiveLabels[effectiveStatus ?? "invalid"]}</strong><small>{evidence.latest_exception?.reviewed_by_name ? `独立复核：${evidence.latest_exception.reviewed_by_name}` : "未使用治理例外"}</small></div>
    <div><span>固定版本</span><strong>{evidence.champion_model_version} → {evidence.challenger_model_version}</strong><small>{evidence.evidence_level === "labeled" ? "有标签监督证据" : "无标签，降级为非监督证据"}</small></div>
    <div><span>有效期 / 证据哈希</span><strong>{evidence.valid_until}</strong><code>{evidence.comparison_evidence_hash?.slice(0, 12)}</code></div>
    {evidence.current_error && <p>{evidence.current_error}</p>}
  </div>;
}


function serializeIndicatorSelection(selection: Record<string, { weight: number; enabled: boolean }>) {
  return Object.entries(selection).map(([indicator_id, item]) => ({ indicator_id, weight: item.weight, enabled: item.enabled }));
}

function cloneRiskPolicy(policy: RiskScreeningPolicy): RiskScreeningPolicy {
  return { ...policy, rules: policy.rules.map((rule) => ({ ...rule, action: { ...rule.action } })) };
}

function updateRiskRule(policy: RiskScreeningPolicy, index: number, change: Partial<RiskScreeningPolicyRule>): RiskScreeningPolicy {
  return { ...policy, rules: policy.rules.map((rule, itemIndex) => itemIndex === index ? { ...rule, ...change } : rule) };
}

function updateRiskAction(policy: RiskScreeningPolicy, index: number, change: Partial<RiskScreeningPolicyRule["action"]>): RiskScreeningPolicy {
  return { ...policy, rules: policy.rules.map((rule, itemIndex) => itemIndex === index ? { ...rule, action: { ...rule.action, ...change } } : rule) };
}


function IndicatorPoolComposer({ pool, selection, search, category, editable, onSearch, onCategory, onSelection }: {
  pool: EnterpriseRiskIndicator[];
  selection: Record<string, { weight: number; enabled: boolean }>;
  search: string;
  category: string;
  editable: boolean;
  onSearch: (value: string) => void;
  onCategory: (value: string) => void;
  onSelection: (value: Record<string, { weight: number; enabled: boolean }>) => void;
}) {
  const categories = [...new Set(pool.map((item) => item.category))];
  const query = search.trim().toLowerCase();
  const filtered = pool.filter((item) => {
    if (category && item.category !== category) return false;
    if (!query) return true;
    return `${item.name} ${item.description} ${item.scoring.formula} ${item.data_source}`.toLowerCase().includes(query);
  });
  const grouped = categories.map((name) => ({ name, items: filtered.filter((item) => item.category === name) })).filter((group) => group.items.length);
  const selectedCount = Object.values(selection).filter((item) => item.enabled).length;
  function toggle(item: EnterpriseRiskIndicator, checked: boolean) {
    const next = { ...selection };
    if (checked) next[item.id] = { weight: selection[item.id]?.weight ?? item.default_weight, enabled: true };
    else delete next[item.id];
    onSelection(next);
  }
  function changeWeight(item: EnterpriseRiskIndicator, weight: number) {
    onSelection({ ...selection, [item.id]: { weight: Math.max(0.01, Math.min(100, weight || 1)), enabled: true } });
  }
  return <section className="indicator-pool-composer">
    <header><div><span>ENTERPRISE RISK INDICATOR POOL</span><h3>企业风险指标池与模型自由组合</h3><p>指标来自第三方风险排查参考表，统一采用 1—3 分口径；3 分代表低风险，缺失数据按 2 分并进入补充清单。</p></div><aside><strong>{pool.length}</strong><span>池内指标</span><b>{selectedCount} 项已选</b></aside></header>
    <div className="indicator-pool-toolbar"><label><span>搜索指标、公式或来源</span><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="如：失信、股东变更、行政处罚" /></label><label><span>风险分类</span><select value={category} onChange={(event) => onCategory(event.target.value)}><option value="">全部分类</option>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><div><span>当前结果</span><strong>{filtered.length} 项</strong></div></div>
    <div className="indicator-category-list">{grouped.map((group) => <details key={group.name} open={Boolean(query || category)}><summary><span>{group.name}</span><b>{group.items.length} 项</b><small>{group.items.filter((item) => selection[item.id]?.enabled).length} 项已选</small></summary><div>{group.items.map((item) => {
      const selected = Boolean(selection[item.id]?.enabled);
      return <article className={selected ? "selected" : ""} key={item.id}><label className="indicator-pick"><input type="checkbox" checked={selected} disabled={!editable} onChange={(event) => toggle(item, event.target.checked)} /><span><strong>{item.name}</strong><small>{item.risk_level} · {item.statistics_period} · {item.use_cases.join(" / ")}</small></span></label><p>{item.description}</p><code>{item.scoring.formula}</code><footer><span>{item.data_source}</span><span>{item.field_path}</span>{selected && editable && <label><em>相对权重</em><input type="number" min="0.01" max="100" step="0.1" value={selection[item.id].weight} onChange={(event) => changeWeight(item, Number(event.target.value))} /></label>}</footer></article>;
    })}</div></details>)}</div>
  </section>;
}


type MonitoringClosureProps = {
  summary: MonitoringSummary | null; outcomes: ModelOutcome[]; imports: ModelOutcomeImport[]; issues: MonitoringIssue[]; runs: ModelMonitoringRun[]; schedules: ModelMonitoringSchedule[]; notifications: ModelGovernanceNotification[]; changes: ModelChangeRecord[];
  canManage: boolean; canReview: boolean; busy: string; owner: string; note: string; monitoringPeriod: string; batchPayload: string; importKey: string; importSource: string; importPeriod: string; importExpectedCount: number;
  scheduleCadence: "monthly" | "quarterly"; scheduleTimezone: "Asia/Shanghai" | "UTC"; scheduleEnabled: boolean; scheduleNextRun: string; outcomeForm: OutcomeForm;
  onOwner: (value: string) => void; onNote: (value: string) => void; onMonitoringPeriod: (value: string) => void; onBatchPayload: (value: string) => void; onImportKey: (value: string) => void; onImportSource: (value: string) => void; onImportPeriod: (value: string) => void; onImportExpectedCount: (value: number) => void;
  onScheduleCadence: (value: "monthly" | "quarterly") => void; onScheduleTimezone: (value: "Asia/Shanghai" | "UTC") => void; onScheduleEnabled: (value: boolean) => void; onScheduleNextRun: (value: string) => void; onOutcomeForm: (value: OutcomeForm) => void;
  onIngest: () => void; onIngestBatch: () => void; onSaveSchedule: () => void; onRunDueSchedules: () => void; onVerifyOutcome: (outcome: ModelOutcome, decision: "verify" | "reject") => void; onScan: () => void; onRun: () => void; onReadNotification: (notification: ModelGovernanceNotification) => void; onLinkChange: (issue: MonitoringIssue, changeId: string) => void; onAction: (issue: MonitoringIssue, action: "remediate" | "submit" | "pass" | "fail") => void;
};

function MonitoringClosurePanel({ summary, outcomes, imports, issues, runs, schedules, notifications, changes, canManage, canReview, busy, owner, note, monitoringPeriod, batchPayload, importKey, importSource, importPeriod, importExpectedCount, scheduleCadence, scheduleTimezone, scheduleEnabled, scheduleNextRun, outcomeForm, onOwner, onNote, onMonitoringPeriod, onBatchPayload, onImportKey, onImportSource, onImportPeriod, onImportExpectedCount, onScheduleCadence, onScheduleTimezone, onScheduleEnabled, onScheduleNextRun, onOutcomeForm, onIngest, onIngestBatch, onSaveSchedule, onRunDueSchedules, onVerifyOutcome, onScan, onRun, onReadNotification, onLinkChange, onAction }: MonitoringClosureProps) {
  if (!summary) return <div className="monitoring-closure loading">正在加载结果观察与整改闭环…</div>;
  const readiness = summary.readiness;
  const statusLabel: Record<string, string> = { open: "待整改", in_remediation: "整改中", pending_revalidation: "待复验", closed: "已关闭" };
  const draftChanges = changes.filter((item) => item.status === "draft");
  const latestRun = runs[0];
  const latestImport = imports[0];
  const schedule = schedules[0];
  return <section className="monitoring-closure">
    <div className="governance-subhead"><div><strong>真实结果数据与监控闭环</strong><span>结果观察 → 周期运行 → 异常通知 → 整改 → 独立复验</span></div>{canReview && <div className="monitoring-run-command"><input value={monitoringPeriod} pattern="\d{4}Q[1-4]" onChange={(event) => onMonitoringPeriod(event.target.value)} /><button disabled={busy === "issue-scan"} onClick={onScan}>即时扫描</button><button disabled={busy === "monitoring-run"} onClick={onRun}>{busy === "monitoring-run" ? "运行中…" : "执行监控批次"}</button></div>}</div>
    <div className="monitoring-readiness">
      <div className={readiness.formal_backtest_ready ? "ready" : "pending"}><span>正式回溯门槛</span><strong>{readiness.formal_backtest_ready ? "已达到" : "积累中"}</strong><small>{readiness.summary}</small></div>
      <div><span>已核验真实观察</span><strong>{readiness.observation_count} / {readiness.minimums.observations}</strong><small>已提交 {readiness.submitted_count} · 待核验 {readiness.pending_verification_count}</small></div>
      <div><span>事件 / 非事件</span><strong>{readiness.event_count} / {readiness.non_event_count}</strong><small>最低分别 {readiness.minimums.events} / {readiness.minimums.non_events}</small></div>
      <div><span>当前生效证据</span><strong>{summary.effective_source === "observed_outcome" ? "真实观察" : summary.effective_source === "simulation_proxy" ? "演示代理" : "尚不可测"}</strong><small>未达门槛前不替换正式监控口径</small></div>
    </div>
    <div className="monitoring-operations-grid"><div><span>最近监控批次</span><strong>{latestRun ? `${latestRun.as_of_period} · ${latestRun.status === "completed" ? "已完成" : latestRun.status}` : "尚未运行"}</strong><small>{latestRun ? `${latestRun.trigger_type === "scheduled" ? "定时" : "人工"}触发 · ${latestRun.issue_ids.length} 个问题` : "支持外部调度器使用运行键安全重试"}</small></div><div><span>治理通知</span><strong>{notifications.filter((item) => item.status === "unread").length} 条未读</strong><small>按模型管理员/风控角色隔离投递</small></div><div><span>结果导入对账</span><strong>{latestImport ? importStatusLabel(latestImport.status) : "尚无任务"}</strong><small>{latestImport ? `预期 ${latestImport.expected_count} · 实收 ${latestImport.received_count} · 拒绝 ${latestImport.rejected_count}` : "保存批次级来源与逐行回执"}</small></div><div><span>监控计划</span><strong>{schedule ? `${schedule.cadence === "monthly" ? "每月" : "每季度"} · ${schedule.enabled ? "启用" : "停用"}` : "尚未配置"}</strong><small>{schedule ? `下次 ${formatTime(schedule.next_run_at)} · v${schedule.row_version}` : "由模型管理员设置执行频率"}</small></div></div>
    {(canManage || canReview) && <div className="monitoring-automation"><div className="closure-heading"><strong>周期监控计划</strong><span>外部定时器调用到期扫描，运行键保证安全重试</span></div>{canManage && <div className="schedule-form"><label><span>执行频率</span><select value={scheduleCadence} onChange={(event) => onScheduleCadence(event.target.value as "monthly" | "quarterly")}><option value="monthly">每月</option><option value="quarterly">每季度</option></select></label><label><span>计划时区</span><select value={scheduleTimezone} onChange={(event) => onScheduleTimezone(event.target.value as "Asia/Shanghai" | "UTC")}><option value="Asia/Shanghai">Asia/Shanghai</option><option value="UTC">UTC</option></select></label><label><span>下次执行时间</span><input type="datetime-local" value={scheduleNextRun} onChange={(event) => onScheduleNextRun(event.target.value)} /></label><label className="schedule-enabled"><input type="checkbox" checked={scheduleEnabled} onChange={(event) => onScheduleEnabled(event.target.checked)} /><span>启用计划</span></label><button disabled={busy === "monitoring-schedule"} onClick={onSaveSchedule}>{busy === "monitoring-schedule" ? "保存中…" : schedule ? "更新监控计划" : "创建监控计划"}</button></div>}{canReview && <div className="schedule-run-row"><span>{schedule?.last_status ? `上次执行：${schedule.last_status === "completed" ? "成功" : "失败"}${schedule.last_error ? ` · ${schedule.last_error}` : ""}` : "尚无计划执行记录"}</span><button disabled={busy === "schedule-tick"} onClick={onRunDueSchedules}>{busy === "schedule-tick" ? "扫描中…" : "执行到期计划"}</button></div>}</div>}
    {notifications.length > 0 && <div className="governance-notification-list">{notifications.slice(0, 4).map((notification) => <article className={`${notification.severity} ${notification.status}`} key={notification.id}><div><strong>{notification.title}</strong><p>{notification.message}</p><small>{formatTime(notification.created_at)}</small></div>{notification.status === "unread" && <button disabled={busy === notification.id} onClick={() => onReadNotification(notification)}>确认已读</button>}</article>)}</div>}
    {canManage && <div className="outcome-ingestion">
      <div className="closure-heading"><strong>接入一条到期观察结果</strong><span>来源级观察编号用于幂等控制</span></div>
      <div className="outcome-form">
        <label><span>观察编号</span><input value={outcomeForm.externalId} onChange={(event) => onOutcomeForm({ ...outcomeForm, externalId: event.target.value })} /></label>
        <label><span>客商编号</span><input value={outcomeForm.counterpartyId} onChange={(event) => onOutcomeForm({ ...outcomeForm, counterpartyId: event.target.value })} /></label>
        <label><span>样本期间</span><input value={outcomeForm.period} pattern="\d{4}Q[1-4]" onChange={(event) => onOutcomeForm({ ...outcomeForm, period: event.target.value })} /></label>
        <label><span>预测评分</span><input type="number" min="0" max="100" step="0.1" value={outcomeForm.score} onChange={(event) => onOutcomeForm({ ...outcomeForm, score: Number(event.target.value) })} /></label>
        <label><span>预测 PD</span><input type="number" min="0" max="1" step="0.01" value={outcomeForm.pd} onChange={(event) => onOutcomeForm({ ...outcomeForm, pd: Number(event.target.value) })} /></label>
        <label><span>观察结果</span><select value={outcomeForm.event ? "event" : "non_event"} onChange={(event) => onOutcomeForm({ ...outcomeForm, event: event.target.value === "event" })}><option value="non_event">非事件</option><option value="event">事件/违约</option></select></label>
        <label><span>预测日期</span><input type="date" value={outcomeForm.predictionAt} onChange={(event) => onOutcomeForm({ ...outcomeForm, predictionAt: event.target.value })} /></label>
        <label><span>观察截止</span><input type="date" value={outcomeForm.observationEnd} onChange={(event) => onOutcomeForm({ ...outcomeForm, observationEnd: event.target.value })} /></label>
        <label className="wide"><span>证据引用</span><input value={outcomeForm.evidence} onChange={(event) => onOutcomeForm({ ...outcomeForm, evidence: event.target.value })} /></label>
        <button disabled={busy === "outcome"} onClick={onIngest}>{busy === "outcome" ? "正在写入…" : "保存真实结果"}</button>
      </div>
      <p>最近接入：{outcomes.length ? `${outcomes.at(-1)?.population_period} · ${outcomes.at(-1)?.counterparty_id} · ${outcomes.at(-1)?.observed_event ? "事件" : "非事件"} · ${outcomeVerificationLabel(outcomes.at(-1)?.verification_status)}` : "暂无真实结果记录"}</p>
      <details className="batch-ingestion"><summary>可对账批量 JSON 接入</summary><div className="batch-meta-form"><label><span>导入任务编号</span><input value={importKey} onChange={(event) => onImportKey(event.target.value)} /></label><label><span>数据来源</span><input value={importSource} onChange={(event) => onImportSource(event.target.value)} /></label><label><span>样本期间</span><input value={importPeriod} pattern="\d{4}Q[1-4]" onChange={(event) => onImportPeriod(event.target.value)} /></label><label><span>预期记录数</span><input type="number" min="1" max="500" value={importExpectedCount} onChange={(event) => onImportExpectedCount(Number(event.target.value))} /></label></div><textarea value={batchPayload} onChange={(event) => onBatchPayload(event.target.value)} placeholder='粘贴结果记录数组；每行来源、模型模板和期间需与任务元数据一致，单批最多 500 条' /><button disabled={busy === "outcome-batch"} onClick={onIngestBatch}>{busy === "outcome-batch" ? "对账处理中…" : "创建导入并执行对账"}</button>{imports.length > 0 && <div className="import-history">{imports.slice(0, 3).map((item) => <article className={item.status} key={item.id}><div><strong>{item.import_key}</strong><span>{item.source} · {item.population_period}</span></div><p>预期 {item.expected_count} / 实收 {item.received_count} · 新增 {item.created_count} · 幂等 {item.idempotent_count} · 拒绝 {item.rejected_count}</p><i>{importStatusLabel(item.status)}</i></article>)}</div>}</details>
    </div>}
    {(canManage || canReview) && <div className="closure-controls"><label><span>整改责任人</span><input value={owner} onChange={(event) => onOwner(event.target.value)} /></label><label><span>整改/复验说明</span><input value={note} onChange={(event) => onNote(event.target.value)} /></label></div>}
    {canReview && outcomes.some((item) => item.verification_status === "pending_verification") && <div className="outcome-verification-list"><div className="closure-heading"><strong>结果证据待核验</strong><span>录入人与核验人必须分离</span></div>{outcomes.filter((item) => item.verification_status === "pending_verification").map((outcome) => <article key={outcome.id}><div><strong>{outcome.external_observation_id}</strong><span>{outcome.population_period} · {outcome.counterparty_id}</span><small>评分 {outcome.predicted_score.toFixed(1)} · PD {(outcome.predicted_pd * 100).toFixed(1)}% · {outcome.observed_event ? "事件" : "非事件"}</small><p>{outcome.evidence_reference}</p></div><footer><button className="reject" disabled={busy === outcome.id} onClick={() => onVerifyOutcome(outcome, "reject")}>驳回证据</button><button disabled={busy === outcome.id} onClick={() => onVerifyOutcome(outcome, "verify")}>核验通过</button></footer></article>)}</div>}
    <div className="monitoring-issue-list">
      <div className="closure-heading"><strong>监控问题台账</strong><span>{issues.filter((item) => item.status !== "closed").length} 个未关闭 · {issues.length} 个累计</span></div>
      {issues.length ? issues.map((issue) => <article className={`${issue.severity} ${issue.status}`} key={issue.id}>
        <header><div><i>{issue.severity === "critical" ? "高" : "中"}</i><strong>{issue.title}</strong><span>{statusLabel[issue.status]}</span></div><small>v{issue.row_version}</small></header>
        <p>{issue.description}</p><div className="issue-meta"><span>{evidenceLevelLabel(issue.evidence_level)}</span><span>{issue.metric_value === null ? "待补充数据" : `指标值 ${issue.metric_value.toFixed(4)}`}</span><span>{issue.owner ?? "待分配"}</span><span>{issue.due_at ? `截止 ${formatTime(issue.due_at)}` : "尚未设置 SLA"}</span></div>
        {issue.remediation_plan && <aside>整改计划：{issue.remediation_plan}</aside>}{issue.remediation_result && <aside>整改结果：{issue.remediation_result}</aside>}{issue.revalidation_conclusion && <aside>复验结论：{issue.revalidation_conclusion}</aside>}
        <footer>{canManage && !issue.linked_change_id && draftChanges.length === 1 && <button className="secondary" disabled={busy === issue.id} onClick={() => onLinkChange(issue, draftChanges[0].id)}>关联 {draftChanges[0].candidate_version}</button>}{canManage && !issue.linked_change_id && draftChanges.length > 1 && <span>存在多个重校准草稿，请先在变更单中确认</span>}{issue.linked_change_id && <span>已关联变更单</span>}{canManage && issue.status === "open" && <button disabled={busy === issue.id} onClick={() => onAction(issue, "remediate")}>制定整改</button>}{canManage && issue.status === "in_remediation" && <button disabled={busy === issue.id} onClick={() => onAction(issue, "submit")}>提交复验</button>}{canReview && issue.status === "pending_revalidation" && <><button className="reject" disabled={busy === issue.id} onClick={() => onAction(issue, "fail")}>退回整改</button><button disabled={busy === issue.id} onClick={() => onAction(issue, "pass")}>复验通过</button></>}</footer>
      </article>) : <div className="governance-empty">尚未生成监控问题；复核角色可执行一次监控扫描。</div>}
    </div>
  </section>;
}


function ModelValidationDashboard({ report, loading }: { report: ModelValidationReport | null; loading: boolean }) {
  if (loading || !report) return <div className="validation-dashboard loading">正在生成模型验证快照…</div>;
  return <div className={`validation-dashboard ${report.release_gate.status}`}>
    <header><div><span>MODEL VALIDATION</span><h3>校准与验证监控</h3><p>{report.model_version} · 目标样本 {report.sample_profile.total_count} / 组合 {report.sample_profile.portfolio_count}</p></div><div className="release-gate"><i>{report.release_gate.passed ? "PASS" : "BLOCK"}</i><strong>{report.release_gate.passed ? "满足预发布门槛" : "暂不允许提交发布"}</strong><small>{report.release_gate.summary}</small></div></header>
    <div className="validation-metrics">{report.metrics.map((metric) => <article className={metric.status} key={metric.key}><div><span>{metric.label}</span><i>{validationStatusLabel(metric.status)}</i></div><strong>{formatValidationMetric(metric.value, metric.unit)}</strong><p>{metric.description}</p></article>)}</div>
    <div className="validation-detail-grid">
      <section><h4>发布硬门槛</h4><div className="gate-list">{report.release_gate.gates.map((gate) => <div className={gate.passed ? "pass" : "fail"} key={gate.key}><i>{gate.passed ? "✓" : "!"}</i><span>{gate.label}<small>实际 {formatGateActual(gate.actual, gate.key)} · 要求 {gate.threshold}</small></span></div>)}</div></section>
      <section className="monitoring-section"><h4>等级分布与跨期监控 {report.monitoring.dataset && <i>{evidenceLevelLabel(report.monitoring.dataset.evidence_level)}</i>}</h4><div className="rating-distribution">{Object.entries(report.score_distribution.rating_counts).map(([rating, count]) => <span key={rating}><b>{rating}</b><i style={{ width: `${Math.max(8, count / Math.max(report.sample_profile.eligible_count, 1) * 100)}%` }} /><small>{count}</small></span>)}</div>{report.monitoring.performance_metrics.length ? <><div className="monitoring-metric-grid">{report.monitoring.performance_metrics.map((metric) => <div className={metric.status} key={metric.key}><span>{metric.label}</span><strong>{metric.value === null ? "不可测" : metric.value.toFixed(4)}</strong><small>{validationStatusLabel(metric.status)}</small></div>)}</div><p className="monitoring-note">{report.monitoring.dataset?.baseline_period} → {report.monitoring.dataset?.current_period} · 回溯样本 {report.monitoring.backtesting.sample_count} 个<br />实际事件率 {formatOptionalPercent(report.monitoring.backtesting.actual_event_rate)} · 预期事件率 {formatOptionalPercent(report.monitoring.backtesting.expected_event_rate)}</p><p className="evidence-warning">{report.monitoring.dataset?.label_definition}</p></> : <p className="monitoring-note">PSI：尚不可测 · {report.monitoring.population_stability.reason}<br />{report.monitoring.recommended_frequency}</p>}</section>
      <section><h4>验证结论与整改</h4><div className="validation-findings">{report.findings.map((finding) => <p key={finding}>{finding}</p>)}</div></section>
    </div>
  </div>;
}


function formatValidationMetric(value: number | null, unit: "percent" | "grade"): string {
  if (value === null) return "不可测";
  return unit === "percent" ? `${(value * 100).toFixed(1)}%` : `${value.toFixed(2)} 档`;
}
function validationStatusLabel(status: string): string { return ({ pass: "通过", warn: "关注", fail: "未通过", not_testable: "不可测" } as Record<string, string>)[status] ?? status; }
function formatGateActual(value: number, key: string): string { return key === "coverage" ? `${(value * 100).toFixed(1)}%` : String(value); }
function formatOptionalPercent(value?: number): string { return value === undefined ? "—" : `${(value * 100).toFixed(1)}%`; }
function evidenceLevelLabel(level: string): string {
  if (level === "simulation_proxy") return "演示代理证据";
  if (level === "observed_outcome") return "真实观察证据";
  return "待核验证据";
}
function outcomeVerificationLabel(status?: string): string { return ({ pending_verification: "待风控核验", verified: "已核验", rejected: "已驳回" } as Record<string, string>)[status ?? ""] ?? "待核验"; }
function importStatusLabel(status: ModelOutcomeImport["status"]): string { return ({ processing: "处理中", completed: "对账一致", completed_with_exceptions: "存在差异", failed: "执行失败" } as Record<ModelOutcomeImport["status"], string>)[status]; }
function toLocalInputValue(value: string): string { const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16); }
function defaultNextRunValue(): string { return toLocalInputValue(new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()); }


function formatTime(value: string | null): string { return value ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "—"; }
