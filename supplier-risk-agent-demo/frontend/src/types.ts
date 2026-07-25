export type Principal = {
  subject: string;
  name: string;
  roles: string[];
  permissions: string[];
  counterparty_id: string | null;
};

export type Counterparty = {
  id: string;
  name: string;
  credit_code: string;
  counterparty_type: "supplier" | "customer";
  industry: string;
  cooperation_status: string;
  is_key_counterparty: boolean;
  requested_limit: number;
  current_limit: number;
  current_payment_term_days: number;
  current_rating: string;
  current_segment: string;
  external: Record<string, string | number | boolean>;
  internal: Record<string, string | number | boolean>;
  financial: Record<string, string | number | boolean>;
  data_quality?: { raw_profile_id?: string; recommended_model?: string; internal_transaction_complete?: boolean; missing_critical_fields?: string[] };
};

export type RawEnterpriseProfile = {
  profile_id: string;
  counterparty_id: string;
  as_of_date: string;
  recommended_model: string;
  entity: {
    name_cn: string;
    name_en: string;
    unified_social_credit_code: string;
    registration_status: string;
    established_date: string;
    legal_representative: string;
    enterprise_type: string;
    registered_capital_cny: number;
    paid_in_capital_cny: number;
    employee_count: number;
    enterprise_scale: string;
    address: string;
    industry: { name: string; class_code: string };
  };
  ownership: { ultimate_parent: { name: string; country: string }; shareholders: Array<{ name: string; ownership_pct: number }> };
  operations: { business_summary: string; annual_capacity_units: number; domestic_sales_pct: number; patent_count: number; qualification_count: number; named_customers: string[] };
  financial_statements: {
    unit: string;
    periods: Array<{ year: number; total_assets: number; total_liabilities: number; total_equity: number; revenue: number; total_profit: number; net_profit: number; debt_to_assets_pct: number; net_profit_margin_pct: number; return_on_equity_pct: number; total_asset_turnover: number; sales_growth_pct: number | null; profit_growth_pct: number | null }>;
    derived_features: Record<string, string | number | Record<string, number>>;
  };
  external_risk: { report_rule_hits: Array<{ severity: string; rule: string; actual?: number; actual_pct?: number }> };
  external_benchmark: { provider: string; report_score: number; report_rating: string; suggested_credit_limit_cny: number; suggested_trade_term: string; usage: string };
  internal_transaction_data: { status: string; note: string };
  missing_critical_fields: string[];
  source_lineage: Array<{ source_id: string; file: string; pages: string; usage: string }>;
};

export type EnterpriseDataImport = {
  id: string;
  import_key: string;
  counterparty_id: string;
  source_type: "internal_erp" | "official_registry" | "audited_financial" | "external_risk" | "credit_report" | "management_submission";
  source_name: string;
  source_priority: number;
  schema_version: string;
  as_of_date: string;
  evidence_reference: string;
  payload_hash: string;
  status: "accepted" | "accepted_with_conflicts";
  field_count: number;
  conflict_count: number;
  stale_count: number;
  invalid_count: number;
  quality_score: number;
  quality: { evidence_coverage: number; missing_critical_fields: string[] };
  created_by: string;
  created_at: string | null;
  idempotent?: boolean;
};

export type EnterpriseDataField = {
  id: string;
  import_id: string;
  counterparty_id: string;
  field_path: string;
  value: unknown;
  value_hash: string;
  value_type: string;
  source_type: EnterpriseDataImport["source_type"];
  source_name: string;
  source_priority: number;
  evidence_reference: string;
  evidence_locator: string | null;
  observed_at: string;
  freshness_days: number;
  freshness_status: "current" | "stale";
  validation_status: "valid";
  conflict_status: "none" | "overrides_lower_priority" | "requires_review";
  created_at: string | null;
  is_effective: boolean;
  selection_method?: "automatic" | "approved_resolution";
  resolution_id?: string | null;
  unresolved_conflict?: boolean;
};

