import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { MonitoringDiffSlaDashboard, RuleCenterReplayComparison, TenantMonitoringDiffCase, TenantMonitoringRun, TenantOutcomeImport, TenantOutcomeLabel, TenantOutcomeLabelDefinition, TenantRolloutEvaluation, TenantRolloutPolicy, TenantRolloutScan, TenantRoutingDecision, TenantSupervisedEvaluation } from "./types";


type Notice = { kind: "error" | "success"; text: string };
const statusLabels: Record<string, string> = { draft: "草稿", pending_review: "待复核", scheduled: "待生效", active: "灰度中", paused: "已暂停", rolled_back: "已回滚", completed: "已结束", rejected: "已驳回", ready_to_activate: "可激活", window_ended: "观察期结束" };
const incidentLabels: Record<string, string> = { open: "待确认", acknowledged: "待提交整改", resolution_pending: "待独立复核", resolved: "已关闭" };
const scanActionLabels: Record<string, string> = { activate: "排期生效", evaluate: "周期评估", close: "观察期收口" };
const evaluationStatusLabels: Record<string, string> = { draft: "草稿", pending_review: "待复核", approved: "已批准", rejected: "已驳回" };
const governanceDecisionLabels: Record<string, string> = { retain_champion: "保留 Champion", promote_candidate: "建议晋级 Challenger", reject_candidate: "拒绝候选模型", continue_observation: "继续观察" };
const definitionStatusLabels: Record<string, string> = { draft: "草稿", pending_review: "待复核", published: "已发布", rejected: "已驳回", retired: "已退役" };
const monitoringGovernanceLabels: Record<string, string> = { draft: "草稿", pending_review: "待复核", published: "已发布", rejected: "已驳回", retracted: "已撤回" };
const monitoringGateLabels: Record<string, string> = { accepted: "门禁通过", at_risk: "诊断观察", blocked: "门禁阻断", evidence_stale: "证据失效" };
const diffCaseStatusLabels: Record<string, string> = { open: "待领取", assigned: "处理中", recomputing: "重算中", pending_disposition: "待处置", resolved: "已关闭", rejected: "已驳回" };
const diffCaseSeverityLabels: Record<string, string> = { info: "一般", warning: "关注", critical: "重大" };
const diffSlaStatusLabels: Record<string, string> = { normal: "正常", due_soon: "临期", overdue: "已逾期", escalated: "严重逾期", stopped: "已停止" };
const diffDispositionLabels: Record<string, string> = { accepted_change: "接受变化", data_issue: "数据问题", calculation_issue: "计算问题", model_drift: "模型漂移", policy_threshold_change_required: "调整阈值政策", superseded: "已被新证据替代" };


