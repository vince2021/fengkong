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
  状态: "已完成" | "处理中" | "待补件" | "待处理" | "已终止";
};

export type CreditAuthoritySlot = {
  key: string;
  role: "risk_manager" | "approver";
  label: string;
  status: "pending" | "approved" | "rejected";
  decision: "approve" | "reject" | null;
  comment: string | null;
  signed_by: string | null;
  signed_by_name: string | null;
  signed_at: string | null;
};

export type CreditAuthority = {
  version: string;
  tier: "standard" | "enhanced" | "committee";
  tier_label: string;
  reason: string;
  policy: { id: string | null; version: string; config_hash: string; source: "builtin" | "published" };
  basis: { suggested_limit: number; rating: string; access_strategy: string; renewal_risk_conclusion?: RenewalRiskReview["conclusion"] | null };
  slots: CreditAuthoritySlot[];
  status: "pending" | "approved" | "rejected";
};

export type AuthorityPolicySlot = {
  key: string;
  role: "risk_manager" | "approver";
  label: string;
};

export type AuthorityPolicyTier = {
  label: string;
  reason: string;
  slots: AuthorityPolicySlot[];
};

export type AuthorityPolicyConfig = {
  standard_limit: number;
  enhanced_limit: number;
  low_risk_ratings: string[];
  high_risk_ratings: string[];
  restricted_strategies: string[];
  prohibited_strategies: string[];
  tiers: Record<"standard" | "enhanced" | "committee", AuthorityPolicyTier>;
};

export type AuthorityPolicySnapshot = {
  id: string | null;
  policy_version: string;
  config_hash: string;
  config: AuthorityPolicyConfig;
  source: "builtin" | "published";
};

export type AuthorityPolicyConfigDiff = {
  version: string;
  overall_direction: "tightened" | "relaxed" | "mixed" | "neutral" | "unchanged";
  summary: {
    changed_field_count: number;
    tightened_count: number;
    relaxed_count: number;
    mixed_count: number;
    neutral_count: number;
  };
  changes: Array<{
    key: string;
    label: string;
    category: "limit_threshold" | "risk_set" | "signoff_slots" | "tier_metadata";
    before: unknown;
    after: unknown;
    direction: "tightened" | "relaxed" | "mixed" | "neutral";
    rationale: string;
    added?: string[];
    removed?: string[];
  }>;
  method_note: string;
};

export type AuthorityPolicyImpact = {
  version: string;
  generated_at: string;
  base_policy_version: string;
  base_config_hash: string;
  candidate_policy_version: string;
  candidate_config_hash: string;
  config_diff?: AuthorityPolicyConfigDiff;
  input_snapshot_hash: string;
  release_gate: {
    passed: boolean;
    status: "pass" | "blocked";
    summary: string;
    gates: Array<{ key: string; label: string; passed: boolean; actual: number; threshold: string }>;
  };
  sample_profile: {
    portfolio_count: number;
    eligible_count: number;
    skipped_count: number;
    calculation_error_count: number;
    coverage_rate: number;
  };
  summary: {
    changed_count: number;
    escalated_count: number;
    deescalated_count: number;
    slot_changed_count: number;
    additional_signoffs: number;
    removed_signoffs: number;
    escalated_limit: number;
    deescalated_limit: number;
  };
  before_distribution: Record<"standard" | "enhanced" | "committee", number>;
  after_distribution: Record<"standard" | "enhanced" | "committee", number>;
  migration_matrix: Record<"standard" | "enhanced" | "committee", Record<"standard" | "enhanced" | "committee", number>>;
  details: Array<{
    counterparty_id: string;
    counterparty_name: string;
    counterparty_type: "supplier" | "customer";
    template_key: string;
    model_version: string;
    model_config_hash: string;
    rating: string;
    access_strategy: string;
    suggested_limit: number;
    before_tier: "standard" | "enhanced" | "committee";
    before_tier_label: string;
    after_tier: "standard" | "enhanced" | "committee";
    after_tier_label: string;
    direction: "escalated" | "deescalated" | "unchanged";
    before_signoff_count: number;
    after_signoff_count: number;
    signoff_delta: number;
    drivers: string[];
  }>;
  skipped_samples: Array<{ counterparty_id: string; counterparty_name: string; template_key: string; reason: string }>;
  calculation_errors: Array<{ counterparty_id: string; counterparty_name: string; template_key: string; reason: string }>;
};