export type EnterpriseDataResolution = {
  id: string;
  counterparty_id: string;
  field_path: string;
  selected_field_id: string;
  selected_value: unknown;
  selected_value_hash: string;
  candidate_snapshot_hash: string;
  candidate_count: number;
  reason_category: "source_confirmation" | "document_verification" | "system_of_record" | "manual_investigation";
  rationale: string;
  status: "pending_review" | "approved" | "rejected" | "superseded";
  created_by: string;
  created_by_name: string;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
  idempotent?: boolean;
  is_current_snapshot?: boolean;
};

export type EnterpriseDataConflict = {
  counterparty_id: string;
  field_path: string;
  status: "unresolved" | "pending_review" | "resolved" | "reopened";
  candidate_snapshot_hash: string;
  automatic_field_id: string | null;
  effective_field_id: string | null;
  is_resolved: boolean;
  is_pending: boolean;
  resolution: EnterpriseDataResolution | null;
  candidates: EnterpriseDataField[];
};

export type EnterpriseDataProfile = {
  counterparty_id: string;
  profile: Record<string, unknown>;
  summary: {
    field_count: number;
    stale_count: number;
    conflict_count: number;
    invalid_count: number;
    evidence_coverage: number;
    quality_score: number;
    missing_critical_fields: string[];
    import_count: number;
    source_count: number;
    sections: Record<string, number>;
    total_conflict_count: number;
    resolved_conflict_count: number;
    pending_resolution_count: number;
    resolution_count: number;
  };
  effective_fields: EnterpriseDataField[];
  conflict_paths: string[];
  all_conflict_paths: string[];
  resolved_conflict_paths: string[];
  pending_resolution_paths: string[];
  stale_fields: EnterpriseDataField[];
  recent_imports: EnterpriseDataImport[];
};

export type EnterpriseFieldLineage = {
  counterparty_id: string;
  field_path: string;
  effective_field_id: string | null;
  automatic_field_id: string | null;
  candidate_snapshot_hash: string;
  resolution: EnterpriseDataResolution | null;
  resolution_status: "resolved" | "pending_review" | "unresolved";
  candidates: EnterpriseDataField[];
};

export type RatingReadiness = {
  mapping_version: string;
  template_key: string;
  model_version: string;
  source_mode: "governed" | "legacy_static";
  as_of_date: string | null;
  gate_status: "pass" | "review" | "blocked" | "legacy";
  ready_for_scoring: boolean;
  auto_approval_ready: boolean;
  mapped_count: number;
  total_mapping_count: number;
  coverage_rate: number;
  required_missing: string[];
  stale_required: string[];
  conflict_paths: string[];
  transaction_complete: boolean;
  quality_score: number | null;
  warnings: string[];
  data_snapshot_hash: string;
  mapping_snapshot_hash: string | null;
  mappings: Array<{
    target_path: string;
    label: string;
    value: unknown;
    source_paths: string[];
    source_field_ids: string[];
    source_names: string[];
    formula: string;
    required: boolean;
    status: "mapped" | "stale" | "conflict" | "missing";
  }>;
};

export type WorkflowProgress = {
  序号: number;
  审批环节: string;
  负责角色: string;
  状态: "已完成" | "处理中" | "待处理" | "已终止";
};

export type ApprovalCase = {
  case_id: string;
  counterparty_id: string;
  counterparty_name: string;
  current_stage: string;
  status: string;
  completed_stages: string[];
  data: Record<string, Record<string, unknown>>;
  timeline: Array<Record<string, string>>;
  row_version: number;
  stage_started_at: string | null;
  stage_due_at: string | null;
  sla_status: "正常" | "即将超时" | "已超时" | "已停止" | "未设置";
  remaining_seconds: number | null;
  created_at: string | null;
  updated_at: string | null;
  progress?: WorkflowProgress[];
};

export type ApprovalAction = "return_for_supplement" | "reject" | "withdraw" | "comment";

