import type { ApiErrorShape, ApprovalAction, ApprovalCase, AuthorityPolicyActivationRun, AuthorityPolicyActivationScan, AuthorityPolicyActivationStatus, AuthorityPolicyConfig, AuthorityPolicyEvidence, AuthorityPolicyEvidenceAnchor, AuthorityPolicyEvidenceAnchorReceipt, AuthorityPolicyEvidenceComparison, AuthorityPolicyImpact, AuthorityPolicyRecord, AuthorityPolicyScenarioComparison, AuthorityPolicySnapshot, Counterparty, CreditFacility, CreditFacilityDetail, CreditReport, CreditReportIntegrity, DecisionGovernanceSummary, DecisionPipelineDefinition, DecisionVariance, DocumentChecklist, DocumentCheckResult, DocumentCorrection, DocumentCorrectionTask, DocumentPrecheck, DocumentRecord, DocumentVersionComparison, EnterpriseDataConflict, EnterpriseDataImport, EnterpriseDataProfile, EnterpriseDataResolution, EnterpriseFieldLineage, EnterpriseIndicatorObservation, FacilityAlert, FacilityControlCondition, FacilityControlExtension, FacilitySummary, IndicatorCatalogItem, IndicatorPoolResponse, ModelChangeRecord, ModelDetail, ModelGovernanceNotification, ModelImpact, ModelMonitoringRun, ModelMonitoringSchedule, ModelOutcome, ModelOutcomeImport, ModelReleaseRecord, ModelSummary, ModelValidationReport, MonitoringIssue, MonitoringSchedulerTick, MonitoringSummary, NotificationRecord, OperationsSummary, PersonalTaskAssignment, PersonalTaskQueue, PipelineSimulationResult, PipelineStage, PortfolioRatingBatch, Principal, RatingReadiness, RatingResult, RatingTrace, RawEnterpriseProfile, RenewalDocumentCarryover, RenewalRiskReview, RiskEvent, RiskScreeningPolicy, RuleAction, RuleCenterActivationResult, RuleCenterAssetType, RuleCenterGovernanceChange, RuleCenterPackagePreview, RuleCenterReleasePackage, RuleCenterReplayDataset, RuleCenterReplayRun, RuleCenterReplaySnapshot, RuleCenterVersionHistory, RuleCondition, RuleDefinition, RuleSetDefinition, RuleTestResult, ScorecardAsset, ScorecardChange, ScorecardDefinitionPayload, ScorecardDevelopmentExclusionRule, ScorecardDevelopmentRun, ScorecardDevelopmentTrends, ScorecardMonitoringBulkAssignResult, ScorecardMonitoringEvent, ScorecardMonitoringEventFilters, ScorecardMonitoringExecution, ScorecardMonitoringPlan, ScorecardMonitoringRunConfig, ScorecardMonitoringSavedView, ScorecardMonitoringSchedulerExecution, ScorecardMonitoringSchedulerHealth, ScorecardMonitoringSlaPolicy, ScorecardPortfolioStability, ScorecardValidationPolicy, ScorecardValidationThresholds, SlaScanHistory, SlaScanResult, SlaScanRetryResult, StrongRule, TeamTaskBoard } from "./types";
import type { RuleCenterReplayComparison, RuleCenterReplayComparisonException } from "./types";
import type { CreditCalibrationAnalyzeRequest, CreditCalibrationComparison, CreditCalibrationConfig, CreditCalibrationPlan, CreditCalibrationRun, CreditCalibrationResult } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const TOKEN_KEY = "risk-platform.dev-token";
type ModelOutcomePayload = { external_observation_id: string; source: string; template_key: string; model_version: string; counterparty_id: string; population_period: string; predicted_score: number; predicted_pd: number; observed_event: boolean; prediction_at: string; observation_end: string; evidence_reference: string };