export type AuthorityPolicyScenarioComparison = {
  version: string;
  generated_at: string;
  base_policy_version: string;
  base_config_hash: string;
  input_snapshot_hash: string;
  sample_profile: AuthorityPolicyImpact["sample_profile"];
  lowest_workload_key: string | null;
  highest_control_key: string | null;
  lowest_workload_keys: string[];
  highest_control_keys: string[];
  scenarios: Array<{
    key: string;
    name: string;
    description: string;
    config: AuthorityPolicyConfig;
    config_hash: string;
    impact: AuthorityPolicyImpact;
    metrics: {
      total_signoffs: number;
      average_signoffs: number;
      standard_count: number;
      enhanced_count: number;
      committee_count: number;
      enhanced_review_count: number;
      control_intensity_index: number;
    };
  }>;
};

export type AuthorityPolicyRecord = {
  id: string;
  policy_version: string;
  base_policy_version: string;
  status: "draft" | "pending_review" | "scheduled" | "published" | "rejected" | "cancelled";
  config: AuthorityPolicyConfig;
  config_hash: string;
  impact: AuthorityPolicyImpact | null;
  impact_hash: string | null;
  impact_evaluated_at: string | null;
  restore_source_policy_id: string | null;
  restore_source_policy_version: string | null;
  change_reason: string;
  created_by: string;
  created_by_name: string;
  submitted_at: string | null;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  effective_at: string | null;
  activated_at: string | null;
  published_at: string | null;
  superseded_at: string | null;
  schedule_cancelled_at: string | null;
  schedule_cancelled_by: string | null;
  schedule_cancelled_by_name: string | null;
  schedule_cancel_reason: string | null;
  is_active: boolean;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type AuthorityPolicyActivationRun = {
  id: string;
  run_key: string;
  trigger_type: "manual" | "scheduler";
  status: "no_due" | "activated" | "blocked";
  scheduled_policy_id: string | null;
  scheduled_policy_version: string | null;
  scheduled_effective_at: string | null;
  active_policy_before: string;
  active_policy_after: string;
  error_message: string | null;
  incident_status: "not_applicable" | "open" | "acknowledged" | "resolved";
  acknowledged_by: string | null;
  acknowledged_by_name: string | null;
  acknowledged_at: string | null;
  acknowledgement_note: string | null;
  resolved_by: string | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
  resolution_type: "activated" | "retry_activated" | "schedule_cancelled" | null;
  resolution_note: string | null;
  retry_of_run_id: string | null;
  resolved_by_run_id: string | null;
  actor_subject: string;
  actor_name: string;
  started_at: string;
  completed_at: string | null;
  row_version: number;
  created_at: string | null;
};

export type AuthorityPolicyActivationStatus = {
  scheduled_policy: AuthorityPolicyRecord | null;
  scheduler_health: {
    state: "idle" | "healthy" | "attention" | "overdue" | "blocked";
    message: string;
    scan_interval_minutes: number;
    checked_at: string;
    last_scheduler_run: AuthorityPolicyActivationRun | null;
    next_expected_scan_at: string | null;
    overdue_seconds: number;
  };
  unresolved_incident_count: number;
  unresolved_incidents: AuthorityPolicyActivationRun[];
  recent_runs: AuthorityPolicyActivationRun[];
};

export type AuthorityPolicyActivationScan = {
  run: AuthorityPolicyActivationRun;
  run_at: string;
  due_count: number;
  activated_count: number;
  activated_policy: AuthorityPolicyRecord | null;
  idempotent: boolean;
};

export type AuthorityPolicyEvidence = {
  schema_version: "authority-policy-evidence-v1";
  generated_at: string;
  package_hash: string;
  package_hash_algorithm: "SHA-256";
  policy: AuthorityPolicyRecord;
  activation_runs: AuthorityPolicyActivationRun[];
  notifications_by_run: Record<string, Array<{
    id: string;
    recipient_role: string;
    status: "unread" | "read" | "resolved";
    severity: "info" | "warning" | "critical";
    dedup_key: string;
    created_at: string | null;
    read_at: string | null;
  }>>;
  audit: {
    policy_lifecycle: AuthorityPolicyEvidenceAuditChain;
    activation_runs: Record<string, AuthorityPolicyEvidenceAuditChain>;
  };
  integrity: {
    passed: boolean;
    unresolved_incident_count: number;
    checks: Array<{
      key: string;
      label: string;
      passed: boolean;
      applicable: boolean;
      detail: string;
    }>;
  };
};

export type AuthorityPolicyEvidenceAnchor = {
  id: string;
  policy_id: string;
  policy_version: string;
  schema_version: string;
  package_hash: string;
  anchor_hash: string;
  anchor_hash_valid: boolean;
  package_unchanged: boolean;
  audit_valid: boolean;
  registry_valid: boolean;
  status: "active" | "revoked";
  trust_eligible: boolean;
  integrity_passed: boolean;
  issued_by: string;
  issued_by_name: string;
  issued_at: string;
  revoked_by: string | null;
  revoked_by_name: string | null;
  revoked_at: string | null;
  revocation_reason: string | null;
  supersedes_anchor_id: string | null;
  replacement_reason: string | null;
  replacement_anchor_id: string | null;
  superseded_anchor: {
    id: string;
    anchor_hash: string;
    issued_by: string;
    revoked_by: string;
    revoked_at: string;
  } | null;
  row_version: number;
  created_at: string | null;
  idempotent?: boolean;
  package?: AuthorityPolicyEvidence;
  audit?: AuthorityPolicyEvidenceAuditChain;
  package_verification?: {
    verified: boolean;
    trust_level: "self_sealed" | "externally_anchored" | "invalid";
    computed_package_hash: string;
    expected_package_hash: string | null;
    checks: Array<{
      key: string;
      label: string;
      passed: boolean;
      applicable: boolean;
      detail: string;
    }>;
    note: string;
  };
};

export type AuthorityPolicyEvidenceAnchorReceipt = {
  schema_version: "authority-policy-anchor-receipt-v1";
  verified_at: string;
  trust_scope: "status_at_verified_at";
  anchor: Omit<
    AuthorityPolicyEvidenceAnchor,
    "created_at" | "idempotent" | "package" | "audit" | "package_verification"
  >;
  audit_checkpoint: {
    event_count: number;
    terminal_hash: string;
  };
  receipt_hash_algorithm: "SHA-256";
  receipt_hash: string;
};

export type AuthorityPolicyEvidenceAuditChain = {
  aggregate_type: string;
  aggregate_id: string;
  valid: boolean;
  event_count: number;
  terminal_hash: string;
  events: Array<{
    id: string;
    event_type: string;
    actor: string;
    payload: Record<string, unknown>;
    previous_hash: string;
    event_hash: string;
    expected_hash: string;
    hash_valid: boolean;
    created_at: string | null;
  }>;
};

export type AuthorityPolicyEvidenceComparison = {
  schema_version: "authority-policy-evidence-comparison-v1";
  generated_at: string;
  comparison_hash: string;
  comparison_hash_algorithm: "SHA-256";
  base: AuthorityPolicyEvidenceComparisonSummary;
  candidate: AuthorityPolicyEvidenceComparisonSummary;
  config_diff: AuthorityPolicyConfigDiff;
  evidence_delta: {
    lifecycle_event_count: number;
    activation_run_count: number;
    unresolved_incident_count: number;
    newly_failed_checks: string[];
    resolved_checks: string[];
  };
};

export type AuthorityPolicyEvidenceComparisonSummary = {
  policy_id: string;
  policy_version: string;
  status: string;
  config_hash: string;
  package_hash: string;
  integrity_passed: boolean;
  lifecycle_event_count: number;
  activation_run_count: number;
  unresolved_incident_count: number;
};

export type ApprovalCase = {
  case_id: string;
  counterparty_id: string;
  counterparty_name: string;
  application_type: "new_credit" | "renewal";
  source_facility_id: string | null;
  current_stage: string;
  status: string;
  completed_stages: string[];
  data: Record<string, Record<string, unknown>>;
  timeline: Array<Record<string, string>>;
  row_version: number;
  stage_started_at: string | null;
  stage_due_at: string | null;
  assigned_to: string | null;
  assigned_to_name: string | null;
  assigned_at: string | null;
  assignment_expires_at: string | null;
  sla_status: "正常" | "即将超时" | "已超时" | "已暂停" | "已停止" | "未设置";
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
  renewal_risk: { application_type?: "new_credit" | "renewal"; review?: RenewalRiskReview | null; disposition?: { review_conclusion: RenewalRiskReview["conclusion"]; risk_review_hash: string; alignment: string; adopted_controls: string[]; override_reason: string | null } | null };
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
  source_document_id: string | null;
  carried_over_by: string | null;
  carried_over_at: string | null;
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
  assigned_role: "client" | "relationship_manager" | "risk_manager" | "approver";
  assigned_to: string | null;
  assigned_to_name: string | null;
  assigned_at: string | null;
  assignment_expires_at: string | null;
  sla_started_at: string | null;
  sla_due_at: string | null;
  sla_status: "normal" | "due_soon" | "overdue" | "escalated" | "stopped";
  remaining_seconds: number;
  reminder_count: number;
  last_reminded_at: string | null;
  extension_count: number;
  total_extension_hours: number;
  resolved_by: string | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type DocumentCorrectionTask = DocumentCorrection & {
  counterparty_name: string;
  recent_actions: Array<{
    event_type: "correction_manually_reminded" | "correction_reassigned" | "correction_sla_extended";
    actor: string;
    reason: string;
    detail: string;
    created_at: string | null;
  }>;
};

export type DocumentVersionComparison = {
  correction_id: string;
  document_type: string;
  from_document: {
    id: string;
    original_name: string;
    sha256: string;
    size_bytes: number;
    created_at: string | null;
  };
  to_document: {
    id: string;
    original_name: string;
    sha256: string;
    size_bytes: number;
    created_at: string | null;
  };
  overall_trend: "improved" | "regressed" | "unchanged";
  readiness: "ready_for_manual_review" | "attention_required" | "blocked";
  summary: {
    resolved_count: number;
    remaining_count: number;
    new_issue_count: number;
    changed_field_count: number;
  };
  requested_check_keys: string[];
  check_changes: Array<{
    key: string;
    label: string;
    previous_status: DocumentPrecheck["overall_status"];
    current_status: DocumentPrecheck["overall_status"];
    trend: "improved" | "regressed" | "unchanged";
    previous_detail: string | null;
    current_detail: string | null;
  }>;
  field_changes: Array<{
    key: string;
    label: string;
    previous_value: string | null;
    current_value: string | null;
    previous_matches_expected: boolean | null;
    current_matches_expected: boolean | null;
    previous_confidence: number | null;
    current_confidence: number | null;
    change_type: "resolved" | "introduced" | "unresolved" | "changed" | "unchanged";
  }>;
  recommendation: string;
  disclaimer: string;
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
  type_equivalents: Record<string, string[]>;
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

export type RenewalDocumentCarryover = {
  case_id: string;
  source_case_id: string;
  counterparty_id?: string;
  template_key: string;
  items: Array<{
    key: string;
    document_type: string;
    description: string;
    required: boolean;
    models: string[];
    action: "reusable" | "carried" | "current" | "refresh_required" | "expired_source" | "missing_source";
    reason: string;
    age_days: number | null;
    max_age_days: number | null;
    source_document: DocumentRecord | null;
    current_document: DocumentRecord | null;
  }>;
  summary: {
    reusable_count: number;
    carried_count: number;
    current_count: number;
    refresh_required_count: number;
  };
  carried_documents?: DocumentRecord[];
  created_count?: number;
  idempotent?: boolean;
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

export type TaskAction = {
  page?: "documents" | "approvals" | "facilities";
  counterparty_id?: string;
  case_id?: string;
  correction_id?: string;
  facility_id?: string;
  condition_id?: string;
};

export type NotificationRecord = {
  id: string;
  case_id: string | null;
  counterparty_id: string | null;
  recipient_role: string;
  recipient_subject: string | null;
  category: string;
  level: "due_soon" | "overdue" | "escalated" | "reminder" | "assignment" | "extension" | "task_created" | "resubmitted" | "reopened" | "completed" | "resumed" | "supervisor_reminder" | "lease_due_soon" | "lease_expired" | "policy_blocked";
  severity: "info" | "warning" | "critical";
  title: string;
  message: string;
  action: TaskAction;
  status: "unread" | "read" | "resolved";
  created_at: string | null;
  read_at: string | null;
};

export type PersonalTask = {
  id: string;
  task_type: "approval" | "correction" | "facility_control" | "control_extension";
  title: string;
  description: string;
  counterparty_id: string;
  counterparty_name: string;
  case_id: string | null;
  stage: string;
  stage_label: string;
  correction_id: string | null;
  document_type: string | null;
  facility_id?: string | null;
  condition_id?: string | null;
  extension_id?: string | null;
  status: string;
  sla_status: "normal" | "due_soon" | "overdue" | "escalated";
  due_at: string | null;
  remaining_seconds: number | null;
  owner_roles: string[];
  viewer_mode: "owner" | "collaborator";
  assigned_to: string | null;
  assigned_to_name: string | null;
  assigned_at: string | null;
  assignment_expires_at: string | null;
  lease_remaining_seconds: number | null;
  assignment_expired: boolean;
  assignment_state: "unassigned" | "mine" | "assigned_other" | "direct";
  can_release: boolean;
  claimable: boolean;
  reminder_role: string | null;
  row_version: number;
  action: TaskAction;
};

export type PersonalTaskAssignment = {
  task_type: "approval" | "correction";
  task_id: string;
  assigned_to: string | null;
  assigned_to_name: string | null;
  assigned_at: string | null;
  assignment_expires_at: string | null;
  lease_remaining_seconds: number | null;
  row_version: number;
};

export type PersonalTaskQueue = {
  generated_at: string;
  summary: {
    total: number;
    returned: number;
    truncated: boolean;
    approval: number;
    correction: number;
    facility_control: number;
    control_extension: number;
    post_credit: number;
    due_soon: number;
    overdue: number;
    escalated: number;
  };
  tasks: PersonalTask[];
};

export type TeamTask = PersonalTask & {
  can_force_release: boolean;
  can_remind: boolean;
};

export type TeamTaskBoard = {
  generated_at: string;
  summary: {
    total: number;
    returned: number;
    truncated: boolean;
    claimed: number;
    unassigned: number;
    direct: number;
    expired: number;
    at_risk: number;
  };
  role_load: Array<{ role: string; total: number; claimed: number; unassigned: number; direct: number; risk: number }>;
  assignee_load: Array<{ subject: string | null; name: string; total: number; risk: number }>;
  tasks: TeamTask[];
};

export type OperationsSummary = {
  generated_at: string;
  total_cases: number;
  active_cases: number;
  sla: { normal: number; due_soon: number; overdue: number; escalated: number; paused: number };
  correction_sla: { active: number; normal: number; due_soon: number; overdue: number; escalated: number };
  unread_notifications: { total: number; info: number; warning: number; critical: number };
  last_scan: { run_id: string; run_at: string | null; actor: string; active_cases_scanned: number; active_corrections_scanned: number; notifications_created: number; expired_assignments_released: number } | null;
  stage_distribution: Array<{ stage: string; label: string; count: number }>;
};

export type SlaScanResult = {
  run_id: string;
  run_at: string;
  active_cases_scanned: number;
  due_soon_cases: number;
  overdue_cases: number;
  escalated_cases: number;
  active_corrections_scanned: number;
  due_soon_corrections: number;
  overdue_corrections: number;
  escalated_corrections: number;
  notifications_created: number;
  expired_assignments_released: number;
};

export type CreditFacility = {
  id: string;
  case_id: string;
  counterparty_id: string;
  counterparty_name: string;
  approved_limit: number;
  used_limit: number;
  opening_balance: number;
  supersedes_facility_id: string | null;
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
  control_condition_count: number;
  pending_control_count: number;
  overdue_control_count: number;
  critical_control_count: number;
  row_version: number;
};

export type FacilityControlCondition = {
  id: string;
  facility_id: string;
  source_case_id: string;
  source_review_hash: string;
  sequence: number;
  measure: string;
  owner_role: "risk_manager";
  status: "pending" | "completed";
  due_at: string | null;
  escalation_level: number;
  escalation_role: "risk_manager" | "approver" | "admin" | null;
  escalated_at: string | null;
  linked_alert_id: string | null;
  extension_requests: FacilityControlExtension[];
  sla_status: "on_track" | "due_soon" | "overdue" | "completed";
  days_remaining: number | null;
  overdue_days: number;
  completion_note: string | null;
  completed_by: string | null;
  completed_at: string | null;
  row_version: number;
  created_at: string | null;
};

export type FacilityControlExtension = {
  id: string;
  condition_id: string;
  facility_id: string;
  extension_days: number;
  previous_due_at: string;
  proposed_due_at: string;
  reason: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  requested_by: string;
  requested_by_name: string;
  requested_at: string;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  row_version: number;
  created_at: string | null;
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

export type RenewalRiskBaseline = {
  capture_status: "captured" | "legacy_missing";
  unresolved_alert_count: number;
  critical_alert_count: number;
  active_risk_event_count: number;
  critical_risk_event_count: number;
  signals: Array<{
    alert_type: string;
    severity: "warning" | "critical";
    title: string;
    message: string;
    created_at: string | null;
  }>;
};

export type RenewalRiskReview = {
  status: "completed";
  conclusion: "cleared" | "controls_required" | "decline_recommended";
  review_note: string;
  control_measures: string[];
  baseline_hash: string;
  latest_risk_snapshot: RenewalRiskBaseline;
  latest_risk_hash: string;
  reviewed_by: string;
  reviewed_by_name: string;
  reviewed_at: string;
};

export type CreditFacilityDetail = CreditFacility & {
  transactions: CreditUsageTransaction[];
  control_conditions: FacilityControlCondition[];
  renewal_case: {
    case_id: string;
    application_type: "renewal";
    status: string;
    current_stage: string;
    created_at: string | null;
    request_snapshot: {
      baseline_status: "frozen" | "legacy_facility_fallback";
      current_approved_limit: number;
      current_used_limit: number;
      current_payment_term_days: number;
      current_rating: string | null;
      current_access_strategy: string | null;
      current_monitoring_frequency: string | null;
      source_expires_at: string | null;
      risk_baseline: RenewalRiskBaseline;
      requested_limit: number;
      requested_term_days: number;
      limit_delta: number;
      term_delta_days: number;
      renewal_reason: string;
    };
  } | null;
};

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
  pending_control_conditions: number;
  overdue_control_conditions: number;
  critical_control_conditions: number;
};