export type CreditReportPreview = {
  counterparty: { id: string; name: string; credit_code: string; counterparty_type: string; industry: string; cooperation_status: string };
  case: { case_id: string; status: string; counterparty_id: string; counterparty_name: string; created_at: string | null; completed_at: string | null };
  model: { template_key: string; model_name: string; model_version: string; rating_run_id: string; model_snapshot_id: string; input_hash: string; result_hash: string };
  rating: { total_score: number; raw_rating: string; rating: string; risk_segment: string; access_strategy: string; suggested_limit: number; suggested_payment_term_days: number; monitoring_frequency: string; review_required: boolean; data_completeness: number | null };
  proposal: { suggested_limit: number; suggested_payment_term_days: number; access_strategy: string; monitoring_frequency: string };
  decision: { decision: string; access_strategy: string; approved_limit: number; approved_payment_term_days: number; monitoring_frequency: string; facility_validity_days: number };
  decision_variance: DecisionVarianceSnapshot;
  document_count: number;
  timeline_count: number;
  source_count: number;
  data_limitations: string[];
};

export type DecisionVarianceSnapshot = {
  direction: "aligned" | "stricter" | "relaxed" | "mixed" | "rejected";
  materiality: "none" | "minor" | "material";
  changed_fields: string[];
  requires_reason: boolean;
  requires_compensating_controls: boolean;
  recommendation: { decision: string; access_strategy: string; suggested_limit: number; suggested_payment_term_days: number; monitoring_frequency: string };
  final_decision: { decision: string; access_strategy: string; approved_limit: number; approved_payment_term_days: number; monitoring_frequency: string };
  deltas: { limit_amount: number; limit_ratio: number; payment_term_days: number; strategy_steps: number; monitoring_steps: number; decision_steps: number };
  reason_category: string | null;
  reason_detail: string | null;
  compensating_controls: string[];
};

export type DecisionVariance = DecisionVarianceSnapshot & {
  id: string;
  case_id: string;
  counterparty_id: string;
  counterparty_name: string;
  rating_run_id: string | null;
  model_snapshot_id: string | null;
  decided_by: string;
  decided_at: string | null;
};

export type DecisionGovernanceSummary = {
  total: number;
  aligned_count: number;
  adjusted_count: number;
  material_count: number;
  relaxation_count: number;
  average_limit_reduction_rate: number;
  direction_distribution: Record<DecisionVariance["direction"], number>;
  recent: DecisionVariance[];
};

export type CreditReport = {
  id: string;
  report_no: string;
  case_id: string;
  counterparty_id: string;
  report_version: number;
  report_type: "credit_decision";
  status: "sealed";
  snapshot_hash: string;
  pdf_sha256: string;
  size_bytes: number;
  created_by: string;
  created_at: string | null;
  preview: CreditReportPreview;
  idempotent?: boolean;
};

export type CreditReportIntegrity = {
  report_id: string;
  report_no: string;
  status: "verified" | "failed";
  valid: boolean;
  snapshot: { valid: boolean; expected_sha256: string; actual_sha256: string };
  pdf: { valid: boolean; object_exists: boolean; expected_sha256: string; actual_sha256: string | null };
};

export type DocumentRecord = {
  id: string;
  counterparty_id: string;
  case_id: string | null;
  document_type: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by: string;
  status: string;
  checklist: DocumentCheckResult[];
  review_status: "pending_review" | "verified" | "needs_supplement" | "rejected";
  review_comment: string | null;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  row_version: number;
  created_at: string;
};

export type DocumentCheckResult = {
  key: string;
  label: string;
  status: "pass" | "fail" | "not_applicable";
  note: string;
};

export type DocumentPrecheck = {
  document_id: string;
  document_type: string;
  overall_status: "pass" | "warning" | "manual_review" | "block";
  summary: string;
  checks: Array<{
    key: string;
    label: string;
    status: "pass" | "warning" | "manual_review" | "block";
    detail: string;
    signals: string[];
  }>;
  recommendations: string[];
  ocr: {
    status: "not_needed" | "success" | "no_text" | "unavailable" | "error";
    provider: string | null;
    pages_processed: number;
    average_confidence: number;
    warning: string | null;
  };
  extracted_fields: Array<{
    key: string;
    label: string;
    value: string;
    source: "ocr" | "text_layer";
    confidence: number;
    matches_expected: boolean | null;
  }>;
  generated_from_sha256: string;
  disclaimer: string;
};