export const devIdentities = [
  { token: "dev-manager", label: "客户经理", description: "发起申请并推动业务环节" },
  { token: "dev-risk", label: "风控经理", description: "选择模型、评级与风险复核" },
  { token: "dev-approver", label: "授信审批人", description: "审批额度、账期与最终策略" },
  { token: "dev-approver-peer", label: "授信审批人乙", description: "委员会级授信第二独立签署人" },
  { token: "dev-client", label: "企业客户", description: "维护本企业资料" },
  { token: "dev-model-admin", label: "模型管理员", description: "模型治理与配置" },
  { token: "dev-auditor", label: "审计人员", description: "审计追溯与可信锚点签发" },
  { token: "dev-operations", label: "运营值班", description: "运行 SLA 扫描与升级催办" },
  { token: "dev-admin", label: "平台管理员", description: "本地演示全权限" },
] as const;

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "dev-manager";
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${getToken()}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const error = (await response.json()) as ApiErrorShape;
      if (error.detail) message = error.detail;
    } catch {
      // Non-JSON gateway errors keep the status-based message.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function queryString(values: object): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (typeof value === "string" && value) params.set(key, value); });
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function download(path: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!response.ok) {
    let message = `下载失败（${response.status}）`;
    try { message = ((await response.json()) as ApiErrorShape).detail ?? message; } catch { /* Keep status message. */ }
    throw new Error(message);
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? "scorecard-monitoring-events.csv";
  const link = document.createElement("a");
  link.href = blobUrl; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
  URL.revokeObjectURL(blobUrl);
}

export const api = {
  me: () => request<Principal>("/auth/me"),
  counterparties: () => request<Counterparty[]>("/counterparties"),
  rawProfile: (counterpartyId: string) => request<RawEnterpriseProfile>(`/counterparties/${counterpartyId}/raw-profile`),
  enterpriseDataProfile: (counterpartyId: string) => request<EnterpriseDataProfile>(`/data-governance/counterparties/${counterpartyId}/profile`),
  enterpriseDataConflicts: (counterpartyId: string) => request<EnterpriseDataConflict[]>(`/data-governance/counterparties/${counterpartyId}/conflicts`),
  ratingReadiness: (counterpartyId: string, templateKey = "corporate_credit_v2") => request<RatingReadiness>(`/data-governance/counterparties/${counterpartyId}/rating-readiness?template_key=${encodeURIComponent(templateKey)}`),
  enterpriseFieldLineage: (counterpartyId: string, fieldPath: string) => request<EnterpriseFieldLineage>(`/data-governance/counterparties/${counterpartyId}/lineage?field_path=${encodeURIComponent(fieldPath)}`),
  enterpriseDataImports: (counterpartyId: string) => request<EnterpriseDataImport[]>(`/data-governance/imports?counterparty_id=${encodeURIComponent(counterpartyId)}`),
  createEnterpriseDataImport: (payload: { import_key: string; counterparty_id: string; source_type: EnterpriseDataImport["source_type"]; source_name: string; schema_version: string; as_of_date: string; evidence_reference: string; payload: Record<string, unknown>; field_evidence: Record<string, { reference?: string; locator?: string }> }) =>
    request<EnterpriseDataImport>("/data-governance/imports", { method: "POST", body: JSON.stringify(payload) }),
  createEnterpriseDataResolution: (payload: { counterparty_id: string; field_path: string; selected_field_id: string; reason_category: EnterpriseDataResolution["reason_category"]; rationale: string }) =>
    request<EnterpriseDataResolution>("/data-governance/resolutions", { method: "POST", body: JSON.stringify(payload) }),
  reviewEnterpriseDataResolution: (id: string, payload: { expected_row_version: number; decision: "approve" | "reject"; comment: string }) =>
    request<EnterpriseDataResolution>(`/data-governance/resolutions/${id}/review`, { method: "POST", body: JSON.stringify(payload) }),
  approvalCases: () => request<ApprovalCase[]>("/approval-cases"),
  approvalCase: (id: string) => request<ApprovalCase>(`/approval-cases/${id}`),
  createApprovalCase: (counterpartyId: string) =>
    request<ApprovalCase>("/approval-cases", { method: "POST", body: JSON.stringify({ counterparty_id: counterpartyId }) }),
  advanceApprovalCase: (id: string, rowVersion: number, payload: Record<string, unknown>) =>
    request<ApprovalCase>(`/approval-cases/${id}/advance`, {
      method: "POST",
      body: JSON.stringify({ expected_row_version: rowVersion, payload }),
    }),
  automateApprovalCase: (id: string, rowVersion: number, templateKey?: string) =>
    request<ApprovalCase>(`/approval-cases/${id}/automate`, {
      method: "POST",
      body: JSON.stringify({ expected_row_version: rowVersion, ...(templateKey ? { template_key: templateKey } : {}) }),
    }),
  reviewRenewalRisk: (id: string, payload: { expected_row_version: number; conclusion: RenewalRiskReview["conclusion"]; review_note: string; control_measures: string[] }) =>
    request<ApprovalCase>(`/approval-cases/${id}/renewal-risk-review`, { method: "POST", body: JSON.stringify(payload) }),
  actOnApprovalCase: (id: string, rowVersion: number, action: ApprovalAction, reason: string, requiredDocumentTypes: string[] = []) =>
    request<ApprovalCase>(`/approval-cases/${id}/actions`, {
      method: "POST",
      body: JSON.stringify({ action, reason, expected_row_version: rowVersion, required_document_types: requiredDocumentTypes }),
    }),
  signoffApprovalCase: (id: string, rowVersion: number, slotKey: string, decision: "approve" | "reject", comment: string) =>
    request<ApprovalCase>(`/approval-cases/${id}/signoffs`, {
      method: "POST",
      body: JSON.stringify({ slot_key: slotKey, decision, comment, expected_row_version: rowVersion }),
    }),
  authorityPolicies: () => request<AuthorityPolicyRecord[]>("/authority-policies"),
  activeAuthorityPolicy: () => request<AuthorityPolicySnapshot>("/authority-policies/active"),
  evaluateAuthorityPolicy: (policyVersion: string, config: AuthorityPolicyConfig) =>
    request<AuthorityPolicyImpact>("/authority-policies/impact", { method: "POST", body: JSON.stringify({ policy_version: policyVersion, config }) }),
  compareAuthorityPolicyScenarios: (scenarios: Array<{ key: string; name: string; description: string; config: AuthorityPolicyConfig }>) =>
    request<AuthorityPolicyScenarioComparison>("/authority-policies/scenarios", { method: "POST", body: JSON.stringify({ scenarios }) }),
  createAuthorityPolicyRestoreDraft: (payload: { source_policy_ref: string; policy_version: string; change_reason: string }) =>
    request<AuthorityPolicyRecord>("/authority-policies/restore-drafts", { method: "POST", body: JSON.stringify(payload) }),
  createAuthorityPolicy: (payload: { policy_version: string; change_reason: string; config: AuthorityPolicyConfig }) =>
    request<AuthorityPolicyRecord>("/authority-policies", { method: "POST", body: JSON.stringify(payload) }),
  updateAuthorityPolicy: (id: string, payload: { expected_row_version: number; change_reason: string; config: AuthorityPolicyConfig }) =>
    request<AuthorityPolicyRecord>(`/authority-policies/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  submitAuthorityPolicy: (id: string, rowVersion: number) =>
    request<AuthorityPolicyRecord>(`/authority-policies/${id}/submit`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  reviewAuthorityPolicy: (id: string, rowVersion: number, decision: "publish" | "reject", comment: string, effectiveAt?: string) =>
    request<AuthorityPolicyRecord>(`/authority-policies/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment, effective_at: effectiveAt }) }),
  authorityPolicyActivationStatus: () =>
    request<AuthorityPolicyActivationStatus>("/authority-policies/activation-status"),
  authorityPolicyEvidence: (id: string) =>
    request<AuthorityPolicyEvidence>(`/authority-policies/${id}/evidence`),
  authorityPolicyEvidenceAnchors: (id: string) =>
    request<AuthorityPolicyEvidenceAnchor[]>(`/authority-policies/${id}/evidence/anchors`),
  issueAuthorityPolicyEvidenceAnchor: (id: string) =>
    request<AuthorityPolicyEvidenceAnchor>(`/authority-policies/${id}/evidence/anchors`, { method: "POST" }),
  authorityPolicyEvidenceAnchor: (anchorId: string) =>
    request<AuthorityPolicyEvidenceAnchor>(`/authority-policies/evidence/anchors/${anchorId}`),
  authorityPolicyEvidenceAnchorReceipt: (anchorId: string) =>
    request<AuthorityPolicyEvidenceAnchorReceipt>(`/authority-policies/evidence/anchors/${anchorId}/receipt`),
  revokeAuthorityPolicyEvidenceAnchor: (anchorId: string, rowVersion: number, reason: string) =>
    request<AuthorityPolicyEvidenceAnchor>(`/authority-policies/evidence/anchors/${anchorId}/revoke`, {
      method: "POST",
      body: JSON.stringify({ expected_row_version: rowVersion, reason }),
    }),
  replaceAuthorityPolicyEvidenceAnchor: (anchorId: string, rowVersion: number, reason: string) =>
    request<AuthorityPolicyEvidenceAnchor>(`/authority-policies/evidence/anchors/${anchorId}/replace`, {
      method: "POST",
      body: JSON.stringify({ expected_row_version: rowVersion, reason }),
    }),
  compareAuthorityPolicyEvidence: (basePolicyId: string, candidatePolicyId: string) =>
    request<AuthorityPolicyEvidenceComparison>(`/authority-policies/evidence/compare?base_policy_id=${encodeURIComponent(basePolicyId)}&candidate_policy_id=${encodeURIComponent(candidatePolicyId)}`),
  activateDueAuthorityPolicy: (payload?: { run_key?: string; trigger_type?: "manual" | "scheduler" }) =>
    request<AuthorityPolicyActivationScan>("/authority-policies/activation-scan", { method: "POST", body: payload ? JSON.stringify(payload) : undefined }),
  acknowledgeAuthorityPolicyActivation: (runId: string, rowVersion: number, note: string) =>
    request<AuthorityPolicyActivationRun>(`/authority-policies/activation-runs/${runId}/acknowledge`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, note }) }),
  retryAuthorityPolicyActivation: (runId: string, rowVersion: number, note: string, runKey?: string) =>
    request<AuthorityPolicyActivationScan>(`/authority-policies/activation-runs/${runId}/retry`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, note, run_key: runKey }) }),
  cancelAuthorityPolicySchedule: (id: string, rowVersion: number, reason: string) =>
    request<AuthorityPolicyRecord>(`/authority-policies/${id}/cancel-schedule`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, reason }) }),
  creditReports: (caseId: string) => request<CreditReport[]>(`/credit-reports?case_id=${encodeURIComponent(caseId)}`),
  createCreditReport: (caseId: string) => request<CreditReport>("/credit-reports", { method: "POST", body: JSON.stringify({ case_id: caseId }) }),
  decisionVariances: (caseId?: string) => request<DecisionVariance[]>(`/decision-governance/variances${caseId ? `?case_id=${encodeURIComponent(caseId)}` : ""}`),
  decisionGovernanceSummary: () => request<DecisionGovernanceSummary>("/decision-governance/summary"),
  verifyCreditReport: (id: string) => request<CreditReportIntegrity>(`/credit-reports/${id}/integrity`),
  downloadCreditReport: async (report: CreditReport) => {
    const response = await fetch(`${API_BASE}/credit-reports/${report.id}/download`, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!response.ok) {
      let message = `报告下载失败（${response.status}）`;
      try { const payload = await response.json() as ApiErrorShape; if (payload.detail) message = payload.detail; } catch { /* keep status message */ }
      throw new Error(message);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = `${report.report_no}-信用评级与授信决策报告.pdf`;
    anchor.click();
    URL.revokeObjectURL(url);
  },
  runRating: (counterpartyId: string, templateKey = "general") =>
    request<RatingResult>("/ratings/run", {
      method: "POST",
      body: JSON.stringify({ counterparty_id: counterpartyId, template_key: templateKey }),
    }),
  portfolioRatingBatches: (templateKey?: string) => request<PortfolioRatingBatch[]>(`/ratings/batches${templateKey ? `?template_key=${encodeURIComponent(templateKey)}` : ""}`),
  createPortfolioRatingBatch: (payload: { batch_key: string; template_key: string; counterparty_type: "all" | "supplier" | "customer" }) =>
    request<PortfolioRatingBatch>("/ratings/batches", { method: "POST", body: JSON.stringify(payload) }),
  models: () => request<ModelSummary[]>("/models"),
  model: (templateKey: string) => request<ModelDetail>(`/models/${templateKey}`),
  ruleDefinitions: () => request<RuleDefinition[]>("/rule-center/rules"),
  createRuleDefinition: (payload: { code: string; name: string; rule_type: RuleDefinition["rule_type"]; category?: string | null; enabled: boolean; conditions_json: RuleCondition[]; condition_relation: "all" | "any"; actions_json: RuleAction[]; priority: number }) =>
    request<RuleDefinition>("/rule-center/rules", { method: "POST", body: JSON.stringify(payload) }),
  testRuleDefinition: (code: string, context: Record<string, unknown>) =>
    request<RuleTestResult>(`/rule-center/rules/${encodeURIComponent(code)}/test`, { method: "POST", body: JSON.stringify({ context }) }),
  ruleSetDefinitions: () => request<RuleSetDefinition[]>("/rule-center/rule-sets"),
  createRuleSetDefinition: (payload: { code: string; name: string; rule_codes: string[]; evaluation_strategy: RuleSetDefinition["evaluation_strategy"] }) =>
    request<RuleSetDefinition>("/rule-center/rule-sets", { method: "POST", body: JSON.stringify(payload) }),
  decisionPipelines: () => request<DecisionPipelineDefinition[]>("/rule-center/pipelines"),
  createDecisionPipeline: (payload: { code: string; name: string; stages_json: PipelineStage[] }) =>
    request<DecisionPipelineDefinition>("/rule-center/pipelines", { method: "POST", body: JSON.stringify(payload) }),
  simulateDecisionPipeline: (code: string, counterparty: Record<string, unknown>, config: Record<string, unknown>) =>
    request<PipelineSimulationResult>(`/rule-center/pipelines/${encodeURIComponent(code)}/simulate`, { method: "POST", body: JSON.stringify({ counterparty, config }) }),
  ruleCenterGovernanceChanges: (assetType?: RuleCenterAssetType, code?: string) => {
    const query = new URLSearchParams();
    if (assetType) query.set("asset_type", assetType);
    if (code) query.set("code", code);
    return request<RuleCenterGovernanceChange[]>(`/rule-center/governance/changes${query.size ? `?${query}` : ""}`);
  },
  createRuleCenterGovernanceChange: (payload: { asset_type: RuleCenterAssetType; definition: Record<string, unknown>; change_reason: string }) =>
    request<RuleCenterGovernanceChange>("/rule-center/governance/changes", { method: "POST", body: JSON.stringify(payload) }),
  updateRuleCenterGovernanceChange: (id: string, payload: { expected_row_version: number; definition: Record<string, unknown>; change_reason: string }) =>
    request<RuleCenterGovernanceChange>(`/rule-center/governance/changes/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  submitRuleCenterGovernanceChange: (id: string, rowVersion: number) =>
    request<RuleCenterGovernanceChange>(`/rule-center/governance/changes/${id}/submit`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  reviewRuleCenterGovernanceChange: (id: string, rowVersion: number, decision: "publish" | "reject", comment: string, effectiveAt?: string) =>
    request<RuleCenterGovernanceChange>(`/rule-center/governance/changes/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment, effective_at: effectiveAt || null }) }),
  activateDueRuleCenterChanges: (asOf = new Date().toISOString()) =>
    request<RuleCenterActivationResult>("/rule-center/governance/activation-scan", { method: "POST", body: JSON.stringify({ as_of: asOf }) }),
  ruleCenterVersionHistory: (assetType: RuleCenterAssetType, code: string) =>
    request<RuleCenterVersionHistory[]>(`/rule-center/governance/history?asset_type=${encodeURIComponent(assetType)}&code=${encodeURIComponent(code)}`),
  createRuleCenterRestoreDraft: (payload: { asset_type: RuleCenterAssetType; code: string; version: number; change_reason: string }) =>
    request<RuleCenterGovernanceChange>("/rule-center/governance/restore-drafts", { method: "POST", body: JSON.stringify(payload) }),
  previewRuleCenterReleasePackage: (changeIds: string[]) =>
    request<RuleCenterPackagePreview>("/rule-center/governance/packages/impact", { method: "POST", body: JSON.stringify({ change_ids: changeIds }) }),
  ruleCenterReleasePackages: () => request<RuleCenterReleasePackage[]>("/rule-center/governance/packages"),
  createRuleCenterReleasePackage: (payload: { name: string; change_reason: string; change_ids: string[] }) =>
    request<RuleCenterReleasePackage>("/rule-center/governance/packages", { method: "POST", body: JSON.stringify(payload) }),
  submitRuleCenterReleasePackage: (id: string, rowVersion: number) =>
    request<RuleCenterReleasePackage>(`/rule-center/governance/packages/${id}/submit`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  reviewRuleCenterReleasePackage: (id: string, rowVersion: number, decision: "publish" | "reject", comment: string) =>
    request<RuleCenterReleasePackage>(`/rule-center/governance/packages/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment }) }),
  ruleCenterPackageReplays: (id: string) => request<RuleCenterReplayRun[]>(`/rule-center/governance/packages/${id}/replays`),
  ruleCenterReplayDatasets: () => request<RuleCenterReplayDataset[]>("/rule-center/governance/replay-datasets"),
  createRuleCenterReplayDataset: (payload: { code: string; name: string; description: string }) => request<RuleCenterReplayDataset>("/rule-center/governance/replay-datasets", { method: "POST", body: JSON.stringify(payload) }),
  ruleCenterReplaySnapshots: () => request<RuleCenterReplaySnapshot[]>("/rule-center/governance/replay-datasets/snapshots"),
  importRuleCenterReplaySnapshot: (datasetId: string, payload: { source_name: string; schema_version: string; as_of_date: string; evidence_reference: string; data_classification: "deidentified" | "synthetic"; field_mapping: Record<string, string>; label_field?: string; observed_at_field?: string; records: Array<Record<string, unknown>> }) => request<RuleCenterReplaySnapshot>(`/rule-center/governance/replay-datasets/${datasetId}/snapshots`, { method: "POST", body: JSON.stringify(payload) }),
  ruleCenterReplayComparisons: () => request<RuleCenterReplayComparison[]>("/rule-center/governance/replay-comparisons"),
  runRuleCenterReplayComparison: (payload: { dataset_snapshot_id: string; champion_model_key: string; challenger_model_key: string; champion_pipeline_code?: string; challenger_pipeline_code?: string; segment_field: string; positive_labels: string[]; positive_admissions: string[]; sample_limit: number; max_execution_failure_rate: number; max_psi: number; max_rating_change_rate: number; max_admission_change_rate: number; max_absolute_average_score_delta: number; max_segment_absolute_score_delta: number; max_ks_drop: number; require_labeled_evidence: boolean }) => request<RuleCenterReplayComparison>("/rule-center/governance/replay-comparisons", { method: "POST", body: JSON.stringify(payload) }),
  requestRuleCenterReplayComparisonException: (comparisonId: string, payload: { reason: string; business_impact: string; compensating_controls: string; valid_until: string }) => request<RuleCenterReplayComparisonException>(`/rule-center/governance/replay-comparisons/${comparisonId}/exceptions`, { method: "POST", body: JSON.stringify(payload) }),
  reviewRuleCenterReplayComparisonException: (comparisonId: string, exceptionId: string, payload: { expected_row_version: number; decision: "approve" | "reject"; comment: string }) => request<RuleCenterReplayComparisonException>(`/rule-center/governance/replay-comparisons/${comparisonId}/exceptions/${exceptionId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  runRuleCenterPackageReplay: (id: string, payload: { dataset_snapshot_id: string; model_key: string; pipeline_code?: string; sample_limit: number; min_sample_count: number; max_decision_change_rate: number; max_execution_failure_rate: number }) =>
    request<RuleCenterReplayRun>(`/rule-center/governance/packages/${id}/replays`, { method: "POST", body: JSON.stringify(payload) }),
  indicatorPool: () => request<IndicatorPoolResponse>("/indicator-pool"),
  indicatorCatalog: () => request<{ count: number; items: IndicatorCatalogItem[] }>("/indicator-center/catalog"),
  scorecards: () => request<ScorecardAsset[]>("/indicator-center/scorecards"),
  scorecardChanges: () => request<ScorecardChange[]>("/indicator-center/scorecard-changes"),
  scorecardDevelopmentRuns: () => request<ScorecardDevelopmentRun[]>("/indicator-center/scorecard-development-runs"),
  scorecardDevelopmentTrends: () => request<ScorecardDevelopmentTrends>("/indicator-center/scorecard-development-trends"),
  scorecardPortfolioStability: () => request<ScorecardPortfolioStability>("/indicator-center/scorecard-portfolio-stability"),
  creditCalibrationConfig: () => request<CreditCalibrationConfig>("/indicator-center/credit-calibration/config"),
  analyzeCreditCalibration: (payload: CreditCalibrationAnalyzeRequest) => request<CreditCalibrationResult>("/indicator-center/credit-calibration/analyze", { method: "POST", body: JSON.stringify(payload) }),
  creditCalibrationPlans: () => request<CreditCalibrationPlan[]>("/indicator-center/credit-calibration/plans"),
  createCreditCalibrationPlan: (payload: { code: string; name: string; template_key: "corporate_credit_v2"; candidate: CreditCalibrationAnalyzeRequest["candidate"]; positive_labels: string[]; sample_limit: number; business_basis: string }) => request<CreditCalibrationPlan>("/indicator-center/credit-calibration/plans", { method: "POST", body: JSON.stringify(payload) }),
  updateCreditCalibrationPlan: (id: string, payload: { expected_row_version: number; code: string; name: string; template_key: "corporate_credit_v2"; candidate: CreditCalibrationAnalyzeRequest["candidate"]; positive_labels: string[]; sample_limit: number; business_basis: string }) => request<CreditCalibrationPlan>(`/indicator-center/credit-calibration/plans/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  runCreditCalibrationPlan: (id: string, rowVersion: number, snapshotId: string) => request<CreditCalibrationRun>(`/indicator-center/credit-calibration/plans/${id}/runs`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, dataset_snapshot_id: snapshotId }) }),
  submitCreditCalibrationPlan: (id: string, rowVersion: number) => request<CreditCalibrationPlan>(`/indicator-center/credit-calibration/plans/${id}/submit`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  reviewCreditCalibrationPlan: (id: string, rowVersion: number, decision: "approve" | "reject", comment: string) => request<CreditCalibrationPlan>(`/indicator-center/credit-calibration/plans/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment }) }),
  compareCreditCalibrationPlans: (planIds: string[]) => request<CreditCalibrationComparison>("/indicator-center/credit-calibration/comparisons", { method: "POST", body: JSON.stringify({ plan_ids: planIds }) }),
  createGovernedCreditCalibrationModelChange: (planId: string, payload: { expected_row_version: number; run_id: string; candidate_version: string; change_reason: string }) => request<ModelChangeRecord>(`/indicator-center/credit-calibration/plans/${planId}/model-changes`, { method: "POST", body: JSON.stringify(payload) }),
  scorecardMonitoringPlans: () => request<ScorecardMonitoringPlan[]>("/indicator-center/scorecard-monitoring-plans"),
  scorecardMonitoringEvents: (filters: ScorecardMonitoringEventFilters = {}) => request<ScorecardMonitoringEvent[]>(`/indicator-center/scorecard-monitoring-events${queryString(filters)}`),
  exportScorecardMonitoringEvents: (filters: ScorecardMonitoringEventFilters = {}) => download(`/indicator-center/scorecard-monitoring-events/export${queryString(filters)}`),
  createScorecardMonitoringPlan: (plan: { code: string; name: string; description: string; scorecard_asset_id: string; validation_policy_id: string; training_dataset_id: string; validation_dataset_id?: string; oot_dataset_id?: string; run_config: ScorecardMonitoringRunConfig; cadence: "monthly" | "quarterly"; timezone_name: "Asia/Shanghai" | "UTC"; enabled: boolean; next_run_at: string; owner: string }) => request<ScorecardMonitoringPlan>("/indicator-center/scorecard-monitoring-plans", { method: "POST", body: JSON.stringify({ plan }) }),
  updateScorecardMonitoringPlan: (id: string, rowVersion: number, plan: { code: string; name: string; description: string; scorecard_asset_id: string; validation_policy_id: string; training_dataset_id: string; validation_dataset_id?: string; oot_dataset_id?: string; run_config: ScorecardMonitoringRunConfig; cadence: "monthly" | "quarterly"; timezone_name: "Asia/Shanghai" | "UTC"; enabled: boolean; next_run_at: string; owner: string }) => request<ScorecardMonitoringPlan>(`/indicator-center/scorecard-monitoring-plans/${id}`, { method: "PUT", body: JSON.stringify({ expected_row_version: rowVersion, plan }) }),
  runScorecardMonitoringPlan: (id: string, rowVersion: number) => request<ScorecardMonitoringExecution>(`/indicator-center/scorecard-monitoring-plans/${id}/run`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  runDueScorecardMonitoringPlans: () => request<ScorecardMonitoringSchedulerExecution>("/indicator-center/scorecard-monitoring-plans/run-due", { method: "POST", body: JSON.stringify({ max_plans: 50, trigger_type: "manual" }) }),
  scorecardMonitoringSchedulerHealth: () => request<ScorecardMonitoringSchedulerHealth>("/indicator-center/scorecard-monitoring-scheduler/health"),
  retryScorecardMonitoringSchedulerRun: (id: string, reason: string) => request<ScorecardMonitoringSchedulerExecution>(`/indicator-center/scorecard-monitoring-scheduler/runs/${id}/retry`, { method: "POST", body: JSON.stringify({ reason, max_plans: 50 }) }),
  actionScorecardMonitoringEvent: (id: string, payload: { expected_row_version: number; action: "assign" | "acknowledge" | "remediate" | "submit_revalidation" | "review_revalidation"; assignee?: string; remediation_plan?: string; remediation_result?: string; revalidation_run_id?: string; decision?: "pass" | "fail"; conclusion?: string }) => request<ScorecardMonitoringEvent>(`/indicator-center/scorecard-monitoring-events/${id}/action`, { method: "POST", body: JSON.stringify(payload) }),
  bulkAssignScorecardMonitoringEvents: (items: Array<{ event_id: string; expected_row_version: number }>, assignee: string, reason: string) => request<ScorecardMonitoringBulkAssignResult>("/indicator-center/scorecard-monitoring-events/bulk-assign", { method: "POST", body: JSON.stringify({ items, assignee, reason }) }),
  scorecardMonitoringSavedViews: () => request<ScorecardMonitoringSavedView[]>("/indicator-center/scorecard-monitoring-saved-views"),
  createScorecardMonitoringSavedView: (payload: { name: string; filters: ScorecardMonitoringEventFilters; is_default: boolean }) => request<ScorecardMonitoringSavedView>("/indicator-center/scorecard-monitoring-saved-views", { method: "POST", body: JSON.stringify(payload) }),
  updateScorecardMonitoringSavedView: (id: string, expectedRowVersion: number, payload: { name: string; filters: ScorecardMonitoringEventFilters; is_default: boolean }) => request<ScorecardMonitoringSavedView>(`/indicator-center/scorecard-monitoring-saved-views/${id}`, { method: "PUT", body: JSON.stringify({ expected_row_version: expectedRowVersion, ...payload }) }),
  scorecardMonitoringSlaPolicies: () => request<ScorecardMonitoringSlaPolicy[]>("/indicator-center/scorecard-monitoring-sla-policies"),
  createScorecardMonitoringSlaPolicy: (policy: Omit<ScorecardMonitoringSlaPolicy, "id" | "version" | "status" | "is_active" | "config_hash" | "change_reason" | "created_by" | "created_by_name" | "reviewed_by_name" | "review_comment" | "row_version" | "created_at" | "submitted_at" | "published_at">, changeReason: string) => request<ScorecardMonitoringSlaPolicy>("/indicator-center/scorecard-monitoring-sla-policies", { method: "POST", body: JSON.stringify({ policy, change_reason: changeReason }) }),
  updateScorecardMonitoringSlaPolicy: (id: string, rowVersion: number, policy: Omit<ScorecardMonitoringSlaPolicy, "id" | "version" | "status" | "is_active" | "config_hash" | "change_reason" | "created_by" | "created_by_name" | "reviewed_by_name" | "review_comment" | "row_version" | "created_at" | "submitted_at" | "published_at">, changeReason: string) => request<ScorecardMonitoringSlaPolicy>(`/indicator-center/scorecard-monitoring-sla-policies/${id}`, { method: "PUT", body: JSON.stringify({ expected_row_version: rowVersion, policy, change_reason: changeReason }) }),
  submitScorecardMonitoringSlaPolicy: (id: string, rowVersion: number) => request<ScorecardMonitoringSlaPolicy>(`/indicator-center/scorecard-monitoring-sla-policies/${id}/submit`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  reviewScorecardMonitoringSlaPolicy: (id: string, rowVersion: number, decision: "publish" | "reject", comment: string) => request<ScorecardMonitoringSlaPolicy>(`/indicator-center/scorecard-monitoring-sla-policies/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment }) }),
  validationPolicies: () => request<ScorecardValidationPolicy[]>("/indicator-center/validation-policies"),
  createValidationPolicy: (policy: Omit<ScorecardValidationPolicy, "id" | "version" | "status" | "is_active" | "config_hash" | "change_reason" | "created_by" | "created_by_name" | "reviewed_by_name" | "review_comment" | "row_version" | "created_at" | "submitted_at" | "published_at">, changeReason: string) => request<ScorecardValidationPolicy>("/indicator-center/validation-policies", { method: "POST", body: JSON.stringify({ policy, change_reason: changeReason }) }),
  updateValidationPolicy: (id: string, rowVersion: number, policy: Omit<ScorecardValidationPolicy, "id" | "version" | "status" | "is_active" | "config_hash" | "change_reason" | "created_by" | "created_by_name" | "reviewed_by_name" | "review_comment" | "row_version" | "created_at" | "submitted_at" | "published_at">, changeReason: string) => request<ScorecardValidationPolicy>(`/indicator-center/validation-policies/${id}`, { method: "PUT", body: JSON.stringify({ expected_row_version: rowVersion, policy, change_reason: changeReason }) }),
  submitValidationPolicy: (id: string, rowVersion: number) => request<ScorecardValidationPolicy>(`/indicator-center/validation-policies/${id}/submit`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  reviewValidationPolicy: (id: string, rowVersion: number, decision: "publish" | "reject", comment: string) => request<ScorecardValidationPolicy>(`/indicator-center/validation-policies/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment }) }),
  createScorecardDevelopmentRun: (payload: { scorecard_asset_id: string; validation_policy_id?: string; dataset_snapshot_id: string; validation_snapshot_id?: string; oot_snapshot_id?: string; subject_id_field: string; predicted_probability_field?: string; segment_fields: string[]; sensitive_attribute_fields: string[]; min_segment_sample_count: number; classification_threshold: number; validation_thresholds: ScorecardValidationThresholds; positive_labels: string[]; observation_start?: string; observation_end?: string; performance_window_days: number; maturity_days: number; min_sample_count: number; min_event_count: number; min_non_event_count: number; exclusion_rules: ScorecardDevelopmentExclusionRule[] }) => request<ScorecardDevelopmentRun>("/indicator-center/scorecard-development-runs", { method: "POST", body: JSON.stringify(payload) }),
  reviewScorecardDevelopmentRun: (id: string, rowVersion: number, decision: "approve" | "reject", comment: string) => request<ScorecardDevelopmentRun>(`/indicator-center/scorecard-development-runs/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment }) }),
  createScorecardChange: (definition: ScorecardDefinitionPayload, changeReason: string) => request<ScorecardChange>("/indicator-center/scorecard-changes", { method: "POST", body: JSON.stringify({ definition, change_reason: changeReason }) }),
  updateScorecardChange: (id: string, rowVersion: number, definition: ScorecardDefinitionPayload, changeReason: string) => request<ScorecardChange>(`/indicator-center/scorecard-changes/${id}`, { method: "PUT", body: JSON.stringify({ expected_row_version: rowVersion, definition, change_reason: changeReason }) }),
  submitScorecardChange: (id: string, rowVersion: number) => request<ScorecardChange>(`/indicator-center/scorecard-changes/${id}/submit`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  reviewScorecardChange: (id: string, rowVersion: number, decision: "publish" | "reject", comment: string) => request<ScorecardChange>(`/indicator-center/scorecard-changes/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment }) }),
  indicatorObservations: (counterpartyId: string, indicatorId?: string) => request<EnterpriseIndicatorObservation[]>(`/indicator-observations?counterparty_id=${encodeURIComponent(counterpartyId)}${indicatorId ? `&indicator_id=${encodeURIComponent(indicatorId)}` : ""}`),
  createIndicatorObservation: (payload: { counterparty_id: string; indicator_id: string; values: Record<string, number | boolean>; evidence_reference: string; evidence_document_id?: string; as_of_date: string }) =>
    request<EnterpriseIndicatorObservation>("/indicator-observations", { method: "POST", body: JSON.stringify(payload) }),
  reviewIndicatorObservation: (id: string, payload: { expected_row_version: number; decision: "verify" | "reject"; comment: string }) =>
    request<EnterpriseIndicatorObservation>(`/indicator-observations/${id}/review`, { method: "POST", body: JSON.stringify(payload) }),
  ratingTrace: (counterpartyId: string, templateKey: string) =>
    request<RatingTrace>("/ratings/trace", {
      method: "POST",
      body: JSON.stringify({ counterparty_id: counterpartyId, template_key: templateKey }),
    }),
  modelImpact: (counterpartyId: string, templateKey: string, fieldPath: string, newValue: number) =>
    request<ModelImpact>("/models/impact", {
      method: "POST",
      body: JSON.stringify({ counterparty_id: counterpartyId, template_key: templateKey, field_path: fieldPath, new_value: newValue }),
    }),
  modelChanges: (templateKey: string) => request<ModelChangeRecord[]>(`/model-governance/changes?template_key=${encodeURIComponent(templateKey)}`),
  modelValidation: (templateKey: string, candidateChangeId?: string) => request<ModelValidationReport>(`/model-governance/validation?template_key=${encodeURIComponent(templateKey)}${candidateChangeId ? `&candidate_change_id=${encodeURIComponent(candidateChangeId)}` : ""}`),
  createModelChange: (payload: { template_key: string; candidate_version: string; change_reason: string; weights: Record<string, number>; thresholds: Record<string, number>; strong_rules: StrongRule[]; strategy_mapping: Array<Record<string, string | number>>; indicator_selection: Array<{ indicator_id: string; weight: number; enabled: boolean }>; risk_screening_policy: RiskScreeningPolicy; scorecard_id?: string | null; scorecard_validation_run_id?: string | null }) =>
    request<ModelChangeRecord>("/model-governance/changes", { method: "POST", body: JSON.stringify(payload) }),
  updateModelChange: (id: string, payload: { expected_row_version: number; change_reason: string; weights: Record<string, number>; thresholds: Record<string, number>; strong_rules: StrongRule[]; strategy_mapping: Array<Record<string, string | number>>; indicator_selection: Array<{ indicator_id: string; weight: number; enabled: boolean }>; risk_screening_policy: RiskScreeningPolicy; scorecard_id?: string | null; scorecard_validation_run_id?: string | null }) =>
    request<ModelChangeRecord>(`/model-governance/changes/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  runModelChangeComparisonEvidence: (id: string, payload: { expected_row_version: number; dataset_snapshot_id: string; champion_pipeline_code?: string; challenger_pipeline_code?: string; segment_field: string; positive_labels: string[]; positive_admissions: string[]; sample_limit: number; max_execution_failure_rate: number; max_psi: number; max_rating_change_rate: number; max_admission_change_rate: number; max_absolute_average_score_delta: number; max_segment_absolute_score_delta: number; max_ks_drop: number; require_labeled_evidence: boolean; evidence_valid_days: number }) =>
    request<ModelChangeRecord>(`/model-governance/changes/${id}/comparison-evidence/run`, { method: "POST", body: JSON.stringify(payload) }),
  submitModelChange: (id: string, rowVersion: number) =>
    request<ModelChangeRecord>(`/model-governance/changes/${id}/submit`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion }) }),
  reviewModelChange: (id: string, rowVersion: number, decision: "publish" | "reject", comment: string) =>
    request<ModelChangeRecord>(`/model-governance/changes/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, comment }) }),
  modelReleases: (templateKey: string) => request<ModelReleaseRecord[]>(`/model-governance/releases?template_key=${encodeURIComponent(templateKey)}`),
  rollbackModelRelease: (id: string, comment: string) =>
    request<ModelReleaseRecord>(`/model-governance/releases/${id}/rollback`, { method: "POST", body: JSON.stringify({ comment }) }),
  modelMonitoringSummary: (templateKey: string) => request<MonitoringSummary>(`/model-governance/monitoring-summary?template_key=${encodeURIComponent(templateKey)}`),
  modelOutcomes: (templateKey: string) => request<ModelOutcome[]>(`/model-governance/outcomes?template_key=${encodeURIComponent(templateKey)}`),
  createModelOutcome: (payload: ModelOutcomePayload) =>
    request<ModelOutcome>("/model-governance/outcomes", { method: "POST", body: JSON.stringify(payload) }),
  createModelOutcomesBatch: (outcomes: ModelOutcomePayload[]) =>
    request<{ total: number; created: number; idempotent: number; rejected: number; results: Array<{ index: number; external_observation_id: string; status: "created" | "idempotent" | "rejected"; outcome_id: string | null; error: string | null }> }>("/model-governance/outcomes/batch", { method: "POST", body: JSON.stringify({ outcomes }) }),
  outcomeImports: (templateKey: string) => request<ModelOutcomeImport[]>(`/model-governance/outcome-imports?template_key=${encodeURIComponent(templateKey)}`),
  createOutcomeImport: (payload: { import_key: string; source: string; template_key: string; population_period: string; expected_count: number; outcomes: ModelOutcomePayload[] }) =>
    request<ModelOutcomeImport>("/model-governance/outcome-imports", { method: "POST", body: JSON.stringify(payload) }),
  verifyModelOutcome: (id: string, rowVersion: number, decision: "verify" | "reject", note: string) =>
    request<ModelOutcome>(`/model-governance/outcomes/${id}/verify`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, note }) }),
  monitoringIssues: (templateKey: string) => request<MonitoringIssue[]>(`/model-governance/issues?template_key=${encodeURIComponent(templateKey)}`),
  modelMonitoringRuns: (templateKey: string) => request<ModelMonitoringRun[]>(`/model-governance/runs?template_key=${encodeURIComponent(templateKey)}`),
  executeModelMonitoringRun: (payload: { run_key: string; template_key: string; as_of_period: string; trigger_type: "manual" | "scheduled" }) =>
    request<ModelMonitoringRun>("/model-governance/runs", { method: "POST", body: JSON.stringify(payload) }),
  monitoringSchedules: (templateKey: string) => request<ModelMonitoringSchedule[]>(`/model-governance/schedules?template_key=${encodeURIComponent(templateKey)}`),
  createMonitoringSchedule: (payload: { template_key: string; cadence: "monthly" | "quarterly"; timezone_name: "Asia/Shanghai" | "UTC"; enabled: boolean; next_run_at: string }) =>
    request<ModelMonitoringSchedule>("/model-governance/schedules", { method: "POST", body: JSON.stringify(payload) }),
  updateMonitoringSchedule: (id: string, payload: { expected_row_version: number; cadence: "monthly" | "quarterly"; timezone_name: "Asia/Shanghai" | "UTC"; enabled: boolean; next_run_at: string }) =>
    request<ModelMonitoringSchedule>(`/model-governance/schedules/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  runDueMonitoringSchedules: (asOf = new Date().toISOString()) => request<MonitoringSchedulerTick>("/model-governance/schedules/run-due", { method: "POST", body: JSON.stringify({ as_of: asOf }) }),
  governanceNotifications: (unreadOnly = false) => request<ModelGovernanceNotification[]>(`/model-governance/governance-notifications?unread_only=${unreadOnly}`),
  readGovernanceNotification: (id: string) => request<ModelGovernanceNotification>(`/model-governance/governance-notifications/${id}/read`, { method: "POST" }),
  scanMonitoringIssues: (templateKey: string) => request<MonitoringIssue[]>(`/model-governance/issues/scan?template_key=${encodeURIComponent(templateKey)}`, { method: "POST" }),
  startMonitoringRemediation: (id: string, rowVersion: number, owner: string, plan: string, dueDays = 30) =>
    request<MonitoringIssue>(`/model-governance/issues/${id}/remediation`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, owner, plan, due_days: dueDays }) }),
  submitMonitoringRevalidation: (id: string, rowVersion: number, result: string) =>
    request<MonitoringIssue>(`/model-governance/issues/${id}/submit-revalidation`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, result }) }),
  reviewMonitoringRevalidation: (id: string, rowVersion: number, decision: "pass" | "fail", conclusion: string) =>
    request<MonitoringIssue>(`/model-governance/issues/${id}/review`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, decision, conclusion }) }),
  linkMonitoringIssueChange: (id: string, rowVersion: number, changeId: string) =>
    request<MonitoringIssue>(`/model-governance/issues/${id}/link-change`, { method: "POST", body: JSON.stringify({ expected_row_version: rowVersion, change_id: changeId }) }),
  creditFacilities: () => request<CreditFacility[]>("/credit-facilities"),
  creditFacility: (id: string) => request<CreditFacilityDetail>(`/credit-facilities/${id}`),
  createFacilityRenewal: (id: string, payload: { expected_row_version: number; requested_limit: number; requested_term_days: number; renewal_reason: string }) =>
    request<ApprovalCase & { idempotent: boolean }>(`/credit-facilities/${id}/renewals`, { method: "POST", body: JSON.stringify(payload) }),
  facilitySummary: () => request<FacilitySummary>("/credit-facilities/summary"),
  facilityAlerts: () => request<FacilityAlert[]>("/credit-facilities/alerts"),
  riskEvents: () => request<RiskEvent[]>("/credit-facilities/risk-events"),
  transactFacility: (id: string, payload: { transaction_ref: string; transaction_type: "drawdown" | "repayment"; amount: number; expected_row_version: number; reason: string }) =>
    request<{ facility: CreditFacility; idempotent: boolean }>(`/credit-facilities/${id}/transactions`, { method: "POST", body: JSON.stringify(payload) }),
  reviewFacility: (id: string, payload: { expected_row_version: number; rating: string; next_review_days: number; conclusion: string }) =>
    request<CreditFacility>(`/credit-facilities/${id}/reviews`, { method: "POST", body: JSON.stringify(payload) }),
  scanFacilities: () => request<{ active_facilities_scanned: number; facilities_expired: number; alerts_opened: number; control_conditions_scanned: number; control_alerts_opened: number; control_conditions_escalated: number; control_notifications_created: number }>("/credit-facilities/scan", { method: "POST" }),
  acknowledgeFacilityAlert: (id: string) => request<FacilityAlert>(`/credit-facilities/alerts/${id}/acknowledge`, { method: "POST" }),
  createRiskEvent: (id: string, payload: { external_event_id: string; event_type: string; source: string; severity: "warning" | "critical"; occurred_at: string; title: string; description: string; payload: Record<string, unknown> }) =>
    request<{ risk_event: RiskEvent; alert: FacilityAlert; idempotent: boolean }>(`/credit-facilities/${id}/risk-events`, { method: "POST", body: JSON.stringify(payload) }),
  controlFacility: (id: string, payload: { expected_row_version: number; action: "freeze" | "unfreeze" | "reduce_limit" | "close"; target_limit?: number; reason: string }) =>
    request<CreditFacility>(`/credit-facilities/${id}/controls`, { method: "POST", body: JSON.stringify(payload) }),
  completeFacilityControlCondition: (facilityId: string, conditionId: string, payload: { expected_row_version: number; conclusion: string }) =>
    request<FacilityControlCondition>(`/credit-facilities/${facilityId}/control-conditions/${conditionId}/complete`, { method: "POST", body: JSON.stringify(payload) }),
  requestFacilityControlExtension: (facilityId: string, conditionId: string, payload: { expected_condition_version: number; extension_days: number; reason: string }) =>
    request<FacilityControlExtension>(`/credit-facilities/${facilityId}/control-conditions/${conditionId}/extensions`, { method: "POST", body: JSON.stringify(payload) }),
  reviewFacilityControlExtension: (facilityId: string, conditionId: string, extensionId: string, payload: { expected_extension_version: number; expected_condition_version: number; decision: "approve" | "reject"; comment: string }) =>
    request<{ extension: FacilityControlExtension; condition: FacilityControlCondition }>(`/credit-facilities/${facilityId}/control-conditions/${conditionId}/extensions/${extensionId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  disposeFacilityAlert: (id: string, payload: { expected_alert_version: number; expected_facility_version: number; action: "monitor" | "freeze" | "reduce_limit" | "close"; target_limit?: number; conclusion: string }) =>
    request<{ alert: FacilityAlert; facility: CreditFacility }>(`/credit-facilities/alerts/${id}/dispose`, { method: "POST", body: JSON.stringify(payload) }),
  documents: (counterpartyId?: string, caseId?: string) => {
    const query = new URLSearchParams();
    if (counterpartyId) query.set("counterparty_id", counterpartyId);
    if (caseId) query.set("case_id", caseId);
    return request<DocumentRecord[]>(`/documents${query.size ? `?${query}` : ""}`);
  },
  documentChecklist: (counterpartyId: string, templateKey: string, caseId?: string) => {
    const query = new URLSearchParams({ counterparty_id: counterpartyId, template_key: templateKey });
    if (caseId) query.set("case_id", caseId);
    return request<DocumentChecklist>(`/documents/checklist?${query}`);
  },
  renewalDocumentCarryover: (caseId: string, templateKey: string) =>
    request<RenewalDocumentCarryover>(`/documents/renewal-carryover?case_id=${encodeURIComponent(caseId)}&template_key=${encodeURIComponent(templateKey)}`),
  carryOverRenewalDocuments: (caseId: string, templateKey: string, expectedCaseRowVersion: number) =>
    request<RenewalDocumentCarryover>("/documents/renewal-carryover", { method: "POST", body: JSON.stringify({ case_id: caseId, template_key: templateKey, expected_case_row_version: expectedCaseRowVersion }) }),
  documentPrechecks: (counterpartyId?: string, caseId?: string) => {
    const query = new URLSearchParams();
    if (counterpartyId) query.set("counterparty_id", counterpartyId);
    if (caseId) query.set("case_id", caseId);
    return request<DocumentPrecheck[]>(`/documents/prechecks${query.size ? `?${query}` : ""}`);
  },
  documentCorrections: (counterpartyId?: string, caseId?: string) => {
    const query = new URLSearchParams();
    if (counterpartyId) query.set("counterparty_id", counterpartyId);
    if (caseId) query.set("case_id", caseId);
    return request<DocumentCorrection[]>(`/documents/corrections${query.size ? `?${query}` : ""}`);
  },
  documentCorrectionComparison: (correctionId: string) =>
    request<DocumentVersionComparison>(`/documents/corrections/${correctionId}/comparison`),
  uploadDocument: (counterpartyId: string, documentType: string, file: File, caseId?: string, correctionId?: string) => {
    const body = new FormData();
    body.set("counterparty_id", counterpartyId);
    body.set("document_type", documentType);
    if (caseId) body.set("case_id", caseId);
    if (correctionId) body.set("correction_id", correctionId);
    body.set("file", file);
    return request<DocumentRecord>("/documents", { method: "POST", body });
  },
  reviewDocument: (documentId: string, payload: { expected_row_version: number; decision: "verify" | "needs_supplement" | "reject"; comment: string; checks: DocumentCheckResult[] }) =>
    request<DocumentRecord>(`/documents/${documentId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  linkDocumentToCase: (documentId: string, caseId: string, expectedRowVersion: number) =>
    request<DocumentRecord>(`/documents/${documentId}/case`, { method: "POST", body: JSON.stringify({ case_id: caseId, expected_row_version: expectedRowVersion }) }),
  downloadDocument: async (document: DocumentRecord) => {
    const response = await fetch(`${API_BASE}/documents/${document.id}/download`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!response.ok) throw new Error(`下载失败（${response.status}）`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = document.original_name;
    anchor.click();
    URL.revokeObjectURL(url);
  },
  notifications: (unreadOnly = false) => request<NotificationRecord[]>(`/notifications?unread_only=${unreadOnly}`),
  markNotificationRead: (id: string) => request<NotificationRecord>(`/notifications/${id}/read`, { method: "POST" }),
  personalTasks: () => request<PersonalTaskQueue>("/operations/my-tasks"),
  assignPersonalTask: (taskType: "approval" | "correction", taskId: string, action: "claim" | "renew" | "release", expectedRowVersion: number) =>
    request<PersonalTaskAssignment>(`/operations/my-tasks/${taskType}/${taskId}/assignment`, { method: "POST", body: JSON.stringify({ action, expected_row_version: expectedRowVersion }) }),
  teamTasks: () => request<TeamTaskBoard>("/operations/team-tasks"),
  releaseTeamTask: (taskType: "approval" | "correction", taskId: string, expectedRowVersion: number, reason: string) =>
    request<PersonalTaskAssignment>(`/operations/team-tasks/${taskType}/${taskId}/release`, { method: "POST", body: JSON.stringify({ expected_row_version: expectedRowVersion, reason }) }),
  remindTeamTask: (taskType: "approval" | "correction" | "facility_control" | "control_extension", taskId: string, expectedRowVersion: number, reason: string) =>
    request<NotificationRecord>(`/operations/team-tasks/${taskType}/${taskId}/remind`, { method: "POST", body: JSON.stringify({ expected_row_version: expectedRowVersion, reason }) }),
  operationsSummary: () => request<OperationsSummary>("/operations/sla/summary"),
  slaScanHistory: (limit = 10) => request<SlaScanHistory>(`/operations/sla/scans?limit=${limit}`),
  runSlaScan: () => request<SlaScanResult>("/operations/sla/scan", { method: "POST" }),
  retrySlaScan: (runKey: string, reason: string) =>
    request<SlaScanRetryResult>(`/operations/sla/scans/${encodeURIComponent(runKey)}/retry`, { method: "POST", body: JSON.stringify({ reason }) }),
  releaseSlaScanLease: (executionId: string, reason: string) =>
    request<{ execution_id: string; status: "force_released" | "terminal_lease_released"; finished_at: string; released_by: string; reason: string }>("/operations/sla/lease/release", { method: "POST", body: JSON.stringify({ expected_execution_id: executionId, reason }) }),
  documentCorrectionWorkbench: (activeOnly = true) =>
    request<DocumentCorrectionTask[]>(`/operations/document-corrections?active_only=${activeOnly}`),
  actOnDocumentCorrection: (id: string, payload: { expected_row_version: number; action: "remind" | "reassign" | "extend"; reason: string; assigned_role?: DocumentCorrection["assigned_role"]; extension_hours?: number }) =>
    request<DocumentCorrectionTask>(`/operations/document-corrections/${id}/actions`, { method: "POST", body: JSON.stringify(payload) }),
};