export default function TenantRolloutPanel({ modelKey, canManage, canReview, onNotice }: { modelKey: string; canManage: boolean; canReview: boolean; onNotice: (notice: Notice) => void }) {
  const [policies, setPolicies] = useState<TenantRolloutPolicy[]>([]);
  const [comparisons, setComparisons] = useState<RuleCenterReplayComparison[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [routes, setRoutes] = useState<TenantRoutingDecision[]>([]);
  const [evaluations, setEvaluations] = useState<TenantRolloutEvaluation[]>([]);
  const [outcomes, setOutcomes] = useState<TenantOutcomeLabel[]>([]);
  const [outcomeImports, setOutcomeImports] = useState<TenantOutcomeImport[]>([]);
  const [definitions, setDefinitions] = useState<TenantOutcomeLabelDefinition[]>([]);
  const [supervisedEvaluations, setSupervisedEvaluations] = useState<TenantSupervisedEvaluation[]>([]);
  const [monitoringRuns, setMonitoringRuns] = useState<TenantMonitoringRun[]>([]);
  const [monitoringDiffCases, setMonitoringDiffCases] = useState<TenantMonitoringDiffCase[]>([]);
  const [diffSlaDashboard, setDiffSlaDashboard] = useState<MonitoringDiffSlaDashboard | null>(null);
  const [scans, setScans] = useState<TenantRolloutScan[]>([]);
  const [comparisonId, setComparisonId] = useState("");
  const [trafficPercent, setTrafficPercent] = useState(10);
  const [windowMinutes, setWindowMinutes] = useState(1440);
  const [minSampleSize, setMinSampleSize] = useState(100);
  const [reason, setReason] = useState("基于固定回放证据开展小流量观察，并配置自动保护阈值");
  const [reviewComment, setReviewComment] = useState("双侧资产、样本证据与在线保护阈值已独立复核");
  const [incidentNote, setIncidentNote] = useState("");
  const [selectedDefinitionId, setSelectedDefinitionId] = useState("");
  const [outcomeForm, setOutcomeForm] = useState({ routeId: "", externalId: "", counterpartyId: "", source: "贷后结果系统", observedEvent: false, observationEnd: new Date().toISOString().slice(0, 10), evidenceReference: "post-loan://outcome/", lossAmount: "", exposureAmount: "" });
  const [batchForm, setBatchForm] = useState({ importKey: `OUTCOME-${Date.now()}`, source: "贷后结果仓", expectedCount: 1, payload: "[]" });
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvImportKey, setCsvImportKey] = useState(`CSV-${Date.now()}`);
  const [definitionForm, setDefinitionForm] = useState({ code: "default_90d", name: "90 天违约口径", description: "观察企业在决策后 90 天内是否发生约定违约事件。", eventType: "default" as "default" | "delinquency" | "loss" | "recovery", observationDays: 90, graceDays: 0, sources: "贷后核心系统,贷后结果系统,贷后结果仓", requireLoss: false, requireExposure: false });
  const [correctingId, setCorrectingId] = useState("");
  const [correctionForm, setCorrectionForm] = useState({ externalId: "", observedEvent: false, observationEnd: new Date().toISOString().slice(0, 10), lossAmount: "", exposureAmount: "", evidenceReference: "post-loan://correction/", reason: "经贷后工单复核，原始结果事实需要冲正并保留版本链" });
  const [supervisedConfig, setSupervisedConfig] = useState({ min_mature_samples: 30, min_events: 5, min_non_events: 5, min_reliable_samples_per_arm: 30, high_risk_threshold: 0.4, bootstrap_resamples: 1000 });
  const [selectedMonitoringRunId, setSelectedMonitoringRunId] = useState("");
  const [diffCaseReason, setDiffCaseReason] = useState("监控快照差异需要固定口径重算并形成独立处置结论");
  const [diffDisposition, setDiffDisposition] = useState<NonNullable<TenantMonitoringDiffCase["disposition"]>>("accepted_change");
  const [diffConclusion, setDiffConclusion] = useState("已核对原始差异、固定口径重算结果及业务影响，同意关闭本次差异工单");
  const [upgradeReason, setUpgradeReason] = useState("基于已批准的延迟监督证据生成 Challenger 晋级候选草稿");
  const [restartChangeId, setRestartChangeId] = useState("");
  const [governanceDecision, setGovernanceDecision] = useState<"retain_champion" | "promote_candidate" | "reject_candidate" | "continue_observation">("continue_observation");
  const [busy, setBusy] = useState("");
  const [thresholds, setThresholds] = useState({ max_challenger_failure_rate: 0.05, max_latency_increase_ratio: 0.5, max_score_psi: 0.25, max_admission_distribution_shift: 0.15 });

  const eligibleComparisons = useMemo(() => comparisons.filter((item) => item.champion_model_key === modelKey && ["passed", "exception_approved"].includes(item.effective_status)), [comparisons, modelKey]);
  const selected = policies.find((item) => item.id === selectedId) ?? policies[0];
  const challengerRoutes = routes.filter((item) => item.selected_arm === "challenger");
  const latestEvaluation = evaluations[0];
  const latestSupervised = supervisedEvaluations[0];
  const activeOutcomes = outcomes.filter((item) => item.record_status === "active");
  const publishedDefinitions = definitions.filter((item) => item.status === "published" && item.is_active);
  const selectedDefinition = publishedDefinitions.find((item) => item.id === selectedDefinitionId) ?? publishedDefinitions[0];
  const linkedRouteIds = new Set(activeOutcomes.map((item) => item.routing_decision_id));
  const eligibleOutcomeRoutes = routes.filter((item) => item.status === "completed" && item.score !== null && item.evidence_hash && !linkedRouteIds.has(item.id));

  const reload = useCallback(async () => {
    try {
      const [policyRows, comparisonRows, scanRows, definitionRows, slaDashboard] = await Promise.all([api.tenantRollouts(modelKey), api.ruleCenterReplayComparisons(), api.tenantRolloutScans(), api.outcomeLabelDefinitions(), api.tenantMonitoringDiffSlaDashboard()]);
      setPolicies(policyRows);
      setComparisons(comparisonRows);
      setScans(scanRows);
      setDefinitions(definitionRows);
      setDiffSlaDashboard(slaDashboard);
      setSelectedDefinitionId((current) => current && definitionRows.some((item) => item.id === current && item.status === "published" && item.is_active) ? current : definitionRows.find((item) => item.status === "published" && item.is_active && item.applicable_model_keys.includes(modelKey))?.id ?? definitionRows.find((item) => item.status === "published" && item.is_active)?.id ?? "");
      setSelectedId((current) => current && policyRows.some((item) => item.id === current) ? current : policyRows[0]?.id ?? "");
      setComparisonId((current) => current || comparisonRows.find((item) => item.champion_model_key === modelKey && ["passed", "exception_approved"].includes(item.effective_status))?.id || "");
    } catch (error) { onNotice({ kind: "error", text: message(error, "灰度策略加载失败") }); }
  }, [modelKey, onNotice]);

  const loadEvidence = useCallback(async (policyId: string) => {
    if (!policyId) { setRoutes([]); setEvaluations([]); setOutcomes([]); setOutcomeImports([]); setSupervisedEvaluations([]); setMonitoringRuns([]); setMonitoringDiffCases([]); return; }
    try {
      const [routeRows, evaluationRows, outcomeRows, importRows, supervisedRows, monitoringRows, diffCases] = await Promise.all([api.tenantRolloutRoutes(policyId), api.tenantRolloutEvaluations(policyId), api.tenantRolloutOutcomes(policyId), api.tenantRolloutOutcomeImports(policyId), api.tenantSupervisedEvaluations(policyId), api.tenantMonitoringRuns(policyId), api.tenantMonitoringDiffCases(policyId)]);
      setRoutes(routeRows); setEvaluations(evaluationRows); setOutcomes(outcomeRows); setOutcomeImports(importRows); setSupervisedEvaluations(supervisedRows); setMonitoringRuns(monitoringRows); setMonitoringDiffCases(diffCases);
      setSelectedMonitoringRunId((current) => current && monitoringRows.some((item) => item.id === current && item.governance_status === "published") ? current : monitoringRows.find((item) => item.governance_status === "published")?.id ?? "");
      setOutcomeForm((current) => ({ ...current, routeId: current.routeId && routeRows.some((item) => item.id === current.routeId) ? current.routeId : routeRows.find((item) => item.status === "completed" && item.score !== null)?.id ?? "" }));
    } catch (error) { onNotice({ kind: "error", text: message(error, "在线灰度证据加载失败") }); }
  }, [onNotice]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => { void loadEvidence(selected?.id ?? ""); }, [selected?.id, loadEvidence]);

  async function createPolicy() {
    if (!comparisonId) return onNotice({ kind: "error", text: "请先生成一条门禁通过的固定双模型回放证据" });
    const now = new Date();
    setBusy("create");
    try {
      const created = await api.createTenantRollout({
        name: `${modelKey} 候选模型 ${trafficPercent}% 灰度`, comparison_run_id: comparisonId,
        routing_key_field: "counterparty_id", traffic_basis_points: Math.round(trafficPercent * 100),
        observation_window_minutes: windowMinutes, min_sample_size: minSampleSize, thresholds,
        starts_at: new Date(now.getTime() - 60_000).toISOString(), ends_at: new Date(now.getTime() + 7 * 86_400_000).toISOString(), reason,
      });
      await reload(); setSelectedId(created.id);
      onNotice({ kind: "success", text: "灰度草稿已创建，双侧资产图与回放证据已冻结" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "灰度策略创建失败") }); }
    finally { setBusy(""); }
  }

  async function act(policy: TenantRolloutPolicy, action: "submit" | "approve" | "reject" | "pause" | "resume" | "rollback" | "complete" | "evaluate") {
    setBusy(`${policy.id}:${action}`);
    try {
      if (action === "submit") await api.submitTenantRollout(policy.id, policy.row_version, reason);
      else if (action === "approve" || action === "reject") await api.reviewTenantRollout(policy.id, policy.row_version, action, reviewComment);
      else if (action === "evaluate") await api.evaluateTenantRollout(policy.id);
      else await api.changeTenantRolloutStatus(policy.id, policy.row_version, action, action === "rollback" ? "人工触发保护性回滚，立即切回 Champion" : reviewComment);
      await reload(); await loadEvidence(policy.id);
      onNotice({ kind: "success", text: action === "evaluate" ? "在线保护阈值已重新评估" : "灰度策略状态已更新" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "灰度策略操作失败") }); }
    finally { setBusy(""); }
  }

  async function scan() {
    setBusy("scan");
    try {
      const result = await api.scanTenantRollouts();
      await reload();
      if (selected) await loadEvidence(selected.id);
      onNotice({ kind: result.run.status === "failed" || result.run.status === "partial" ? "error" : "success", text: `灰度扫描${result.run.status === "no_due" ? "无待处理策略" : "已记录执行证据"}` });
    } catch (error) { onNotice({ kind: "error", text: message(error, "灰度扫描失败") }); }
    finally { setBusy(""); }
  }

  async function restartAfterRelease(policy: TenantRolloutPolicy) {
    if (!restartChangeId.trim() || reason.trim().length < 5) return onNotice({ kind: "error", text: "请输入已发布模型变更单编号和重启依据" });
    setBusy(`restart:${policy.id}`);
    try {
      const result = await api.restartTenantRolloutAfterRelease(policy.id, policy.row_version, restartChangeId.trim(), reason.trim());
      await reload();
      setSelectedId(result.policy.id);
      onNotice({ kind: "success", text: `已创建发布后重启灰度草稿 ${result.policy.id.slice(0, 8)}，尚未恢复流量` });
    } catch (error) { onNotice({ kind: "error", text: message(error, "发布后灰度重启失败") }); }
    finally { setBusy(""); }
  }

  async function actOnIncident(policy: TenantRolloutPolicy, action: "acknowledge" | "request_resolution" | "approve_resolution") {
    if (incidentNote.trim().length < 5) return onNotice({ kind: "error", text: "请填写至少 5 个字符的事故核查或整改依据" });
    setBusy(`${policy.id}:${action}`);
    try {
      await api.actOnTenantRolloutIncident(policy.id, policy.row_version, action, incidentNote.trim());
      await reload(); setIncidentNote("");
      onNotice({ kind: "success", text: action === "approve_resolution" ? "事故已独立复核关闭，原灰度流量不会自动恢复" : "事故状态已更新" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "事故处置失败") }); }
    finally { setBusy(""); }
  }

  async function ingestOutcome() {
    if (!selected || !selectedDefinition || !outcomeForm.routeId || !outcomeForm.counterpartyId.trim() || !outcomeForm.externalId.trim()) return onNotice({ kind: "error", text: "请选择已发布标签口径与历史路由，并填写企业编号和外部标签编号" });
    setBusy("outcome-create");
    try {
      await api.createTenantRolloutOutcome(selected.id, {
        source: outcomeForm.source, external_label_id: outcomeForm.externalId.trim(), routing_decision_id: outcomeForm.routeId,
        counterparty_id: outcomeForm.counterpartyId.trim(), label_definition_id: selectedDefinition.id, observed_event: outcomeForm.observedEvent,
        observation_end: new Date(`${outcomeForm.observationEnd}T23:59:59+08:00`).toISOString(),
        loss_amount: outcomeForm.lossAmount === "" ? undefined : Number(outcomeForm.lossAmount),
        exposure_amount: outcomeForm.exposureAmount === "" ? undefined : Number(outcomeForm.exposureAmount),
        evidence_reference: outcomeForm.evidenceReference.trim(),
      });
      await loadEvidence(selected.id);
      setOutcomeForm((current) => ({ ...current, externalId: "", counterpartyId: "", lossAmount: "", exposureAmount: "" }));
      onNotice({ kind: "success", text: "结果标签已绑定冻结路由，等待独立核验" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "结果标签导入失败") }); }
    finally { setBusy(""); }
  }

  function prepareBatchTemplate() {
    const rows = eligibleOutcomeRoutes.slice(0, 20).map((route, index) => ({
      external_label_id: `BATCH-${Date.now()}-${index + 1}`,
      routing_decision_id: route.id,
      counterparty_id: "请填写历史路由对应企业编号",
      observed_event: false,
      observation_end: new Date().toISOString(),
      loss_amount: 0,
      exposure_amount: 100000,
      evidence_reference: `post-loan://batch/${index + 1}`,
    }));
    setBatchForm((current) => ({ ...current, expectedCount: Math.max(1, rows.length), payload: JSON.stringify(rows, null, 2) }));
  }

  async function ingestOutcomeBatch() {
    if (!selected || !selectedDefinition) return onNotice({ kind: "error", text: "请先选择一个已发布标签口径" });
    let rows: Array<{ external_label_id: string; routing_decision_id: string; counterparty_id: string; observed_event: boolean; observation_end: string; loss_amount?: number; exposure_amount?: number; evidence_reference: string }>;
    try {
      const parsed: unknown = JSON.parse(batchForm.payload);
      if (!Array.isArray(parsed) || parsed.length === 0) throw new Error("批次数据必须是非空 JSON 数组");
      rows = parsed as typeof rows;
    } catch (error) {
      return onNotice({ kind: "error", text: message(error, "批次 JSON 格式无效") });
    }
    setBusy("outcome-batch");
    try {
      const result = await api.createTenantRolloutOutcomeImport(selected.id, {
        import_key: batchForm.importKey.trim(), source: batchForm.source.trim(), label_definition_id: selectedDefinition.id,
        expected_count: batchForm.expectedCount, outcomes: rows,
      });
      await loadEvidence(selected.id);
      setBatchForm((current) => ({ ...current, importKey: `OUTCOME-${Date.now()}` }));
      onNotice({ kind: result.status === "completed" ? "success" : "error", text: `批次完成：新增 ${result.created_count}、幂等 ${result.idempotent_count}、拒绝 ${result.rejected_count}` });
    } catch (error) { onNotice({ kind: "error", text: message(error, "结果标签批次导入失败") }); }
    finally { setBusy(""); }
  }

  async function ingestOutcomeCsv() {
    if (!selected || !selectedDefinition || !csvFile) return onNotice({ kind: "error", text: "请选择 CSV 文件并确认已发布标签口径" });
    setBusy("outcome-csv");
    try {
      const result = await api.uploadTenantRolloutOutcomeCsv(selected.id, {
        file: csvFile, importKey: csvImportKey.trim(), source: batchForm.source.trim(), labelDefinitionId: selectedDefinition.id, expectedCount: batchForm.expectedCount,
      });
      await loadEvidence(selected.id);
      setCsvFile(null); setCsvImportKey(`CSV-${Date.now()}`);
      onNotice({ kind: result.status === "completed" ? "success" : "error", text: `CSV 校验并导入完成：${result.file.row_count} 行，新增 ${result.created_count}、拒绝 ${result.rejected_count}` });
    } catch (error) { onNotice({ kind: "error", text: message(error, "CSV 标签导入失败") }); }
    finally { setBusy(""); }
  }

  async function verifyOutcome(item: TenantOutcomeLabel, decision: "verify" | "reject") {
    if (!selected) return;
    setBusy(`outcome:${item.id}`);
    try {
      await api.verifyTenantRolloutOutcome(selected.id, item.id, item.row_version, decision, reviewComment);
      await loadEvidence(selected.id);
      onNotice({ kind: "success", text: decision === "verify" ? "标签已核验，成熟后可进入监督评估" : "标签已驳回，不会进入监督评估" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "结果标签核验失败") }); }
    finally { setBusy(""); }
  }

  function beginCorrection(item: TenantOutcomeLabel) {
    setCorrectingId(item.id);
    setCorrectionForm({
      externalId: `${item.external_label_id}-CORR-${Date.now()}`,
      observedEvent: item.observed_event,
      observationEnd: item.observation_end.slice(0, 10),
      lossAmount: item.loss_amount === null ? "" : String(item.loss_amount),
      exposureAmount: item.exposure_amount === null ? "" : String(item.exposure_amount),
      evidenceReference: item.evidence_reference,
      reason: "经贷后工单复核，原始结果事实需要冲正并保留版本链",
    });
  }

  async function correctOutcome(item: TenantOutcomeLabel) {
    if (!selected || correctionForm.reason.trim().length < 5) return onNotice({ kind: "error", text: "请填写至少 5 个字符的冲正依据" });
    setBusy(`correct:${item.id}`);
    try {
      await api.correctTenantRolloutOutcome(selected.id, item.id, {
        expected_row_version: item.row_version,
        external_label_id: correctionForm.externalId.trim(), observed_event: correctionForm.observedEvent,
        observation_end: new Date(`${correctionForm.observationEnd}T23:59:59+08:00`).toISOString(),
        loss_amount: correctionForm.lossAmount === "" ? undefined : Number(correctionForm.lossAmount),
        exposure_amount: correctionForm.exposureAmount === "" ? undefined : Number(correctionForm.exposureAmount),
        evidence_reference: correctionForm.evidenceReference.trim(), reason: correctionForm.reason.trim(),
      });
      setCorrectingId(""); await loadEvidence(selected.id);
      onNotice({ kind: "success", text: "冲正版本已建立，旧标签保留，新标签需重新独立核验" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "结果标签冲正失败") }); }
    finally { setBusy(""); }
  }

  async function evaluateSupervised() {
    if (!selected || !selectedDefinition) return onNotice({ kind: "error", text: "请先选择本次监督评估使用的已发布标签口径" });
    setBusy("supervised-evaluate");
    try {
      const selectedMonitoringRun = monitoringRuns.find((item) => item.id === selectedMonitoringRunId);
      const result = await api.evaluateTenantSupervisedOutcomes(selected.id, { ...supervisedConfig, evaluation_as_of: selectedMonitoringRun?.observed_to, label_definition_id: selectedDefinition.id, tenant_monitoring_run_id: selectedMonitoringRunId || undefined });
      await loadEvidence(selected.id);
      onNotice({ kind: result.evidence_level === "supervised" ? "success" : "error", text: result.evidence_level === "supervised" ? "延迟监督证据已生成" : "监督样本尚未达到门槛，已保存降级证据" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "监督评估失败") }); }
    finally { setBusy(""); }
  }

  async function submitMonitoringRun(item: TenantMonitoringRun) {
    if (!selected || reviewComment.trim().length < 5) return onNotice({ kind: "error", text: "请填写至少 5 个字符的监控快照提交说明" });
    setBusy(`monitoring-submit:${item.id}`);
    try { await api.submitTenantMonitoringRun(selected.id, item.id, item.row_version, reviewComment.trim()); await loadEvidence(selected.id); onNotice({ kind: "success", text: "监控快照已提交独立复核" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "监控快照提交失败") }); }
    finally { setBusy(""); }
  }

  async function reviewMonitoringRun(item: TenantMonitoringRun, decision: "approve" | "reject") {
    if (!selected || reviewComment.trim().length < 5) return onNotice({ kind: "error", text: "请填写至少 5 个字符的监控快照复核意见" });
    setBusy(`monitoring-review:${item.id}`);
    try { await api.reviewTenantMonitoringRun(selected.id, item.id, item.row_version, decision, reviewComment.trim()); await loadEvidence(selected.id); onNotice({ kind: "success", text: decision === "approve" ? "监控快照已发布，可用于监督评估" : "监控快照已驳回" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "监控快照复核失败") }); }
    finally { setBusy(""); }
  }

  async function retractMonitoringRun(item: TenantMonitoringRun) {
    if (!selected || reason.trim().length < 5) return onNotice({ kind: "error", text: "请填写至少 5 个字符的撤回原因" });
    setBusy(`monitoring-retract:${item.id}`);
    try { await api.retractTenantMonitoringRun(selected.id, item.id, item.row_version, reason.trim()); await loadEvidence(selected.id); onNotice({ kind: "success", text: "监控快照已撤回，不能再绑定监督评估" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "监控快照撤回失败") }); }
    finally { setBusy(""); }
  }

  async function showMonitoringDiff(item: TenantMonitoringRun) {
    if (!selected) return;
    const baseline = monitoringRuns.find((candidate) => candidate.id !== item.id && candidate.model_key === item.model_key && candidate.model_version === item.model_version && new Date(candidate.observed_to).getTime() < new Date(item.observed_to).getTime());
    if (!baseline) return onNotice({ kind: "error", text: "当前没有同模型历史快照可供比较" });
    setBusy(`monitoring-diff:${item.id}`);
    try { const diff = await api.tenantMonitoringRunDiff(selected.id, item.id, baseline.id); onNotice({ kind: "success", text: `监控差异已计算，哈希 ${diff.diff_hash.slice(0, 16)}` }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "监控快照差异计算失败") }); }
    finally { setBusy(""); }
  }

  async function createMonitoringDiffCase(item: TenantMonitoringRun) {
    if (!selected || diffCaseReason.trim().length < 5) return onNotice({ kind: "error", text: "请填写至少 5 个字符的差异立案原因" });
    const baseline = monitoringRuns.find((candidate) => candidate.id !== item.id && candidate.model_key === item.model_key && candidate.model_version === item.model_version && new Date(candidate.observed_to).getTime() < new Date(item.observed_to).getTime());
    if (!baseline) return onNotice({ kind: "error", text: "当前没有同模型历史快照可供立案" });
    setBusy(`monitoring-diff-case:${item.id}`);
    try {
      const created = await api.createTenantMonitoringDiffCase(selected.id, { base_run_id: item.id, against_run_id: baseline.id, reason: diffCaseReason.trim() });
      await loadEvidence(selected.id);
      onNotice({ kind: "success", text: created.idempotent ? "该差异已登记，未重复创建工单" : "差异工单已登记并进入处置台账" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "差异工单登记失败") }); }
    finally { setBusy(""); }
  }

  async function assignMonitoringDiffCase(item: TenantMonitoringDiffCase) {
    if (!selected || diffCaseReason.trim().length < 5) return;
    setBusy(`diff-assign:${item.id}`);
    try { await api.assignTenantMonitoringDiffCase(selected.id, item.id, item.row_version, diffCaseReason.trim()); await loadEvidence(selected.id); onNotice({ kind: "success", text: "差异工单已领取" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "差异工单领取失败") }); }
    finally { setBusy(""); }
  }

  async function recomputeMonitoringDiffCase(item: TenantMonitoringDiffCase) {
    if (!selected || diffCaseReason.trim().length < 5) return;
    setBusy(`diff-recompute:${item.id}`);
    try { await api.recomputeTenantMonitoringDiffCase(selected.id, item.id, item.row_version, diffCaseReason.trim()); await loadEvidence(selected.id); onNotice({ kind: "success", text: "固定截止时间和标签口径的重算草稿已生成" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "差异重算失败") }); }
    finally { setBusy(""); }
  }

  async function disposeMonitoringDiffCase(item: TenantMonitoringDiffCase) {
    if (!selected || diffConclusion.trim().length < 5) return onNotice({ kind: "error", text: "请填写至少 5 个字符的独立处置结论" });
    setBusy(`diff-dispose:${item.id}`);
    try { await api.disposeTenantMonitoringDiffCase(selected.id, item.id, item.row_version, diffDisposition, diffConclusion.trim()); await loadEvidence(selected.id); onNotice({ kind: "success", text: "差异工单已独立处置并关闭" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "差异工单处置失败") }); }
    finally { setBusy(""); }
  }

  async function generateMonitoringRuns() {
    if (!selected || !selectedDefinition) return onNotice({ kind: "error", text: "请先选择适用于当前双模型的已发布标签口径" });
    setBusy("monitoring-generate");
    try { const result = await api.generateTenantMonitoringRuns(selected.id, selectedDefinition.id); await loadEvidence(selected.id); onNotice({ kind: "success", text: result.idempotent ? "监控快照已存在，未重复生成" : "已生成 Champion/Challenger 监控草稿，等待双人复核" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "监控快照生成失败") }); }
    finally { setBusy(""); }
  }

  async function scanMonitoringGates() {
    setBusy("monitoring-gate-scan");
    try {
      const result = await api.scanTenantMonitoringGates();
      if (selected) await loadEvidence(selected.id);
      onNotice({ kind: "success", text: `门禁扫描完成：通过 ${result.accepted_count}，风险 ${result.at_risk_count}，阻断 ${result.blocked_count}，证据失效 ${result.stale_count}` });
    } catch (error) { onNotice({ kind: "error", text: message(error, "监控门禁扫描失败") }); }
    finally { setBusy(""); }
  }

  async function scanMonitoringDiffSla() {
    setBusy("monitoring-diff-sla-scan");
    try {
      const result = await api.scanTenantMonitoringDiffSla();
      const dashboard = await api.tenantMonitoringDiffSlaDashboard();
      setDiffSlaDashboard(dashboard);
      if (selected) await loadEvidence(selected.id);
      onNotice({ kind: "success", text: `差异 SLA 扫描完成：临期 ${result.due_soon}，逾期 ${result.overdue}，升级 ${result.escalated}，新增提醒 ${result.notifications_created}` });
    } catch (error) { onNotice({ kind: "error", text: message(error, "差异工单 SLA 扫描失败") }); }
    finally { setBusy(""); }
  }

  async function submitSupervised(item: TenantSupervisedEvaluation) {
    if (!selected) return;
    setBusy(`supervised-submit:${item.id}`);
    try {
      await api.submitTenantSupervisedEvaluation(selected.id, item.id, item.row_version, reviewComment);
      await loadEvidence(selected.id);
      onNotice({ kind: "success", text: "监督结论已提交独立复核" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "监督结论提交失败") }); }
    finally { setBusy(""); }
  }

  async function reviewSupervised(item: TenantSupervisedEvaluation, decision: "approve" | "reject") {
    if (!selected) return;
    setBusy(`supervised-review:${item.id}`);
    try {
      await api.reviewTenantSupervisedEvaluation(selected.id, item.id, item.row_version, decision, decision === "approve" ? governanceDecision : null, reviewComment);
      await loadEvidence(selected.id); await reload();
      onNotice({ kind: "success", text: decision === "approve" ? "监督结论已批准；治理意见已留证，但不会自动切流" : "监督结论已驳回" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "监督结论审批失败") }); }
    finally { setBusy(""); }
  }

  async function createDefinition() {
    const sources = definitionForm.sources.split(",").map((item) => item.trim()).filter(Boolean);
    if (!sources.length) return onNotice({ kind: "error", text: "标签口径至少需要一个允许来源" });
    setBusy("definition-create");
    try {
      await api.createOutcomeLabelDefinition({
        code: definitionForm.code.trim(), name: definitionForm.name.trim(), description: definitionForm.description.trim(),
        event_type: definitionForm.eventType,
        event_threshold: definitionForm.eventType === "delinquency" || definitionForm.eventType === "default" ? { days_past_due: definitionForm.observationDays } : {},
        observation_window_days: definitionForm.observationDays, maturity_grace_days: definitionForm.graceDays,
        source_priorities: sources.map((source, index) => ({ source, priority: index + 1 })),
        applicable_model_keys: [modelKey], require_loss_amount: definitionForm.requireLoss, require_exposure_amount: definitionForm.requireExposure,
      });
      await reload();
      onNotice({ kind: "success", text: "标签口径草稿已创建，发布前需提交独立复核" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "标签口径创建失败") }); }
    finally { setBusy(""); }
  }

  async function actOnDefinition(item: TenantOutcomeLabelDefinition, action: "submit" | "approve" | "reject") {
    setBusy(`definition:${item.id}:${action}`);
    try {
      if (action === "submit") await api.submitOutcomeLabelDefinition(item.id, item.row_version, reviewComment);
      else await api.reviewOutcomeLabelDefinition(item.id, item.row_version, action, reviewComment);
      await reload();
      onNotice({ kind: "success", text: action === "submit" ? "标签口径已提交独立复核" : action === "approve" ? "标签口径已发布，同代码旧版本已自动退役" : "标签口径已驳回" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "标签口径操作失败") }); }
    finally { setBusy(""); }
  }

  async function createUpgradeDraft(item: TenantSupervisedEvaluation) {
    if (!selected) return;
    setBusy(`upgrade:${item.id}`);
    try {
      const result = await api.createTenantSupervisedUpgradeDraft(selected.id, item.id, item.evidence_hash, upgradeReason);
      await loadEvidence(selected.id);
      onNotice({ kind: "success", text: `模型变更草稿 ${result.model_change_id.slice(0, 8)} 已生成；尚未提交、发布或切换流量` });
    } catch (error) { onNotice({ kind: "error", text: message(error, "模型变更草稿生成失败") }); }
    finally { setBusy(""); }
  }

  async function downloadVerificationReport(item: TenantSupervisedEvaluation) {
    if (!selected) return;
    setBusy(`report:${item.id}`);
    try {
      await api.downloadTenantSupervisedVerificationReport(selected.id, item.id);
      onNotice({ kind: "success", text: "监督验证报告已下载，报告哈希对应当前不可变评估快照" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "验证报告下载失败") }); }
    finally { setBusy(""); }
  }

  return <section id="tenant-rollout-governance" className="tenant-rollout-console">
    <div className="governance-subhead"><div><strong>租户级 Champion / Challenger 灰度</strong><span>将通过离线门禁的候选模型按企业稳定分流到真实流量，并可自动切回 Champion</span></div><span className="soft-chip">固定资产 · 逐笔留证 · 自动熔断</span></div>
    <div className="rollout-notes">
      <p><b>稳定分流</b>以租户、策略和企业编号计算固定哈希桶，同一企业在观察期内始终使用同一侧，避免结果来回跳变。</p>
      <p><b>非监督证据</b>在线结果尚未形成成熟坏样本标签时，只使用失败率、延迟、评分 PSI 和准入分布保护；KS 与混淆矩阵不会被伪造。</p>
    </div>
    <div className="rollout-operations">
      <div><strong>运行控制</strong><span>周期扫描会激活排期、复评新增样本并在观察期结束时停止候选流量。证据不足不会视为验证通过。</span></div>
      {canReview && <button type="button" disabled={Boolean(busy)} onClick={() => void scan()}>{busy === "scan" ? "扫描中…" : "立即扫描"}</button>}
    </div>
    {scans.length > 0 && <div className="rollout-scans" aria-label="灰度扫描台账">{scans.slice(0, 3).map((run) => <div key={run.id}>
      <span>{run.trigger_type === "scheduler" ? "自动" : "人工"} · {new Date(run.scan_at).toLocaleString("zh-CN")}</span>
      <strong>{run.status === "no_due" ? "无待处理" : run.status === "completed" ? "已完成" : run.status === "failed" ? "执行失败" : "部分失败"}</strong>
      <small>{run.results.length} 项 · {run.results.map((item) => `${scanActionLabels[item.action]}${item.status === "failed" ? `失败（${item.error_type}）` : "完成"}`).join("、") || "空跑"}</small>
      <code title={run.evidence_hash}>{run.evidence_hash.slice(0, 12)}</code>
    </div>)}</div>}
    {canManage && <div className="rollout-builder">
      <label className="wide"><span>固定回放证据</span><select value={comparisonId} onChange={(event) => setComparisonId(event.target.value)}><option value="">请选择门禁通过证据</option>{eligibleComparisons.map((item) => <option key={item.id} value={item.id}>{item.champion_model_version} → {item.challenger_model_version} · {item.evidence_level === "labeled" ? "有标签" : "非监督"} · {item.evidence_hash.slice(0, 10)}</option>)}</select></label>
      <label><span>Challenger 流量</span><div className="rollout-number"><input type="number" min="0.01" max="99.99" step="0.5" value={trafficPercent} onChange={(event) => setTrafficPercent(Number(event.target.value))} /><small>%</small></div></label>
      <label><span>观察窗口</span><div className="rollout-number"><input type="number" min="5" max="43200" value={windowMinutes} onChange={(event) => setWindowMinutes(Number(event.target.value))} /><small>分钟</small></div></label>
      <label><span>最小样本量</span><input type="number" min="2" value={minSampleSize} onChange={(event) => setMinSampleSize(Number(event.target.value))} /></label>
      <label><span>失败率上限</span><input type="number" min="0" max="1" step="0.01" value={thresholds.max_challenger_failure_rate} onChange={(event) => setThresholds({ ...thresholds, max_challenger_failure_rate: Number(event.target.value) })} /></label>
      <label><span>延迟增幅上限</span><input type="number" min="0" step="0.1" value={thresholds.max_latency_increase_ratio} onChange={(event) => setThresholds({ ...thresholds, max_latency_increase_ratio: Number(event.target.value) })} /></label>
      <label><span>评分 PSI 上限</span><input type="number" min="0" step="0.05" value={thresholds.max_score_psi} onChange={(event) => setThresholds({ ...thresholds, max_score_psi: Number(event.target.value) })} /></label>
      <label><span>准入分布偏移</span><input type="number" min="0" max="1" step="0.05" value={thresholds.max_admission_distribution_shift} onChange={(event) => setThresholds({ ...thresholds, max_admission_distribution_shift: Number(event.target.value) })} /></label>
      <label className="wide"><span>上线依据</span><input value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <label className="wide"><span>发布后重启关联变更单（可选）</span><input value={restartChangeId} onChange={(event) => setRestartChangeId(event.target.value)} placeholder="仅用于已回滚/已结束策略的发布后重启" /></label>
      <button disabled={Boolean(busy) || !eligibleComparisons.length} onClick={() => void createPolicy()}>{busy === "create" ? "正在冻结资产…" : "创建灰度草稿"}</button>
    </div>}
    {canReview && <label className="review-comment"><span>复核 / 状态操作说明</span><input value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} /></label>}
    <div className="rollout-layout">
      <div className="rollout-policy-list">{policies.length ? policies.map((policy) => <article key={policy.id} className={`${policy.status} ${selected?.id === policy.id ? "selected" : ""}`} onClick={() => setSelectedId(policy.id)}>
        <header><span className={`governance-status ${policy.status}`}>{statusLabels[policy.effective_status] ?? policy.effective_status}</span><strong>{policy.name}</strong><small>{policy.traffic_percent}%</small></header>
        <div className="rollout-arms"><span><i>Champion</i><b>{policy.champion.model_key}</b><small>{policy.champion.model_version}</small></span><span><i>Challenger</i><b>{policy.challenger.model_key}</b><small>{policy.challenger.model_version}</small></span></div>
        <footer><code>{policy.config_hash.slice(0, 12)}</code><div>
          {canManage && policy.status === "draft" && <button className="secondary" onClick={(event) => { event.stopPropagation(); void act(policy, "submit"); }}>提交复核</button>}
          {canReview && policy.status === "pending_review" && <><button className="reject" onClick={(event) => { event.stopPropagation(); void act(policy, "reject"); }}>驳回</button><button onClick={(event) => { event.stopPropagation(); void act(policy, "approve"); }}>批准灰度</button></>}
          {canReview && policy.status === "active" && <><button className="secondary" onClick={(event) => { event.stopPropagation(); void act(policy, "evaluate"); }}>立即评估</button><button className="secondary" onClick={(event) => { event.stopPropagation(); void act(policy, "pause"); }}>暂停</button><button className="reject" onClick={(event) => { event.stopPropagation(); void act(policy, "rollback"); }}>切回 Champion</button></>}
          {canReview && policy.status === "paused" && <><button onClick={(event) => { event.stopPropagation(); void act(policy, "resume"); }}>恢复</button><button className="reject" onClick={(event) => { event.stopPropagation(); void act(policy, "rollback"); }}>回滚</button></>}
          {canManage && ["rolled_back", "completed"].includes(policy.status) && restartChangeId.trim() && <button className="secondary" disabled={Boolean(busy)} onClick={(event) => { event.stopPropagation(); void restartAfterRelease(policy); }}>{busy === `restart:${policy.id}` ? "重启中…" : "发布后重启观察"}</button>}
        </div></footer>
        {policy.terminal_reason && <p className="rollout-terminal">{policy.terminal_reason}</p>}
      </article>) : <div className="governance-empty">暂无在线灰度策略。先完成固定快照双模型比较，再创建小流量计划。</div>}</div>
      <aside className="rollout-evidence">
        <header><div><span>ONLINE EVIDENCE</span><strong>{selected ? "在线观测证据" : "等待选择策略"}</strong></div>{selected && <small>{routes.length} 笔</small>}</header>
        {selected && <>
          {selected.incident_status !== "not_applicable" && <div className={`rollout-incident ${selected.incident_status}`}>
            <strong>自动熔断事故 · {incidentLabels[selected.incident_status]}</strong>
            <p>Challenger 已切回 Champion。事故关闭只表示处置经复核，不会恢复原策略流量。</p>
            {selected.incident_evaluation_id && <small>触发评估 {selected.incident_evaluation_id}</small>}
            {selected.acknowledgement_note && <p>核查：{selected.acknowledgement_note}</p>}
            {selected.resolution_note && <p>整改：{selected.resolution_note}</p>}
            {canReview && selected.incident_status !== "resolved" && <div className="rollout-incident-actions">
              <label><span>事故核查 / 整改 / 复核依据</span><textarea value={incidentNote} onChange={(event) => setIncidentNote(event.target.value)} rows={2} /></label>
              {selected.incident_status === "open" && <button disabled={Boolean(busy)} onClick={() => void actOnIncident(selected, "acknowledge")}>确认事故</button>}
              {selected.incident_status === "acknowledged" && <button disabled={Boolean(busy)} onClick={() => void actOnIncident(selected, "request_resolution")}>提交整改</button>}
              {selected.incident_status === "resolution_pending" && <button disabled={Boolean(busy)} onClick={() => void actOnIncident(selected, "approve_resolution")}>独立复核关闭</button>}
            </div>}
          </div>}
          <div className="rollout-metrics"><span><b>{routes.length}</b>总路由</span><span><b>{challengerRoutes.length}</b>候选侧</span><span><b>{challengerRoutes.filter((item) => item.status === "failed").length}</b>候选失败</span><span><b>{routes.filter((item) => item.evidence_hash).length}</b>已封印</span></div>
          {latestEvaluation ? <div className={`rollout-gate ${latestEvaluation.action}`}><strong>{latestEvaluation.gate.summary}</strong><span>{latestEvaluation.sample_count} 个样本 · {latestEvaluation.evidence_level === "unlabeled_online" ? "非监督在线证据" : latestEvaluation.evidence_level}</span><p>{latestEvaluation.metrics.degraded_reason}</p><code>{latestEvaluation.evidence_hash.slice(0, 16)}</code></div> : <div className="governance-empty">达到最小样本量后自动评估，也可由复核人手动触发。</div>}
          <div className="rollout-route-list">{routes.slice(0, 6).map((route) => <div key={route.id}><span className={route.selected_arm}>{route.selected_arm === "challenger" ? "C2" : "C1"}</span><b>{route.channel}</b><small>桶 {route.bucket} · {route.status}{route.elapsed_ms !== null ? ` · ${route.elapsed_ms}ms` : ""}</small><code>{route.evidence_hash?.slice(0, 8) ?? "待完成"}</code></div>)}</div>
        </>}
      </aside>
    </div>
    {diffSlaDashboard && <section className="monitoring-diff-sla-dashboard">
      <header><div><strong>差异工单 SLA 运营看板</strong><small>跨模型、跨策略汇总未关闭差异工单；临期自动提醒，逾期分级升级，关闭后自动恢复通知。</small></div><div className="monitoring-diff-sla-actions">{canReview && <button className="secondary" disabled={Boolean(busy)} onClick={() => void scanMonitoringDiffSla()}>{busy === "monitoring-diff-sla-scan" ? "扫描中…" : "执行 SLA 扫描"}</button>}<span>截至 {new Date(diffSlaDashboard.as_of).toLocaleString("zh-CN")}</span></div></header>
      <div className="monitoring-diff-sla-summary">{(["open", "due_soon", "overdue", "escalated", "unassigned", "pending_disposition", "critical"] as const).map((key) => <div key={key} className={`monitoring-diff-sla-card ${key}`}><span>{({ open: "待办总数", due_soon: "临期", overdue: "已逾期", escalated: "严重升级", unassigned: "未分派", pending_disposition: "待独立处置", critical: "重大工单" })[key]}</span><strong>{diffSlaDashboard.counts[key]}</strong></div>)}</div>
      {(diffSlaDashboard.by_policy.length > 0 || diffSlaDashboard.by_model.length > 0) && <div className="monitoring-diff-sla-breakdown"><div><strong>按策略工作量</strong>{diffSlaDashboard.by_policy.length === 0 ? <small>暂无未关闭工单</small> : <div className="monitoring-diff-sla-table"><div className="monitoring-diff-sla-row heading"><span>策略</span><span>待办</span><span>临期</span><span>逾期 / 升级</span><span>未分派</span></div>{diffSlaDashboard.by_policy.slice(0, 8).map((row) => <div className="monitoring-diff-sla-row" key={row.policy_id}><span title={row.policy_name}>{row.policy_name}</span><b>{row.open_count}</b><b>{row.due_soon_count}</b><b>{row.overdue_count} / {row.escalated_count}</b><b>{row.unassigned_count}</b></div>)}</div>}</div><div><strong>按模型版本工作量</strong>{diffSlaDashboard.by_model.length === 0 ? <small>暂无未关闭工单</small> : <div className="monitoring-diff-sla-table"><div className="monitoring-diff-sla-row heading"><span>模型版本</span><span>待办</span><span>临期</span><span>逾期 / 升级</span><span>未分派</span></div>{diffSlaDashboard.by_model.slice(0, 8).map((row, index) => <div className="monitoring-diff-sla-row" key={`${row.model_key ?? "unknown"}-${row.model_version ?? index}`}><span title={`${row.model_key ?? "未知模型"} · ${row.model_version ?? "未知版本"}`}>{row.model_key ?? "未知模型"} · {row.model_version ?? "未知版本"}</span><b>{row.open_count}</b><b>{row.due_soon_count}</b><b>{row.overdue_count} / {row.escalated_count}</b><b>{row.unassigned_count}</b></div>)}</div>}</div></div>}
      <div className="monitoring-diff-sla-items"><strong>优先处置队列</strong>{diffSlaDashboard.items.length === 0 ? <small>当前没有未关闭差异工单</small> : diffSlaDashboard.items.slice(0, 6).map((item) => <div className={`monitoring-diff-sla-item ${item.sla.status}`} key={item.id}><div><span className={`governance-status ${item.sla.status}`}>{diffSlaStatusLabels[item.sla.status]}</span><b>{diffCaseSeverityLabels[item.severity]} · {item.policy_name}</b><small>{item.model_key ?? "未知模型"} · {item.model_version ?? "未知版本"} · 负责人 {item.assigned_to_name ?? item.assigned_role}</small></div><strong>{item.sla.status === "due_soon" ? `${item.sla.remaining_hours} 小时后到期` : item.sla.status === "normal" ? `剩余 ${item.sla.remaining_hours} 小时` : `已逾期 ${item.sla.overdue_hours} 小时`}</strong></div>)}</div>
    </section>}
    {selected && <section className="delayed-supervision" aria-label="结果标签与延迟监督评估">
      <header><div><span>DELAYED SUPERVISION</span><strong>结果标签回流与监督评估</strong><p>将逾期、违约或损失事实绑定到决策当时的模型选边与冻结资产。预测分值由历史证据读取，不能在此改写。</p></div><small>{activeOutcomes.filter((item) => item.verification_status === "verified" && item.maturity_status === "mature").length} 条成熟标签</small></header>
      <div className="supervision-notes">
        <p><b>观察窗口</b>是从历史预测到结果可确认的等待期；截止日前的样本仍属于未成熟，不参与 KS/AUC。</p>
        <p><b>监督证据</b>要求已核验的事件与非事件样本均达到门槛；不足时仍保存快照，但明确标记为降级证据。</p>
        <p><b>标签冲正</b>不会覆盖错误事实，而是保留原标签并建立替代版本链；新版本必须重新独立核验。</p>
        <p><b>结论审批</b>只形成模型治理意见。即使批准“建议晋级”，也不会自动发布模型、恢复灰度或切换流量。</p>
      </div>
      <details className="label-definition-console" open={!publishedDefinitions.length}>
        <summary><span><strong>标签口径字典</strong><small>统一事件定义、观察期、来源优先级和适用模型；标签入库后永久冻结口径版本与哈希。</small></span><b>{publishedDefinitions.length} 个已发布</b></summary>
        {canManage && <div className="label-definition-form">
          <label><span>口径代码</span><input value={definitionForm.code} onChange={(event) => setDefinitionForm({ ...definitionForm, code: event.target.value })} /></label>
          <label><span>口径名称</span><input value={definitionForm.name} onChange={(event) => setDefinitionForm({ ...definitionForm, name: event.target.value })} /></label>
          <label><span>事件类型</span><select value={definitionForm.eventType} onChange={(event) => setDefinitionForm({ ...definitionForm, eventType: event.target.value as typeof definitionForm.eventType })}><option value="default">违约</option><option value="delinquency">逾期</option><option value="loss">损失</option><option value="recovery">回收</option></select></label>
          <label><span>观察期 / 宽限期（天）</span><span className="paired-input"><input type="number" min="1" value={definitionForm.observationDays} onChange={(event) => setDefinitionForm({ ...definitionForm, observationDays: Number(event.target.value) })} /><input type="number" min="0" value={definitionForm.graceDays} onChange={(event) => setDefinitionForm({ ...definitionForm, graceDays: Number(event.target.value) })} /></span></label>
          <label className="wide"><span>来源优先级（逗号分隔，顺序即优先级）</span><input value={definitionForm.sources} onChange={(event) => setDefinitionForm({ ...definitionForm, sources: event.target.value })} /></label>
          <label className="wide"><span>口径说明</span><input value={definitionForm.description} onChange={(event) => setDefinitionForm({ ...definitionForm, description: event.target.value })} /></label>
          <label className="definition-check"><input type="checkbox" checked={definitionForm.requireLoss} onChange={(event) => setDefinitionForm({ ...definitionForm, requireLoss: event.target.checked })} /><span>强制损失金额</span></label>
          <label className="definition-check"><input type="checkbox" checked={definitionForm.requireExposure} onChange={(event) => setDefinitionForm({ ...definitionForm, requireExposure: event.target.checked })} /><span>强制风险暴露</span></label>
          <button disabled={Boolean(busy)} onClick={() => void createDefinition()}>{busy === "definition-create" ? "创建中…" : "新建口径版本"}</button>
        </div>}
        <div className="label-definition-ledger">{definitions.map((item) => <article key={item.id} className={item.id === selectedDefinition?.id ? "selected" : ""}>
          <button className="definition-main" type="button" onClick={() => item.status === "published" && item.is_active && setSelectedDefinitionId(item.id)} disabled={item.status !== "published" || !item.is_active}>
            <span className={`governance-status ${item.status}`}>{definitionStatusLabels[item.status]}</span><strong>{item.name} · v{item.version}</strong><small>{item.event_type} · {item.observation_window_days}+{item.maturity_grace_days} 天 · {item.source_priorities.map((source) => source.source).join(" / ")}</small><code>{item.config_hash.slice(0, 12)}</code>
          </button>
          <div className="definition-actions">{canManage && item.status === "draft" && <button disabled={Boolean(busy)} onClick={() => void actOnDefinition(item, "submit")}>提交复核</button>}{canReview && item.status === "pending_review" && <><button className="reject" disabled={Boolean(busy)} onClick={() => void actOnDefinition(item, "reject")}>驳回</button><button disabled={Boolean(busy)} onClick={() => void actOnDefinition(item, "approve")}>批准发布</button></>}</div>
        </article>)}</div>
      </details>
      <div className="supervision-coverage">
        <span><b>{activeOutcomes.length}</b>当前标签</span><span><b>{activeOutcomes.filter((item) => item.verification_status === "verified").length}</b>已核验</span><span><b>{activeOutcomes.filter((item) => item.maturity_status === "mature").length}</b>已成熟</span><span><b>{outcomes.filter((item) => item.record_status === "superseded").length}</b>历史冲正</span>
      </div>
      {canManage && <div className="outcome-entry">
        <label className="wide"><span>已发布标签口径</span><select value={selectedDefinition?.id ?? ""} onChange={(event) => { const definition = publishedDefinitions.find((item) => item.id === event.target.value); setSelectedDefinitionId(event.target.value); if (definition?.source_priorities[0]) { setOutcomeForm((current) => ({ ...current, source: definition.source_priorities[0].source })); setBatchForm((current) => ({ ...current, source: definition.source_priorities[0].source })); } }}><option value="">请选择已发布口径</option>{publishedDefinitions.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version} · {item.observation_window_days} 天</option>)}</select></label>
        <label className="wide"><span>历史灰度路由</span><select value={outcomeForm.routeId} onChange={(event) => setOutcomeForm({ ...outcomeForm, routeId: event.target.value })}><option value="">请选择尚未回流的已完成路由</option>{eligibleOutcomeRoutes.map((route) => <option key={route.id} value={route.id}>{route.selected_arm === "challenger" ? "Challenger" : "Champion"} · {route.request_ref} · 分值 {route.score}</option>)}</select></label>
        <label><span>来源系统</span><select value={outcomeForm.source} onChange={(event) => setOutcomeForm({ ...outcomeForm, source: event.target.value })}>{selectedDefinition?.source_priorities.map((item) => <option key={item.source} value={item.source}>{item.priority}. {item.source}</option>)}</select></label>
        <label><span>企业编号</span><input value={outcomeForm.counterpartyId} onChange={(event) => setOutcomeForm({ ...outcomeForm, counterpartyId: event.target.value })} placeholder="须与历史路由键一致" /></label>
        <label><span>外部标签编号</span><input value={outcomeForm.externalId} onChange={(event) => setOutcomeForm({ ...outcomeForm, externalId: event.target.value })} placeholder="贷后系统唯一编号" /></label>
        <label><span>观察截止日</span><input type="date" value={outcomeForm.observationEnd} onChange={(event) => setOutcomeForm({ ...outcomeForm, observationEnd: event.target.value })} /></label>
        <label><span>结果事件</span><select value={outcomeForm.observedEvent ? "event" : "normal"} onChange={(event) => setOutcomeForm({ ...outcomeForm, observedEvent: event.target.value === "event" })}><option value="normal">未发生风险事件</option><option value="event">发生逾期 / 违约</option></select></label>
        <label><span>损失金额</span><input type="number" min="0" value={outcomeForm.lossAmount} onChange={(event) => setOutcomeForm({ ...outcomeForm, lossAmount: event.target.value })} placeholder="可选" /></label>
        <label><span>风险暴露</span><input type="number" min="0.01" value={outcomeForm.exposureAmount} onChange={(event) => setOutcomeForm({ ...outcomeForm, exposureAmount: event.target.value })} placeholder="可选" /></label>
        <label className="wide"><span>原始证据引用</span><input value={outcomeForm.evidenceReference} onChange={(event) => setOutcomeForm({ ...outcomeForm, evidenceReference: event.target.value })} /></label>
        <button disabled={Boolean(busy) || !eligibleOutcomeRoutes.length} onClick={() => void ingestOutcome()}>{busy === "outcome-create" ? "绑定中…" : "导入并绑定标签"}</button>
      </div>}
      {canManage && <details className="outcome-batch" open={outcomeImports.length === 0}>
        <summary><span><strong>批量导入与数量对账</strong><small>按批次键幂等处理，每行独立回执；单行失败不会撤销其他有效标签。</small></span><b>{outcomeImports.length} 批</b></summary>
        <div className="outcome-batch-form">
          <label><span>批次键</span><input value={batchForm.importKey} onChange={(event) => setBatchForm({ ...batchForm, importKey: event.target.value })} /></label>
          <label><span>来源系统</span><input value={batchForm.source} onChange={(event) => setBatchForm({ ...batchForm, source: event.target.value })} /></label>
          <label><span>冻结口径</span><input value={selectedDefinition ? `${selectedDefinition.name} · v${selectedDefinition.version}` : "请先选择已发布口径"} disabled /></label>
          <label><span>来源声明数量</span><input type="number" min="1" max="500" value={batchForm.expectedCount} onChange={(event) => setBatchForm({ ...batchForm, expectedCount: Number(event.target.value) })} /></label>
          <label className="wide"><span>标签行 JSON</span><textarea rows={8} value={batchForm.payload} onChange={(event) => setBatchForm({ ...batchForm, payload: event.target.value })} spellCheck={false} /></label>
          <div className="outcome-batch-actions"><button type="button" className="secondary" onClick={prepareBatchTemplate}>载入路由模板</button><button type="button" disabled={Boolean(busy)} onClick={() => void ingestOutcomeBatch()}>{busy === "outcome-batch" ? "逐行处理中…" : "执行批量导入"}</button></div>
          <div className="outcome-csv-import"><label><span>生产 CSV 文件</span><input type="file" accept=".csv,text/csv" onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)} /></label><label><span>CSV 批次键</span><input value={csvImportKey} onChange={(event) => setCsvImportKey(event.target.value)} /></label><small>UTF-8 CSV，必须包含 external_label_id、routing_decision_id、counterparty_id、observed_event、observation_end、loss_amount、exposure_amount、evidence_reference；单文件不超过 512KB、500 行。</small><button type="button" className="secondary" disabled={Boolean(busy) || !csvFile} onClick={() => void ingestOutcomeCsv()}>{busy === "outcome-csv" ? "校验并导入中…" : "校验并导入 CSV"}</button></div>
        </div>
      </details>}
      {outcomeImports.length > 0 && <div className="outcome-import-ledger">{outcomeImports.slice(0, 3).map((batch) => <article key={batch.id}>
        <header><div><strong>{batch.import_key}</strong><small>{batch.source} · {batch.label_definition}</small></div><span className={`governance-status ${batch.status}`}>{batch.status === "completed" ? "已对账" : batch.status === "processing" ? "处理中" : batch.status === "failed" ? "失败" : "有差异"}</span></header>
        <div><span>声明 / 收到 <b>{batch.expected_count} / {batch.received_count}</b></span><span>新增 <b>{batch.created_count}</b></span><span>幂等 <b>{batch.idempotent_count}</b></span><span>拒绝 <b>{batch.rejected_count}</b></span></div>
        {batch.results.some((item) => item.status === "rejected") && <ul>{batch.results.filter((item) => item.status === "rejected").map((item) => <li key={`${batch.id}-${item.index}`}>第 {item.index + 1} 行 · {item.external_label_id}：{item.error}</li>)}</ul>}
      </article>)}</div>}
      <div className="outcome-ledger">{outcomes.length ? outcomes.slice(0, 8).map((item) => <div key={item.id}>
        <span className={`outcome-event ${item.observed_event ? "bad" : "good"}`}>{item.observed_event ? "事件" : "正常"}</span>
        <div><strong>{item.counterparty_id}</strong><small>{item.selected_arm} · {item.model_version} · 历史分值 {item.predicted_score}</small><small>{item.label_definition} · v{item.label_definition_version ?? "legacy"}</small>{item.supersedes_label_id && <small>替代 {item.supersedes_label_id.slice(0, 8)}</small>}</div>
        <div><b>{item.maturity_status === "mature" ? "已成熟" : "观察中"}</b><small>{item.link_status === "decision_execution" ? "Decision API 强关联" : "路由证据关联"}</small></div>
        <div className="outcome-state"><span className={`governance-status ${item.record_status}`}>{item.record_status === "active" ? "当前" : "已冲正"}</span><span className={`governance-status ${item.verification_status}`}>{item.verification_status === "verified" ? "已核验" : item.verification_status === "rejected" ? "已驳回" : "待核验"}</span></div>
        <div className="outcome-actions">{canManage && item.record_status === "active" && <button className="secondary" disabled={Boolean(busy)} onClick={() => beginCorrection(item)}>冲正</button>}{canReview && item.record_status === "active" && item.verification_status === "pending_verification" && <><button className="reject" disabled={Boolean(busy)} onClick={() => void verifyOutcome(item, "reject")}>驳回</button><button disabled={Boolean(busy)} onClick={() => void verifyOutcome(item, "verify")}>核验通过</button></>}</div>
        {correctingId === item.id && <div className="outcome-correction">
          <div><strong>创建替代版本</strong><span>原标签将标记为“已冲正”，不会被删除或覆盖。</span></div>
          <label><span>新外部编号</span><input value={correctionForm.externalId} onChange={(event) => setCorrectionForm({ ...correctionForm, externalId: event.target.value })} /></label>
          <label><span>结果事件</span><select value={correctionForm.observedEvent ? "event" : "normal"} onChange={(event) => setCorrectionForm({ ...correctionForm, observedEvent: event.target.value === "event" })}><option value="normal">未发生风险事件</option><option value="event">发生逾期 / 违约</option></select></label>
          <label><span>观察截止日</span><input type="date" value={correctionForm.observationEnd} onChange={(event) => setCorrectionForm({ ...correctionForm, observationEnd: event.target.value })} /></label>
          <label><span>损失 / 暴露</span><span className="paired-input"><input type="number" min="0" value={correctionForm.lossAmount} onChange={(event) => setCorrectionForm({ ...correctionForm, lossAmount: event.target.value })} placeholder="损失" /><input type="number" min="0.01" value={correctionForm.exposureAmount} onChange={(event) => setCorrectionForm({ ...correctionForm, exposureAmount: event.target.value })} placeholder="暴露" /></span></label>
          <label className="wide"><span>证据引用</span><input value={correctionForm.evidenceReference} onChange={(event) => setCorrectionForm({ ...correctionForm, evidenceReference: event.target.value })} /></label>
          <label className="wide"><span>冲正依据</span><input value={correctionForm.reason} onChange={(event) => setCorrectionForm({ ...correctionForm, reason: event.target.value })} /></label>
          <div className="outcome-correction-actions"><button className="secondary" onClick={() => setCorrectingId("")}>取消</button><button disabled={Boolean(busy)} onClick={() => void correctOutcome(item)}>{busy === `correct:${item.id}` ? "冲正中…" : "确认建立替代版本"}</button></div>
        </div>}
      </div>) : <div className="governance-empty">暂无结果标签。在线路由完成后，可从贷后或核心系统回流成熟结果。</div>}</div>
      {(monitoringRuns.length > 0 || canReview) && <div className="monitoring-run-ledger">
        <header><div><strong>租户监控快照治理</strong><small>发布状态控制证据可见性；阈值门禁进一步判断能否用于正式模型再接受。非监督快照只作为诊断证据。</small></div><div className="monitoring-run-header-actions">{canReview && <button className="secondary" disabled={Boolean(busy)} onClick={() => void scanMonitoringGates()}>{busy === "monitoring-gate-scan" ? "扫描中…" : "扫描门禁"}</button>}{canReview && <button disabled={Boolean(busy) || !selectedDefinition} onClick={() => void generateMonitoringRuns()}>{busy === "monitoring-generate" ? "生成中…" : "生成快照"}</button>}<span>{monitoringRuns.length} 条快照</span></div></header>
        {monitoringRuns.slice(0, 6).map((item) => <article key={item.id}><div><strong>{item.model_version}</strong><small>{item.run_key} · {item.evidence_level === "supervised" ? "监督" : "非监督"} · {new Date(item.observed_to).toLocaleString("zh-CN")}</small>{item.monitoring_gate?.reasons[0] && <small className="monitoring-gate-reason">{item.monitoring_gate.reasons[0]}</small>}</div><div className="monitoring-run-statuses"><span className={`governance-status ${item.governance_status}`}>{monitoringGovernanceLabels[item.governance_status] ?? item.governance_status}</span>{item.monitoring_gate && <span className={`governance-status monitoring-gate-${item.monitoring_gate.status}`}>{monitoringGateLabels[item.monitoring_gate.status]}</span>}</div><div className="monitoring-run-actions">{canManage && ["draft", "rejected"].includes(item.governance_status) && <button disabled={Boolean(busy)} onClick={() => void submitMonitoringRun(item)}>{busy === `monitoring-submit:${item.id}` ? "提交中…" : "提交复核"}</button>}{canReview && item.governance_status === "pending_review" && <><button className="reject" disabled={Boolean(busy)} onClick={() => void reviewMonitoringRun(item, "reject")}>驳回</button><button disabled={Boolean(busy)} onClick={() => void reviewMonitoringRun(item, "approve")}>发布</button></>}{canReview && item.governance_status === "published" && <button className="secondary" disabled={Boolean(busy)} onClick={() => void retractMonitoringRun(item)}>撤回</button>}<button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void showMonitoringDiff(item)}>查看差异</button>{canManage && <button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void createMonitoringDiffCase(item)}>{busy === `monitoring-diff-case:${item.id}` ? "登记中…" : "登记工单"}</button>}</div></article>)}
      </div>}
      {(monitoringDiffCases.length > 0 || canManage) && <div className="monitoring-diff-case-ledger">
        <header><div><strong>监控差异处置台账</strong><small>按原截止时间、标签口径和冻结模型重算；原快照不覆盖。重大工单关闭前，关联快照不能发布。</small></div><span>{monitoringDiffCases.filter((item) => !["resolved", "rejected"].includes(item.status)).length} 条待办</span></header>
        <label className="monitoring-diff-reason"><span>立案 / 重算依据</span><input value={diffCaseReason} onChange={(event) => setDiffCaseReason(event.target.value)} /></label>
        {monitoringDiffCases.length === 0 ? <div className="governance-empty">暂无差异工单。可从同模型快照行登记需要复算和追责的差异。</div> : monitoringDiffCases.slice(0, 8).map((item) => <article key={item.id} className={`${item.severity} ${item.overdue ? "overdue" : ""}`}>
          <div className="monitoring-diff-case-main"><div><span className={`governance-status ${item.status}`}>{diffCaseStatusLabels[item.status]}</span><b>{diffCaseSeverityLabels[item.severity]}</b>{item.overdue && <em>已逾期</em>}</div><strong>{item.reason}</strong><small>负责人：{item.assigned_to_name ?? item.assigned_role} · 截止 {new Date(item.due_at).toLocaleString("zh-CN")}</small></div>
          <div className="monitoring-diff-case-evidence"><code>原 {item.diff_hash.slice(0, 12)}</code><code>重算 {item.recomputed_diff_hash?.slice(0, 12) ?? "--"}</code><small>{item.recompute_status === "completed" ? "重算证据已固定" : item.recompute_status === "failed" ? item.recompute_error : "等待固定口径重算"}</small></div>
          <div className="monitoring-diff-case-actions">{canManage && item.status === "open" && <button className="secondary" disabled={Boolean(busy)} onClick={() => void assignMonitoringDiffCase(item)}>{busy === `diff-assign:${item.id}` ? "领取中…" : "领取"}</button>}{canManage && ["open", "assigned"].includes(item.status) && <button disabled={Boolean(busy)} onClick={() => void recomputeMonitoringDiffCase(item)}>{busy === `diff-recompute:${item.id}` ? "重算中…" : item.recompute_status === "failed" ? "重新重算" : "执行重算"}</button>}{canReview && item.status === "pending_disposition" && <><select value={diffDisposition} onChange={(event) => setDiffDisposition(event.target.value as typeof diffDisposition)}>{Object.entries(diffDispositionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input value={diffConclusion} onChange={(event) => setDiffConclusion(event.target.value)} aria-label="差异处置结论" /><button disabled={Boolean(busy)} onClick={() => void disposeMonitoringDiffCase(item)}>{busy === `diff-dispose:${item.id}` ? "提交中…" : "独立处置"}</button></>}{item.status === "resolved" && <small>{diffDispositionLabels[item.disposition ?? ""] ?? item.disposition} · {item.resolved_by_name}</small>}</div>
        </article>)}
      </div>}
      <div className="supervised-runner">
        <div><strong>监督样本门槛</strong><span>事件与非事件不足时，KS/AUC 返回空值，不以模拟数据补齐。</span></div>
        <label><span>租户监控快照</span><select value={selectedMonitoringRunId} onChange={(event) => setSelectedMonitoringRunId(event.target.value)}><option value="">不绑定（历史兼容）</option>{monitoringRuns.filter((item) => item.governance_status === "published").map((item) => <option key={item.id} value={item.id}>{item.run_key} · {item.model_version} · {item.evidence_level === "supervised" ? "监督" : "非监督"}</option>)}</select></label>
        <label><span>评估口径</span><select value={selectedDefinition?.id ?? ""} onChange={(event) => setSelectedDefinitionId(event.target.value)}>{publishedDefinitions.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}</select></label>
        <label><span>成熟样本</span><input type="number" min="2" value={supervisedConfig.min_mature_samples} onChange={(event) => setSupervisedConfig({ ...supervisedConfig, min_mature_samples: Number(event.target.value) })} /></label>
        <label><span>最少事件</span><input type="number" min="1" value={supervisedConfig.min_events} onChange={(event) => setSupervisedConfig({ ...supervisedConfig, min_events: Number(event.target.value) })} /></label>
        <label><span>最少非事件</span><input type="number" min="1" value={supervisedConfig.min_non_events} onChange={(event) => setSupervisedConfig({ ...supervisedConfig, min_non_events: Number(event.target.value) })} /></label>
        <label><span>每侧可靠样本</span><input type="number" min="2" value={supervisedConfig.min_reliable_samples_per_arm} onChange={(event) => setSupervisedConfig({ ...supervisedConfig, min_reliable_samples_per_arm: Number(event.target.value) })} /></label>
        <label><span>高风险阈值</span><input type="number" min="0" max="1" step="0.05" value={supervisedConfig.high_risk_threshold} onChange={(event) => setSupervisedConfig({ ...supervisedConfig, high_risk_threshold: Number(event.target.value) })} /></label>
        <label><span>Bootstrap 次数</span><input type="number" min="200" max="5000" step="100" value={supervisedConfig.bootstrap_resamples} onChange={(event) => setSupervisedConfig({ ...supervisedConfig, bootstrap_resamples: Number(event.target.value) })} /></label>
        {canReview && <button disabled={Boolean(busy)} onClick={() => void evaluateSupervised()}>{busy === "supervised-evaluate" ? "计算中…" : "生成监督评估"}</button>}
      </div>
      {latestSupervised && <div className={`supervised-result ${latestSupervised.evidence_level}`}>
        <header><div><strong>{latestSupervised.evidence_level === "supervised" ? "监督证据已就绪" : latestSupervised.evidence_level === "insufficient_maturity" ? "等待标签成熟" : "监督标签不足"}</strong><span>{latestSupervised.metrics.degraded_reason ?? latestSupervised.metrics.comparison?.conclusion}</span><small>{latestSupervised.tenant_monitoring_run_id ? `已绑定租户监控快照 · ${latestSupervised.tenant_monitoring_evidence_hash?.slice(0, 12)}` : "历史兼容评估，未绑定租户监控快照"}</small></div><div className="supervised-result-status"><span className={`governance-status ${latestSupervised.status}`}>{evaluationStatusLabels[latestSupervised.status]}</span><code>{latestSupervised.evidence_hash.slice(0, 16)}</code></div></header>
        <div className="supervised-arms">{(["champion", "challenger"] as const).map((arm) => { const metric = latestSupervised.metrics[arm]; return <div key={arm}><strong>{arm === "champion" ? "Champion" : "Challenger"}</strong><span>{metric.sample_count} 样本 · 事件率 {percent(metric.event_rate)} · {metric.statistical_reliability === "statistically_reliable" ? "统计可靠" : "方向性"}</span><dl><div><dt>AUC</dt><dd>{metric.auc?.toFixed(3) ?? "--"}</dd></div><div><dt>AUC 95% CI</dt><dd>{decimalInterval(metric.auc_confidence_interval)}</dd></div><div><dt>KS</dt><dd>{metric.ks?.toFixed(3) ?? "--"}</dd></div><div><dt>KS 95% CI</dt><dd>{decimalInterval(metric.ks_confidence_interval)}</dd></div><div><dt>损失率</dt><dd>{percent(metric.loss_rate)}</dd></div><div><dt>风险暴露</dt><dd>{metric.total_exposure_amount.toLocaleString("zh-CN")}</dd></div><div><dt>事件率 95% CI</dt><dd>{interval(metric.event_rate_confidence_interval)}</dd></div><div><dt>损失率 95% CI</dt><dd>{interval(metric.loss_rate_confidence_interval)}</dd></div><div><dt>TP / FP</dt><dd>{metric.confusion_matrix.true_positive} / {metric.confusion_matrix.false_positive}</dd></div><div><dt>TN / FN</dt><dd>{metric.confusion_matrix.true_negative} / {metric.confusion_matrix.false_negative}</dd></div></dl><small>月度稳定性：{trendLabel(metric.stability_trend.direction)} · 分群公平性：不可评估</small></div>; })}</div>
        {latestSupervised.metrics.comparison && <div className="supervised-comparison"><strong>双模型差异信号</strong><span>AUC Δ {latestSupervised.metrics.comparison.auc_delta.toFixed(3)}（{signalLabel(latestSupervised.metrics.comparison.auc_difference_signal)}，95% CI {decimalInterval(latestSupervised.metrics.comparison.auc_difference_confidence_interval)}）</span><span>KS Δ {latestSupervised.metrics.comparison.ks_delta.toFixed(3)}（{signalLabel(latestSupervised.metrics.comparison.ks_difference_signal)}，95% CI {decimalInterval(latestSupervised.metrics.comparison.ks_difference_confidence_interval)}）</span><small>区间重叠：AUC {latestSupervised.metrics.comparison.confidence_interval_overlap.auc === null ? "--" : latestSupervised.metrics.comparison.confidence_interval_overlap.auc ? "是" : "否"} · KS {latestSupervised.metrics.comparison.confidence_interval_overlap.ks === null ? "--" : latestSupervised.metrics.comparison.confidence_interval_overlap.ks ? "是" : "否"}。分群指标仅用于稳定性观察，未绑定受保护属性，不能作公平性结论。</small></div>}
        <p>{latestSupervised.metrics.note}</p>
      </div>}
      <label className="supervised-upgrade-reason"><span>升级草稿变更原因</span><input value={upgradeReason} onChange={(event) => setUpgradeReason(event.target.value)} /></label>
      {supervisedEvaluations.length > 0 && <div className="supervised-ledger">{supervisedEvaluations.slice(0, 4).map((item) => <article key={item.id}>
        <div><span className={`governance-status ${item.status}`}>{evaluationStatusLabels[item.status]}</span><strong>{item.evidence_level === "supervised" ? "监督评估" : "降级证据"}</strong><small>{item.coverage.mature_count} 个成熟样本 · {new Date(item.created_at).toLocaleString("zh-CN")}</small></div>
        <code>{item.evidence_hash.slice(0, 12)}</code>
        {item.governance_decision && <b>{governanceDecisionLabels[item.governance_decision]}</b>}
        {canReview && item.status === "draft" && item.evidence_level === "supervised" && <button disabled={Boolean(busy)} onClick={() => void submitSupervised(item)}>提交复核</button>}
        {canReview && item.status === "pending_review" && <div className="supervised-review-actions"><select value={governanceDecision} onChange={(event) => setGovernanceDecision(event.target.value as typeof governanceDecision)}><option value="continue_observation">继续观察</option><option value="retain_champion">保留 Champion</option><option value="promote_candidate">建议晋级 Challenger</option><option value="reject_candidate">拒绝候选模型</option></select><button className="reject" disabled={Boolean(busy)} onClick={() => void reviewSupervised(item, "reject")}>驳回</button><button disabled={Boolean(busy)} onClick={() => void reviewSupervised(item, "approve")}>批准结论</button></div>}
        <button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void downloadVerificationReport(item)} title="下载当前不可变监督快照的指标和证据摘要">{busy === `report:${item.id}` ? "下载中…" : "下载验证报告"}</button>
        {item.upgrade_decision ? <span className="upgrade-draft-link">模型变更草稿 {item.upgrade_decision.model_change_id?.slice(0, 8)} · 未提交 / 未发布 / 未切流</span> : canManage && item.status === "approved" && item.governance_decision === "promote_candidate" && item.metrics.comparison?.promotion_readiness === "ready" && <button disabled={Boolean(busy)} onClick={() => void createUpgradeDraft(item)}>{busy === `upgrade:${item.id}` ? "生成中…" : "生成模型变更草稿"}</button>}
      </article>)}</div>}
    </section>}
  </section>;
}


function message(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function percent(value: number | null) {
  return value === null ? "--" : `${(value * 100).toFixed(1)}%`;
}

function interval(value: { lower: number; upper: number } | null) {
  return value ? `${(value.lower * 100).toFixed(1)}% - ${(value.upper * 100).toFixed(1)}%` : "--";
}

function decimalInterval(value: { lower: number; upper: number } | null) {
  return value ? `${value.lower.toFixed(3)} - ${value.upper.toFixed(3)}` : "--";
}

function signalLabel(value: string) {
  return value === "significant_challenger_better" ? "Challenger 显著更优" : value === "significant_champion_better" ? "Champion 显著更优" : value === "directional_only" ? "仅方向性" : "不可评估";
}

function trendLabel(value: string) {
  return value === "increasing" ? "事件率上升" : value === "decreasing" ? "事件率下降" : value === "stable" ? "稳定" : "周期不足";
}