export type DocumentCorrection = {
  id: string;
  counterparty_id: string;
  case_id: string | null;
  document_type: string;
  original_document_id: string;
  current_document_id: string;
  version_document_ids: string[];
  status: "open" | "resubmitted" | "closed" | "rejected";
  reason: string;
  failed_check_keys: string[];
  attempt_count: number;
  requested_by: string;
  requested_by_name: string;
  requested_at: string | null;
  resolved_by: string | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type DocumentChecklistItem = {
  key: string;
  document_type: string;
  description: string;
  required: boolean;
  models: string[];
  status: "missing" | DocumentRecord["review_status"];
  document: DocumentRecord | null;
};

export type DocumentChecklist = {
  template_key: string;
  items: DocumentChecklistItem[];
  review_checks: Array<{ key: string; label: string }>;
  summary: {
    total_count: number;
    required_count: number;
    uploaded_count: number;
    verified_count: number;
    pending_count: number;
    missing_required_count: number;
    exception_count: number;
  };
};

export type RatingResult = {
  total_score: number;
  rating: string;
  risk_level?: string;
  suggested_limit: number;
  suggested_payment_term_days: number;
  decision?: string;
  result_hash?: string;
  rating_run_id?: string;
  scorecard_type?: string;
  data_completeness?: number;
  business_risk_band?: number;
  financial_risk_band?: number;
  submodel_scores?: Record<string, number>;
  enterprise_risk_screening?: EnterpriseRiskScreening;
  risk_screening_policy?: RiskScreeningPolicyResult;
};

export type PortfolioRatingResult = {
  counterparty_id: string;
  counterparty_name: string;
  counterparty_type: "supplier" | "customer";
  rating_run_id: string;
  total_score: number;
  rating: string;
  raw_rating: string;
  risk_segment: string;
  access_strategy: string;
  suggested_limit: number;
  suggested_payment_term_days: number;
  monitoring_frequency: string;
  review_required: boolean;
  strong_rule_hit_count: number;
  risk_policy_hits: string[];
  risk_policy_changed: boolean;
  risk_screening_score: number;
  risk_screening_completeness: number;
};

export type PortfolioRatingSummary = {
  candidate_count: number;
  success_count: number;
  skipped_count: number;
  review_required_count: number;
  denied_count: number;
  policy_affected_count: number;
  strong_rule_affected_count: number;
  total_suggested_limit: number;
  average_score: number;
  average_risk_screening_score: number;
  average_risk_screening_completeness: number;
  rating_distribution: Record<string, number>;
  access_distribution: Record<string, number>;
  risk_segment_distribution: Record<string, number>;
  watchlist: PortfolioRatingResult[];
};

export type PortfolioRatingBatch = {
  id: string;
  batch_key: string;
  request_hash: string;
  template_key: string;
  model_version: string;
  model_snapshot_id: string | null;
  scope_type: "all" | "supplier" | "customer";
  status: "completed" | "completed_with_exceptions";
  candidate_count: number;
  success_count: number;
  skipped_count: number;
  summary: PortfolioRatingSummary;
  results: PortfolioRatingResult[];
  skipped: Array<{ counterparty_id: string; counterparty_name: string; reason: string }>;
  result_hash: string;
  created_by: string;
  created_by_name: string;
  created_at: string;
  idempotent?: boolean;
};

export type ModelSummary = { key: string; name: string; version: string };

export type EditableIndicator = { path: string; label: string; unit: string; value_scale?: "whole" | "fraction"; step: number; min: number; max: number; source?: "enterprise_risk_pool" };

export type EnterpriseRiskIndicator = {
  id: string;
  name: string;
  category: string;
  category_key: string;
  subcategories: string[];
  description: string;
  risk_level: "提示风险" | "关注风险" | "警示风险" | string;
  use_cases: string[];
  data_source: string;
  data_type: "boolean" | "count" | "amount" | "years";
  field_path: string;
  max_score: number;
  default_weight: number;
  model_weight?: number;
  enabled?: boolean;
  scoring: {
    type: string;
    direction: string;
    formula: string;
    bands: Array<{ operator: string; value?: number | boolean; score: number; label: string }>;
    missing_score: number;
    input_fields?: string[];
  };
  statistics_period: string;
  data_scope: string;
  filter_condition: string;
  enabled_by_reference: boolean;
  source_references: Array<{ workbook: string; sheet: string; row: number }>;
};

export type IndicatorPoolResponse = {
  version: string;
  name: string;
  description: string;
  score_scale: { min: number; max: number; higher_is_better: boolean; missing_score: number };
  summary: { indicator_count: number; category_count: number; use_cases: string[]; category_counts: Record<string, number> };
  result_count: number;
  indicators: EnterpriseRiskIndicator[];
};

export type EnterpriseRiskScreening = {
  pool_version: string;
  selected_count: number;
  available_count: number;
  missing_count: number;
  completeness: number;
  weighted_score: number;
  normalized_score: number;
  formula: string;
  details: Array<{ indicator_id: string; name: string; category: string; risk_level: string; field_path: string; actual_value: unknown; actual_display: string; score: number; max_score: number; model_weight: number; formula: string; data_status: string; data_source: string; observation_id?: string | null; evidence_reference?: string | null; observed_at?: string | null; reviewed_by_name?: string | null }>;
};

export type RiskScreeningPolicyAction = {
  rating_notch_down: number;
  limit_cap_ratio: number;
  term_cap_days: number;
  access_strategy: "正常准入" | "优先准入" | "审慎准入" | "人工复核" | "限制准入" | "禁入";
  monitoring_frequency: "年度" | "半年度" | "季度" | "月度" | "周度" | "实时监控";
};

export type RiskScreeningPolicyRule = {
  id: string;
  name: string;
  enabled: boolean;
  metric: "normalized_score" | "completeness" | "critical_indicator_count" | "missing_count";
  operator: "<" | "<=" | ">" | ">=" | "==";
  value: number;
  action: RiskScreeningPolicyAction;
};

export type RiskScreeningPolicy = { enabled: boolean; aggregation: "most_restrictive"; rules: RiskScreeningPolicyRule[] };
export type RiskScreeningStrategySnapshot = { rating: string; risk_segment: string; access_strategy: string; suggested_limit: number; suggested_payment_term_days: number; monitoring_frequency: string; review_required: boolean };
export type RiskScreeningPolicyResult = {
  enabled: boolean;
  aggregation: string;
  metrics: Record<"normalized_score" | "completeness" | "critical_indicator_count" | "missing_count", number>;
  hits: Array<RiskScreeningPolicyRule & { actual: number; expression: string }>;
  before: RiskScreeningStrategySnapshot;
  after: RiskScreeningStrategySnapshot;
  changed: boolean;
  formula: string;
};

export type EnterpriseIndicatorObservation = {
  id: string;
  counterparty_id: string;
  indicator_id: string;
  indicator_name: string;
  values: Record<string, number | boolean>;
  values_hash: string;
  evidence_document_id?: string | null;
  evidence_reference: string;
  observed_at: string;
  status: "pending_review" | "verified" | "rejected" | "superseded";
  created_by: string;
  created_by_name: string;
  reviewed_by?: string | null;
  reviewed_by_name?: string | null;
  reviewed_at?: string | null;
  review_comment?: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
};

export type StrongRule = {
  id: string;
  name: string;
  enabled: boolean;
  condition_relation: "all" | "any";
  conditions: Array<{ field: string; operator: string; value?: unknown; value_ref?: string; label: string }>;
  action: Record<string, string | number | boolean>;
};

export type ModelDetail = ModelSummary & {
  status: string;
  industry_template: string;
  weights: Record<string, number>;
  thresholds: Record<string, number>;
  strong_rules: StrongRule[];
  strategy_mapping: Array<Record<string, string | number>>;
  editable_indicators: EditableIndicator[];
  indicator_selection: Array<EnterpriseRiskIndicator & { model_weight: number; enabled: boolean }>;
  risk_screening_policy: RiskScreeningPolicy;
  change_reason: string;
};

export type RatingTrace = {
  ok: boolean;
  result: RatingResult & {
    access_strategy: string;
    risk_segment: string;
    strong_rule_hits: unknown[];
    review_required: boolean;
  };
  dimension_contributions: Array<{ 维度: string; 维度得分: number; 权重: string; 加权贡献: number; 计算公式: string }>;
  indicator_deductions: Array<{ 维度: string; 指标组?: string; 指标: string; 原始值?: string; 标准分?: number; 有效权重?: string; 扣分: number; 证据: string; 运算: string; 数据状态?: string }>;
  matrix_inputs?: Array<{ 子模型: string; 得分: number; 档位: number | string }>;
  data_quality?: Record<string, string>;
  limit_calculation?: { 公式: string; 候选上限: Record<string, number>; 约束项: string; 规则调整前额度: number; 规则调整后额度: number };
  formula: string;
  enterprise_risk_screening: EnterpriseRiskScreening;
};

export type ModelImpact = {
  ok: boolean;
  field_path: string;
  old_value: number | null;
  new_value: number;
  before: RatingTrace["result"];
  after: RatingTrace["result"];
  before_enterprise_risk_screening: EnterpriseRiskScreening;
  after_enterprise_risk_screening: EnterpriseRiskScreening;
  impact: {
    总分变化: number;
    评级变化: string;
    策略变化: string;
    额度变化: number;
    账期变化: number;
    强规则变化: string;
    企业风险筛查分变化: number;
    企业风险完整度变化: number;
    企业风险贷策命中变化: string;
  };
};

export type ModelValidationReport = {
  snapshot_id: string;
  generated_at: string;
  template_key: string;
  model_name: string;
  model_version: string;
  release_gate: {
    passed: boolean;
    status: "pass" | "blocked";
    summary: string;
    gates: Array<{ key: string; label: string; passed: boolean; actual: number; threshold: string }>;
  };
  sample_profile: {
    portfolio_count: number;
    total_count: number;
    out_of_scope_count: number;
    eligible_count: number;
    excluded_count: number;
    calculation_error_count: number;
    labeled_count: number;
    coverage_rate: number;
    labeled_rate: number;
  };
  metrics: Array<{ key: string; label: string; value: number | null; unit: "percent" | "grade"; status: "pass" | "warn" | "fail" | "not_testable"; description: string }>;
  score_distribution: { mean: number; std: number; min: number | null; max: number | null; rating_counts: Record<string, number> };
  monitoring: {
    dataset: { dataset_id: string; name: string; evidence_level: string; label_definition: string; source: string; baseline_period: string; current_period: string } | null;
    population_stability: { status: "not_testable" | "pass" | "warn" | "fail"; value: number | null; reason: string; baseline_distribution?: Record<string, number>; current_distribution?: Record<string, number> };
    backtesting: { status: "ready" | "blocked"; sample_count: number; event_count: number; non_event_count: number; actual_event_rate?: number; expected_event_rate?: number; calibration_gap?: number };
    performance_metrics: Array<{ key: string; label: string; value: number | null; status: "pass" | "warn" | "fail" | "not_testable"; description: string }>;
    recommended_frequency: string;
  };
  findings: string[];
  excluded_samples: Array<{ counterparty_id: string; reason: string }>;
  calculation_errors: Array<{ counterparty_id: string; reason: string }>;
};

export type ModelChangeRecord = {
  id: string;
  template_key: string;
  base_version: string;
  candidate_version: string;
  status: "draft" | "pending_review" | "published" | "rejected";
  config: {
    weights: Record<string, number>;
    thresholds: Record<string, number>;
    strong_rules: StrongRule[];
    strategy_mapping: Array<Record<string, string | number>>;
    indicator_selection?: Array<{ indicator_id: string; weight: number; enabled: boolean }>;
    risk_screening_policy?: RiskScreeningPolicy;
    [key: string]: unknown;
  };
  validation: { valid: boolean; errors: string[]; warnings: string[]; config_hash: string; model_risk?: ModelValidationReport | null };
  impact: {
    sample_count: number;
    skipped_count: number;
    impacted_count: number;
    rating_changes: number;
    strategy_changes: number;
    max_abs_score_delta: number;
    indicator_selection_changed: boolean;
    risk_screening_policy_changed: boolean;
    risk_screening_impacted_count: number;
    max_abs_risk_screening_delta: number;
    average_limit_delta: number;
    details: Array<Record<string, string | number>>;
  };
  change_reason: string;
  created_by: string;
  created_by_name: string;
  reviewed_by_name: string | null;
  review_comment: string | null;
  row_version: number;
  created_at: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  published_at: string | null;
};

export type ModelReleaseRecord = {
  id: string;
  template_key: string;
  model_version: string;
  config_hash: string;
  source_change_id: string | null;
  is_active: boolean;
  published_by: string;
  published_at: string | null;
};

export type ModelOutcome = {
  id: string;
  external_observation_id: string;
  source: string;
  template_key: string;
  model_version: string;
  counterparty_id: string;
  population_period: string;
  predicted_score: number;
  predicted_pd: number;
  observed_event: boolean;
  prediction_at: string;
  observation_end: string;
  evidence_reference: string;
  verification_status: "pending_verification" | "verified" | "rejected";
  verified_by: string | null;
  verified_at: string | null;
  verification_note: string | null;
  row_version: number;
  created_by: string;
  created_at: string | null;
  idempotent?: boolean;
};

export type ModelOutcomeImport = {
  id: string;
  import_key: string;
  source: string;
  template_key: string;
  population_period: string;
  payload_hash: string;
  status: "processing" | "completed" | "completed_with_exceptions" | "failed";
  expected_count: number;
  received_count: number;
  count_variance: number;
  created_count: number;
  idempotent_count: number;
  rejected_count: number;
  results: Array<{ index: number; external_observation_id: string; status: "created" | "idempotent" | "rejected"; outcome_id: string | null; error: string | null }>;
  error_message: string | null;
  created_by: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  idempotent?: boolean;
};

export type MonitoringSummary = {
  template_key: string;
  effective_source: "observed_outcome" | "simulation_proxy" | "observed_outcome_pending" | "none";
  readiness: {
    observation_count: number;
    period_count: number;
    periods: string[];
    event_count: number;
    non_event_count: number;
    formal_backtest_ready: boolean;
    submitted_count: number;
    pending_verification_count: number;
    rejected_count: number;
    summary: string;
    minimums: { observations: number; periods: number; events: number; non_events: number };
  };
  monitoring: ModelValidationReport["monitoring"];
};

export type MonitoringIssue = {
  id: string;
  template_key: string;
  model_version: string;
  dataset_id: string;
  evidence_level: string;
  metric_key: string;
  metric_label: string;
  metric_value: number | null;
  metric_status: string;
  severity: "warning" | "critical";
  title: string;
  description: string;
  status: "open" | "in_remediation" | "pending_revalidation" | "closed";
  owner: string | null;
  remediation_plan: string | null;
  remediation_result: string | null;
  remediated_by: string | null;
  revalidation_conclusion: string | null;
  revalidated_by: string | null;
  linked_change_id: string | null;
  due_at: string | null;
  closed_at: string | null;
  row_version: number;
  created_by: string;
  created_at: string | null;
};

export type ModelMonitoringRun = {
  id: string;
  run_key: string;
  template_key: string;
  model_version: string;
  as_of_period: string;
  trigger_type: "manual" | "scheduled";
  status: "running" | "completed" | "failed";
  effective_source: string;
  evidence_level: string;
  dataset_id: string;
  readiness: MonitoringSummary["readiness"];
  monitoring: ModelValidationReport["monitoring"] | Record<string, never>;
  issue_ids: string[];
  error_message: string | null;
  actor: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  idempotent?: boolean;
};

export type ModelMonitoringSchedule = {
  id: string;
  template_key: string;
  cadence: "monthly" | "quarterly";
  timezone_name: "Asia/Shanghai" | "UTC";
  enabled: boolean;
  next_run_at: string;
  last_scheduled_for: string | null;
  last_run_at: string | null;
  last_run_id: string | null;
  last_status: "completed" | "failed" | null;
  last_error: string | null;
  row_version: number;
  created_by: string;
  updated_by: string;
  created_at: string | null;
  updated_at: string | null;
};

export type MonitoringSchedulerTick = {
  as_of: string;
  due_count: number;
  completed: number;
  failed: number;
  deferred: number;
  results: Array<{ schedule_id: string; run_id: string | null; status: "completed" | "failed" | "deferred"; error: string | null; next_run_at?: string; idempotent?: boolean }>;
};

export type ModelGovernanceNotification = {
  id: string;
  monitoring_run_id: string;
  monitoring_issue_id: string | null;
  template_key: string;
  recipient_role: string;
  severity: "warning" | "critical";
  title: string;
  message: string;
  status: "unread" | "read";
  created_at: string | null;
  read_at: string | null;
  read_by: string | null;
};

export type ApiErrorShape = { detail?: string };

export type NotificationRecord = {
  id: string;
  case_id: string;
  counterparty_id: string;
  recipient_role: string;
  category: string;
  level: "due_soon" | "overdue" | "escalated";
  severity: "info" | "warning" | "critical";
  title: string;
  message: string;
  status: "unread" | "read";
  created_at: string | null;
  read_at: string | null;
};

export type OperationsSummary = {
  generated_at: string;
  total_cases: number;
  active_cases: number;
  sla: { normal: number; due_soon: number; overdue: number; escalated: number };
  unread_notifications: { total: number; info: number; warning: number; critical: number };
  last_scan: { run_id: string; run_at: string | null; actor: string; active_cases_scanned: number; notifications_created: number } | null;
  stage_distribution: Array<{ stage: string; label: string; count: number }>;
};

export type SlaScanResult = {
  run_id: string;
  run_at: string;
  active_cases_scanned: number;
  due_soon_cases: number;
  overdue_cases: number;
  escalated_cases: number;
  notifications_created: number;
};

export type CreditFacility = {
  id: string;
  case_id: string;
  counterparty_id: string;
  counterparty_name: string;
  approved_limit: number;
  used_limit: number;
  available_limit: number;
  utilization_rate: number;
  payment_term_days: number;
  rating: string;
  access_strategy: string;
  monitoring_frequency: string;
  status: "active" | "expired" | "frozen" | "closed";
  effective_at: string | null;
  expires_at: string | null;
  last_review_at: string | null;
  next_review_at: string | null;
  row_version: number;
};

export type CreditUsageTransaction = {
  id: string;
  facility_id: string;
  transaction_ref: string;
  transaction_type: "drawdown" | "repayment";
  amount: number;
  balance_after: number;
  occurred_at: string;
  actor: string;
  reason: string;
};

export type CreditFacilityDetail = CreditFacility & { transactions: CreditUsageTransaction[] };

export type FacilityAlert = {
  id: string;
  facility_id: string;
  counterparty_id: string;
  counterparty_name: string;
  alert_type: string;
  severity: "warning" | "critical";
  title: string;
  message: string;
  status: "open" | "acknowledged" | "resolved";
  created_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  disposition_action: string | null;
  disposition_note: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  row_version: number;
};

export type RiskEvent = {
  id: string;
  facility_id: string;
  counterparty_id: string;
  counterparty_name: string;
  external_event_id: string;
  event_type: string;
  source: string;
  severity: "warning" | "critical";
  occurred_at: string;
  title: string;
  description: string;
  payload: Record<string, unknown>;
  linked_alert_id: string | null;
  status: "active" | "resolved";
  resolved_at: string | null;
  created_by: string;
  created_at: string | null;
};

export type FacilitySummary = {
  total_facilities: number;
  active_facilities: number;
  approved_limit: number;
  used_limit: number;
  available_limit: number;
  high_utilization_facilities: number;
  unresolved_alerts: number;
  critical_alerts: number;
};
