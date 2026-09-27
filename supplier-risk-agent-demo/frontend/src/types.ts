export type Principal = {
  subject: string;
  name: string;
  roles: string[];
  permissions: string[];
  tenant_id: string;
  client_id: string;
  counterparty_id: string | null;
};

export type Counterparty = {
  id: string;
  tenant_id?: string;
  name: string;
  credit_code: string;
  counterparty_type: "supplier" | "customer";
  industry: string;
  cooperation_status: string;
  is_key_counterparty: boolean;
  requested_limit: number;
  current_limit: number;
  current_payment_term_days: number;
  current_rating: string | null;
  current_segment: string | null;
  external: Record<string, unknown>;
  internal: Record<string, unknown>;
  financial: Record<string, unknown>;
  status?: "active" | "archived";
  source_type?: "manual" | "batch_import" | string;
  profile_hash?: string;
  row_version?: number;
  archived_at?: string | null;
  archived_by?: string | null;
  archive_reason?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  data_quality?: { raw_profile_id?: string; recommended_model?: string; internal_transaction_complete?: boolean; missing_critical_fields?: string[] };
};

export type CounterpartyHistoryEvent = {
  id: string;
  event_type: "counterparty_created" | "counterparty_updated" | "counterparty_archived";
  actor: string;
  actor_name: string;
  reason: string;
  changed_fields: string[];
  row_version: number | null;
  previous_hash: string;
  event_hash: string;
  created_at: string | null;
};

export type CounterpartyPage = {
  items: Counterparty[];
  total: number;
  limit: number;
  offset: number;
};

export type CounterpartyImportRowReceipt = {
  row_number: number;
  counterparty_id: string | null;
  credit_code: string | null;
  action: "create" | "update" | "skip" | "reject";
  errors: Array<{ field: string; code: string; message: string }>;
  warnings: Array<{ code: string; message: string }>;
};

export type CounterpartyImportBatch = {
  id: string;
  tenant_id: string;
  import_key: string;
  file_name: string;
  file_format: "json" | "csv";
  duplicate_strategy: "reject" | "skip" | "update";
  field_mapping: Record<string, string>;
  source_hash: string;
  request_hash: string;
  preview_hash: string;
  status: "prechecked" | "blocked" | "committed";
  total_count: number;
  valid_count: number;
  invalid_count: number;
  create_count: number;
  update_count: number;
  skip_count: number;
  committed_count: number;
  row_receipts: CounterpartyImportRowReceipt[];
  precheck_reason: string;
  commit_reason: string | null;
  created_by: string;
  created_by_name: string;
  committed_by: string | null;
  committed_by_name: string | null;
  committed_at: string | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
  idempotent: boolean;
};

export type CounterpartyImportPage = {
  items: CounterpartyImportBatch[];
  total: number;
  limit: number;
  offset: number;
};

export type CounterpartyImportCorrectionDraft = {
  source_batch_id: string;
  source_import_key: string;
  source_hash: string;
  suggested_import_key: string;
  file_name: string;
  file_format: "json" | "csv";
  content: string;
  duplicate_strategy: "reject" | "skip" | "update";
  field_mapping: Record<string, string>;
};

export type CounterpartyImportMappingTemplate = {
  id: string;
  tenant_id: string;
  template_key: string;
  name: string;
  file_format: "json" | "csv";
  mapping: Record<string, string>;
  mapping_hash: string;
  description: string;
  status: "active" | "archived";
  created_by: string;
  updated_by: string;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type GovernanceEvidenceCheck = {
  key: string;
  label: string;
  passed: boolean;
  applicable: boolean;
  detail: string;
};

export type CounterpartyGovernanceEvidence = {
  schema_version: "counterparty-governance-evidence-v1";
  tenant_id: string;
  counterparty_id: string;
  generated_at: string;
  package_hash_algorithm: "SHA-256";
  package_hash: string;
  scope: {
    type: "single_counterparty";
    tenant_boundary: string;
    platform_assets: string;
    documents: string;
  };
  counterparty: Record<string, unknown> & { id: string; name: string; tenant_id: string; profile_hash: string };
  records: Record<string, Array<Record<string, unknown>>>;
  audit: {
    tenant_business_chains: Array<{
      tenant_id: string;
      scope_type: "tenant";
      aggregate_type: string;
      aggregate_id: string;
      valid: boolean;
      event_count: number;
      terminal_hash: string;
      events: Array<Record<string, unknown>>;
    }>;
    platform_asset_checkpoints: Array<{
      evidence_scope: "platform_shared";
      tenant_id: string;
      aggregate_type: string;
      aggregate_id: string;
      event_count: number;
      terminal_hash: string;
      valid: boolean;
    }>;
  };
  platform_asset_references: Array<{
    asset_type: string;
    evidence_scope: "platform_shared";
    id?: string;
    code: string;
    version: string | number;
    config_hash: string;
    assets_hash?: string;
    source_execution_id?: string;
  }>;
  record_hash_checks: GovernanceEvidenceCheck[];
  evidence_assessment: {
    level: "complete" | "partial" | "limited";
    domain_count: number;
    present_domain_count: number;
    completeness_ratio: number;
    domains: Record<string, boolean>;
    missing_domains: string[];
    note: string;
  };
  integrity: { passed: boolean; checks: GovernanceEvidenceCheck[] };
};

export type CounterpartyGovernanceEvidenceVerification = {
  verified: boolean;
  trust_level: "invalid" | "self_sealed" | "externally_anchored";
  computed_package_hash: string;
  expected_package_hash: string | null;
  checks: GovernanceEvidenceCheck[];
  note: string;
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
  tenant_id: string;
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
  tenant_id: string;
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
  tenant_id: string;
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
  tenant_id: string;
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
  tenant_id: string;
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
  tenant_id: string;
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
  tenant_id: string;
  scope_type: "tenant" | "platform";
  aggregate_type: string;
  aggregate_id: string;
  valid: boolean;
  event_count: number;
  terminal_hash: string;
  events: Array<{
    id: string;
    tenant_id: string;
    scope_type: "tenant" | "platform";
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
  tenant_id: string;
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
  scorecard_score?: number;
  scorecard_raw_score?: number;
  scorecard_execution?: {
    scorecard_asset_id: string;
    code: string;
    version: number;
    config_hash: string;
    binding_hash: string;
    score_scale: { min: number; max: number; higher_is_better: boolean };
    raw_range: { min: number; max: number };
    raw_score: number;
    normalized_score: number;
    scaled_score: number;
    missing_count: number;
    details: Array<{
      indicator_code: string;
      indicator_version: string;
      indicator_name: string;
      field_path: string;
      actual_value: unknown;
      bin_kind: "range" | "category" | "missing";
      bin_label: string;
      score: number;
      woe?: number | null;
      weight: number;
      weighted_score: number;
      missing: boolean;
    }>;
  };
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
  access_strategy?: string;
  risk_segment?: string;
  monitoring_frequency?: string;
  review_required?: boolean;
  strong_rule_hits?: Array<Record<string, unknown>>;
  main_deductions?: Array<Record<string, unknown> | string>;
};

export type SalesDemoStory = {
  key: string;
  label: string;
  counterparty_id: string;
  intent: string;
};

export type SalesDemoScenario = {
  key: string;
  eyebrow: string;
  title: string;
  subtitle: string;
  audience: string;
  template_key: string;
  primary_story: string;
  value_points: string[];
  stories: SalesDemoStory[];
  preview?: {
    total_score: number;
    rating: string;
    risk_segment: string;
    access_strategy: string;
    suggested_limit: number;
    suggested_payment_term_days: number;
    review_required: boolean;
  };
  evidence_hash?: string;
};

export type SalesDemoOverview = {
  schema_version: "sales-demo-overview-v1";
  generated_at: string;
  headline: string;
  subheadline: string;
  metrics: {
    scenario_count: number;
    sample_count: number;
    indicator_count: number;
    model_count: number;
    traceable_rate: number;
    requested_total: number;
    suggested_total: number;
  };
  decision_mix: Record<string, number>;
  scenarios: SalesDemoScenario[];
  audience_tracks: Array<{ key: string; label: string; message: string; minutes: number }>;
  overview_hash: string;
};

export type SalesDemoRun = {
  schema_version: "sales-demo-run-v1";
  scenario: SalesDemoScenario;
  story: SalesDemoStory;
  counterparty: {
    id: string;
    name: string;
    credit_code: string;
    counterparty_type: "supplier" | "customer";
    industry: string;
    requested_limit: number;
  };
  result: RatingResult;
  decision_path: Array<{
    key: string;
    kind: string;
    title: string;
    status: "complete" | "attention" | "blocked";
    summary: string;
    detail: string;
    proof: string;
    target_page: "counterparties" | "indicators" | "models" | "rules" | "approvals" | "facilities";
  }>;
  business_summary: {
    risk_summary: string;
    limit_summary: string;
    review_summary: string;
    disclaimer: string;
  };
  evidence: {
    input_snapshot_hash: string;
    model_config_hash: string;
    result_hash: string;
    evidence_hash: string;
    hash_algorithm: "SHA-256";
    model_key: string;
    model_name: string;
    model_version: string;
  };
};

export type SalesDemoDistribution = {
  key: string;
  label: string;
  count: number;
  rate: number;
};

export type SalesDemoComparisonSide = {
  average_score: number;
  average_limit: number;
  total_limit: number;
  average_payment_term_days: number;
  rating_distribution: SalesDemoDistribution[];
  admission_distribution: SalesDemoDistribution[];
  score_distribution: SalesDemoDistribution[];
  ks: null;
  confusion_matrix: null;
};

export type SalesDemoValueDashboard = {
  schema_version: "sales-demo-value-dashboard-v1";
  generated_at: string;
  evidence_scope: {
    data_classification: "synthetic_demo";
    label_status: "unlabeled";
    evidence_level: "non_supervised";
    display_label: string;
    statement: string;
  };
  metrics: {
    fixed_case_count: number;
    source_counterparty_count: number;
    model_count: number;
    execution_success_rate: number;
    automatic_admission_rate: number;
    manual_review_rate: number;
    reject_rate: number;
    average_score: number;
    average_suggested_limit: number;
    total_requested_limit: number;
    total_suggested_limit: number;
    average_payment_term_days: number;
    risk_capture_rate: number | null;
  };
  distributions: {
    rating: SalesDemoDistribution[];
    admission: SalesDemoDistribution[];
    limit: SalesDemoDistribution[];
  };
  top_rule_hits: Array<{ name: string; count: number; rate: number }>;
  model_breakdown: Array<{
    key: string;
    label: string;
    name: string;
    version: string;
    config_hash: string;
    case_count: number;
    average_score: number;
    average_limit: number;
    review_rate: number;
    evidence_hash: string;
  }>;
  supervised_metrics: {
    status: "not_available";
    risk_capture_rate: null;
    ks: null;
    confusion_matrix: null;
    reason: string;
  };
  evidence: {
    snapshot_hash: string;
    case_set_hash: string;
    evidence_hash: string;
    hash_algorithm: "SHA-256";
  };
};

export type SalesDemoChampionChallenger = {
  schema_version: "sales-demo-champion-challenger-v1";
  generated_at: string;
  data_classification: "synthetic_demo";
  evidence_level: "unlabeled";
  champion: { key: string; label: string; name: string; version: string; config_hash: string };
  challenger: { key: string; label: string; name: string; version: string; config_hash: string };
  metrics: {
    sample_count: number;
    failure_count: number;
    average_score_delta: number;
    rating_change_rate: number;
    admission_change_rate: number;
    suggested_limit_delta: number;
    psi: number | null;
    champion: SalesDemoComparisonSide;
    challenger: SalesDemoComparisonSide;
    segments: Array<{
      segment: string;
      label: string;
      sample_count: number;
      champion_average_score: number;
      challenger_average_score: number;
      average_score_delta: number;
      rating_change_rate: number;
      admission_change_rate: number;
    }>;
  };
  supervised_metrics: {
    status: "degraded_to_unsupervised";
    champion_ks: null;
    challenger_ks: null;
    champion_confusion_matrix: null;
    challenger_confusion_matrix: null;
    warning: string;
  };
  evidence: {
    input_snapshot_hash: string;
    champion_model_hash: string;
    challenger_model_hash: string;
    comparison_hash: string;
    hash_algorithm: "SHA-256";
  };
};

export type SalesDemoPostCreditAlert = {
  schema_version: "sales-demo-post-credit-alert-v1";
  generated_at: string;
  data_classification: "synthetic_demo";
  record_status: "read_only_demo";
  alert: {
    id: string;
    title: string;
    alert_type: string;
    severity: "critical";
    severity_label: string;
    status: string;
    observed_at: string;
    counterparty_id: string;
    counterparty_name: string;
    current_exposure: number;
    latest_rating: string;
    latest_admission: string;
    recommended_action: string;
    owner_role: string;
    sla_hours: number;
    escalation_role: string;
  };
  triggers: Array<{
    rule_id: string;
    rule_name: string;
    indicator: string;
    field: string;
    actual_value: unknown;
  }>;
  decision_trace: {
    score: number;
    rating: string;
    admission: string;
    suggested_limit: number;
    monitoring_frequency: string;
    model_name: string;
    model_version: string;
  };
  evidence: {
    counterparty_hash: string;
    model_config_hash: string;
    result_hash: string;
    alert_evidence_hash: string;
    hash_algorithm: "SHA-256";
  };
  disclaimer: string;
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
  tenant_id: string;
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

export type RuleCondition = {
  expression: string;
  operator: "bool" | "==" | "!=" | ">" | ">=" | "<" | "<=";
  value?: unknown;
  label: string;
};

export type RuleAction = {
  type: "rating_override" | "access_strategy" | "risk_segment_override" | "limit_multiplier_cap" | "payment_term_days_cap" | "review_required" | "score_adjustment" | "severity";
  value: unknown;
};

export type RuleDefinition = {
  id: string;
  code: string;
  name: string;
  rule_type: "strong_rule" | "risk_screening" | "admission";
  category: string | null;
  enabled: boolean;
  conditions_json: RuleCondition[];
  condition_relation: "all" | "any";
  actions_json: RuleAction[];
  priority: number;
  version: number;
  status: string;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  created_by: string | null;
};

export type RuleSetDefinition = {
  id: string;
  code: string;
  name: string;
  rule_codes: string[];
  evaluation_strategy: "first_hit" | "all_hits" | "most_restrictive";
  version: number;
  status: string;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  created_by: string | null;
};

export type PipelineStage = {
  stage_type: "scoring" | "strong_rules" | "risk_screening" | "strategy_mapping" | "admission";
  rule_set_code?: string;
};

export type DecisionPipelineDefinition = {
  id: string;
  code: string;
  name: string;
  stages_json: PipelineStage[];
  version: number;
  status: string;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  created_by: string | null;
};

export type RuleTestResult = {
  triggered: boolean;
  details: Array<Record<string, unknown>>;
};

export type PipelineSimulationResult = {
  result: Record<string, unknown>;
  trace: {
    pipeline_code?: string;
    pipeline_version?: number;
    stages?: Array<{ index: number; stage_type: PipelineStage["stage_type"]; rule_set_code?: string | null; output: Record<string, unknown> }>;
  };
};

export type RuleCenterAssetType = "rule" | "rule_set" | "pipeline";

export type RuleCenterGovernanceChange = {
  id: string;
  asset_type: RuleCenterAssetType;
  code: string;
  template_key: string;
  base_version: string;
  candidate_version: string;
  status: "draft" | "pending_review" | "scheduled" | "published" | "rejected" | "activation_failed" | "package_draft" | "package_pending_review";
  config: Record<string, unknown>;
  validation: { valid: boolean; config_hash: string };
  impact: Record<string, unknown>;
  change_reason: string;
  created_by: string;
  created_by_name: string;
  submitted_at: string | null;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  published_at: string | null;
  effective_at: string | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
  restore_source: { code: string; version: number; definition_id: string } | null;
};

export type RuleCenterVersionHistory = {
  id: string;
  asset_type: RuleCenterAssetType;
  code: string;
  version: number;
  status: string;
  is_active: boolean;
  created_by: string | null;
  created_at: string | null;
  config: Record<string, unknown>;
};

export type RuleCenterActivationResult = {
  as_of: string;
  due_count: number;
  published_count: number;
  failed_count: number;
  results: Array<{ change_id: string; status: "published" | "failed"; error: string | null }>;
};

export type RuleCenterPackageImpact = {
  member_count: number;
  create_count: number;
  update_count: number;
  asset_counts: Record<RuleCenterAssetType, number>;
  package_dependency_count: number;
  active_dependency_count: number;
  downstream_assets: { rule_sets: string[]; pipelines: string[] };
};

export type RuleCenterPackagePreview = {
  config_hash: string;
  members: Array<{
    change_id: string;
    asset_type: RuleCenterAssetType;
    code: string;
    base_version: string;
    candidate_version: string;
    config_hash: string;
    change_type: "create" | "update";
  }>;
  dependency_snapshot: Record<string, unknown>;
  impact: RuleCenterPackageImpact;
  release_gate: { passed: boolean; errors: string[]; summary: string };
};

export type RuleCenterReleasePackage = {
  id: string;
  name: string;
  change_reason: string;
  status: "draft" | "pending_review" | "published" | "rejected";
  config_hash: string;
  dependency_snapshot: Record<string, unknown>;
  impact: RuleCenterPackageImpact;
  members: Array<{
    id: string;
    change_id: string;
    asset_type: RuleCenterAssetType;
    code: string;
    candidate_version: string;
    sequence: number;
  }>;
  latest_replay: RuleCenterReplayRun | null;
  created_by: string;
  created_by_name: string;
  submitted_at: string | null;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  published_at: string | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type RuleCenterReplayRun = {
  id: string;
  tenant_id: string;
  package_id: string;
  package_config_hash: string;
  dataset_snapshot_id: string;
  dataset_snapshot_hash: string;
  model_key: string;
  model_version: string;
  pipeline_code: string;
  sample_source: string;
  sample_count: number;
  status: "completed";
  thresholds: {
    sample_limit: number;
    min_sample_count: number;
    max_decision_change_rate: number;
    max_execution_failure_rate: number;
  };
  metrics: {
    sample_count: number;
    failure_count: number;
    failure_rate: number;
    rating_change_count: number;
    rating_change_rate: number;
    decision_change_count: number;
    decision_change_rate: number;
    tightened_count: number;
    loosened_count: number;
    average_score_delta: number | null;
    baseline_rule_hits: Array<{ code: string; hit_count: number; hit_rate: number }>;
    candidate_rule_hits: Array<{ code: string; hit_count: number; hit_rate: number }>;
    rating_migration_matrix: Record<string, Record<string, number>>;
    admission_migration_matrix: Record<string, Record<string, number>>;
  };
  details: Array<Record<string, unknown>>;
  gate: { passed: boolean; errors: string[]; warnings: string[]; summary: string };
  asset_snapshot: Record<string, unknown>;
  assets_hash: string;
  evidence_hash: string;
  created_by: string;
  created_by_name: string;
  created_at: string | null;
};

export type RuleCenterReplaySnapshot = {
  id: string;
  tenant_id: string;
  dataset_id: string;
  version: number;
  source_name: string;
  schema_version: string;
  as_of_date: string;
  evidence_reference: string;
  data_classification: "deidentified" | "synthetic";
  field_mapping: Record<string, string>;
  label_field: string | null;
  observed_at_field: string | null;
  sample_count: number;
  coverage: {
    overall_field_coverage_rate: number;
    field_coverage: Array<{ path: string; present_count: number; coverage_rate: number }>;
    required_fields: Array<{ path: string; present_count: number; coverage_rate: number }>;
    label_coverage_rate: number;
    label_distribution: Record<string, number>;
    observed_at_coverage_rate: number;
    deidentification: { passed: boolean; scanned_field_count: number; sensitive_fields: string[]; data_classification: string };
    time_travel_check: { passed: boolean; future_observation_count: number };
  };
  source_hash: string;
  content_hash: string;
  created_by: string;
  created_by_name: string;
  created_at: string | null;
};

export type RuleCenterReplayDataset = {
  id: string;
  tenant_id: string;
  code: string;
  name: string;
  description: string;
  status: "active";
  latest_snapshot: RuleCenterReplaySnapshot | null;
  created_by: string;
  created_by_name: string;
  created_at: string | null;
};

export type RuleCenterReplayComparisonSide = {
  failure_count: number; failure_rate: number;
  score_mean: number | null; score_min: number | null; score_max: number | null; score_median: number | null;
  raw_score_mean: number | null; raw_score_min: number | null; raw_score_max: number | null;
  business_score_mean: number | null; business_score_min: number | null; business_score_max: number | null;
  rating_distribution: Record<string, number>; admission_distribution: Record<string, number>; score_distribution: Record<string, number>;
  ks: number | null; confusion_matrix: { tp: number; fp: number; tn: number; fn: number } | null;
};

export type RuleCenterReplayComparisonException = {
  id: string; tenant_id: string; comparison_run_id: string; comparison_evidence_hash: string;
  status: "pending_review" | "approved" | "rejected";
  reason: string; business_impact: string; compensating_controls: string;
  valid_until: string; request_hash: string;
  requested_by: string; requested_by_name: string;
  reviewed_by: string | null; reviewed_by_name: string | null;
  reviewed_at: string | null; review_comment: string | null;
  row_version: number; created_at: string | null; updated_at: string | null;
};

export type RuleCenterReplayComparison = {
  id: string; tenant_id: string; dataset_snapshot_id: string; dataset_snapshot_hash: string;
  champion_model_key: string; champion_model_version: string; challenger_model_key: string; challenger_model_version: string;
  challenger_change_id: string | null; challenger_config_hash: string | null;
  champion_pipeline_code: string; champion_pipeline_version: string | null; challenger_pipeline_code: string; challenger_pipeline_version: string | null;
  segment_field: string; evidence_level: "labeled" | "unlabeled";
  config: {
    sample_limit: number; max_execution_failure_rate: number; positive_labels: string[]; positive_admissions: string[];
    score_comparison_basis: "standardized_0_100";
    score_scales: Record<"champion" | "challenger", { min: number; max: number; higher_is_better: boolean; standard_min: 0; standard_max: 100 }>;
    thresholds: { max_psi: number; max_rating_change_rate: number; max_admission_change_rate: number; max_absolute_average_score_delta: number; max_segment_absolute_score_delta: number; max_ks_drop: number; require_labeled_evidence: boolean };
  };
  metrics: {
    sample_count: number; labeled_sample_count: number; champion: RuleCenterReplayComparisonSide; challenger: RuleCenterReplayComparisonSide;
    average_score_delta: number | null; rating_change_rate: number; admission_change_rate: number; psi: number;
    segments: Array<{ segment: string; sample_count: number; champion_score_mean: number | null; challenger_score_mean: number | null; average_score_delta: number | null; rating_change_rate: number; admission_change_rate: number }>;
    warning: string | null;
  };
  gate: { passed: boolean; summary: string; violations: Array<{ key: string; label: string; actual: number; threshold: number; direction: "maximum" | "required"; message: string }>; warnings: string[] };
  effective_status: "passed" | "blocked" | "exception_pending" | "exception_approved";
  latest_exception: RuleCenterReplayComparisonException | null;
  asset_snapshot: Record<string, unknown>; assets_hash: string;
  evidence_hash: string; created_by_name: string; created_at: string | null;
};

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

export type IndicatorCatalogItem = {
  code: string; name: string; category: string; data_type: "numeric" | "categorical" | "boolean";
  version: string; version_source: "indicator_factory" | "enterprise_pool"; field_path: string | null;
  description: string; default_weight: number;
};

export type CreditCalibrationCandidate = {
  score_threshold_shift: number; limit_multiplier_scale: number; revenue_limit_scale: number;
  order_amount_scale: number; payment_term_scale: number; overdue_rate_high: number;
  limit_utilization_high: number; invoice_match_rate_low: number; delivery_fulfillment_rate_low: number;
};

export type CreditCalibrationConfig = {
  template_key: "corporate_credit_v2"; model_name: string; model_version: string; model_config_hash: string;
  policy_status: string; default_candidate: CreditCalibrationCandidate; parameter_notes: Record<string, string>;
  rating_bands: Array<{ rating: string; score_min: number; score_max: number; limit_multiplier: number; payment_term_days: number; access_strategy: string }>;
};

export type CreditCalibrationAnalyzeRequest = {
  dataset_snapshot_id: string; template_key: "corporate_credit_v2"; positive_labels: string[];
  sample_limit: number; candidate: CreditCalibrationCandidate;
};

export type CreditCalibrationModelChangeRequest = CreditCalibrationAnalyzeRequest & {
  candidate_version: string; change_reason: string; expected_evidence_hash: string;
};

export type CreditCalibrationRun = {
  id: string; plan_id: string; plan_config_hash: string; base_model_version: string; baseline_config_hash: string;
  dataset_snapshot_id: string; dataset_snapshot_hash: string; status: "completed" | "failed";
  report: CreditCalibrationResult; evidence_hash: string; evidence_level: "supervised" | "degraded";
  current_valid: boolean; error_message: string | null; created_by: string; created_by_name: string;
  started_at: string; completed_at: string | null; created_at: string;
};

export type CreditCalibrationPlan = {
  id: string; code: string; name: string; version: number; template_key: "corporate_credit_v2";
  status: "draft" | "pending_review" | "approved" | "rejected"; candidate: CreditCalibrationCandidate;
  positive_labels: string[]; sample_limit: number; business_basis: string; config_hash: string;
  created_by: string; created_by_name: string; submitted_at: string | null; reviewed_by: string | null;
  reviewed_by_name: string | null; review_comment: string | null; reviewed_at: string | null;
  row_version: number; created_at: string; updated_at: string; runs: CreditCalibrationRun[];
  latest_valid_run_id: string | null;
};

export type CreditCalibrationComparison = {
  comparable: boolean; compatibility: { same_snapshot: boolean; same_baseline: boolean }; message: string;
  items: Array<{
    plan_id: string; code: string; name: string; version: number; status: CreditCalibrationPlan["status"];
    run_id: string; evidence_level: CreditCalibrationRun["evidence_level"]; snapshot_hash: string; baseline_config_hash: string;
    metrics: Pick<CreditCalibrationMetrics, "automatic_approval_rate" | "manual_review_rate" | "reject_rate" | "average_limit" | "total_limit" | "average_payment_term_days" | "event_exposure_ratio" | "restricted_event_capture_rate">;
    migration: CreditCalibrationResult["migration"];
  }>;
};

export type CreditCalibrationDistribution = { key: string; label?: string; count: number; rate: number };
export type CreditCalibrationMetrics = {
  sample_count: number; average_score: number; automatic_approval_rate: number; manual_review_rate: number; reject_rate: number;
  average_limit: number; median_limit: number; total_limit: number; average_payment_term_days: number;
  event_exposure_ratio: number | null; restricted_event_capture_rate: number | null; event_limit: number | null; non_event_limit: number | null;
  rating_distribution: CreditCalibrationDistribution[]; admission_distribution: CreditCalibrationDistribution[];
  limit_distribution: CreditCalibrationDistribution[]; payment_term_distribution: CreditCalibrationDistribution[];
};

export type CreditCalibrationResult = {
  generated_at: string; evidence_hash: string; governance_note: string; warnings: string[];
  model: { template_key: string; name: string; version: string; baseline_config_hash: string; candidate_config_hash: string };
  snapshot: { id: string; dataset_id: string; dataset_code: string; dataset_name: string; version: number; as_of_date: string; content_hash: string; sample_count: number };
  baseline_parameters: CreditCalibrationCandidate;
  sample: { selected_count: number; paired_success_count: number; failure_count: number; labeled_count: number; event_count: number; non_event_count: number; label_coverage_rate: number; evidence_level: "supervised" | "degraded" };
  candidate_parameters: CreditCalibrationCandidate; baseline: CreditCalibrationMetrics; candidate: CreditCalibrationMetrics;
  deltas: Record<string, number | null>;
  migration: { rating_changed_count: number; rating_change_rate: number; rating_improved_count: number; rating_worsened_count: number; admission_changed_count: number; admission_change_rate: number; rating_cells: Array<{ from: string; to: string; count: number }>; admission_cells: Array<{ from: string; to: string; count: number }> };
  sensitivity: Array<{ score_threshold_shift: number; automatic_approval_rate: number; manual_review_rate: number; reject_rate: number; average_limit: number; total_limit: number; event_exposure_ratio: number | null }>;
  failures: Array<{ sample_id: string; reason: string }>;
};

export type ScorecardBin = {
  kind: "range" | "category" | "missing"; label: string; score: number; woe: number | null;
  lower?: number | null; upper?: number | null; lower_inclusive?: boolean; upper_inclusive?: boolean; values?: string[] | null;
};

export type ScorecardIndicatorBinding = {
  indicator_code: string; indicator_version: string; indicator_name: string;
  field_path: string;
  data_type: "numeric" | "categorical" | "boolean"; weight: number; bins: ScorecardBin[];
};

export type ScorecardDefinitionPayload = {
  code: string; name: string; description: string;
  score_scale: { min: number; max: number; higher_is_better: boolean };
  indicators: ScorecardIndicatorBinding[];
};

export type ScorecardDependencyNode = {
  id: string; type: "scorecard" | "indicator" | "model" | "pipeline" | "rule_set" | "rule" | "release_package";
  code: string; name: string; version: string | null; status: string; lifecycle: "candidate" | "dependency" | "active" | "evidence" | "inflight";
  model_kind?: "release" | "snapshot" | "change"; directly_bound?: boolean; field_path?: string; config_hash?: string;
};

export type ScorecardDependencyGraph = {
  schema_version: "scorecard-dependency-graph-v1"; root_id: string;
  nodes: ScorecardDependencyNode[];
  edges: Array<{ source: string; target: string; relation: string; direct: boolean }>;
  summary: Record<"indicator" | "model" | "pipeline" | "rule_set" | "rule" | "release_package", number>;
  risks: Array<{ key: string; severity: "high" | "medium"; label: string; count: number; node_ids: string[] }>;
  required_actions: string[]; graph_hash: string;
};

export type ScorecardChange = {
  id: string; code: string; base_version: string; candidate_version: string;
  status: "draft" | "submitted" | "published" | "rejected"; definition: ScorecardDefinitionPayload;
  validation: { valid: boolean; errors: string[]; warnings: string[]; summary: { indicator_count: number; total_weight: number; score_min: number; score_max: number; bin_count: number } };
  impact: {
    indicator_codes: string[]; affected_models: string[]; inflight_model_drafts: string[];
    dependency_graph: ScorecardDependencyGraph; dependency_graph_hash: string;
    dependency_graph_current_hash: string; dependency_graph_drifted: boolean; dependency_graph_legacy: boolean;
  };
  change_reason: string; created_by: string; created_by_name: string; reviewed_by_name: string | null;
  review_comment: string | null; row_version: number; created_at: string | null; submitted_at: string | null; published_at: string | null;
};

export type ScorecardAsset = {
  id: string; code: string; name: string; description: string; version: number; status: string; is_active: boolean;
  config: ScorecardDefinitionPayload; config_hash: string; change_id: string; created_by_name: string; published_at: string | null;
};

export type ScorecardDevelopmentExclusionRule = {
  field_path: string; operator: "equals" | "not_equals" | "in" | "is_missing" | "not_missing"; value: unknown; reason: string;
};

export type ScorecardValidationThresholds = {
  require_validation_snapshot: boolean; require_oot_snapshot: boolean; require_probability_evidence: boolean; require_sensitive_attribute_evidence: boolean;
  min_auc: number; min_ks: number; max_brier: number; max_score_psi: number; min_segment_coverage: number;
  max_event_rate_gap: number; max_average_score_gap: number; max_auc_gap: number; max_ks_gap: number;
  max_false_positive_rate_gap: number; max_false_negative_rate_gap: number;
};

export type ScorecardValidationPolicy = {
  id: string; code: string; name: string; description: string; version: number;
  status: "draft" | "submitted" | "published" | "rejected"; is_active: boolean; is_default: boolean;
  applicable_scorecard_codes: string[]; thresholds: ScorecardValidationThresholds; config_hash: string;
  change_reason: string; created_by: string; created_by_name: string; reviewed_by_name: string | null;
  review_comment: string | null; row_version: number; created_at: string | null; submitted_at: string | null; published_at: string | null;
};

export type ScorecardValidationPolicySnapshot = {
  id: string; code: string; name: string; version: number; config_hash: string; is_default: boolean;
  applicable_scorecard_codes: string[]; thresholds: ScorecardValidationThresholds;
};

export type ScorecardDevelopmentRun = {
  id: string; scorecard_asset_id: string; scorecard_code: string; scorecard_version: number; scorecard_config_hash: string;
  dataset_snapshot_id: string; dataset_snapshot_hash: string;
  validation_policy_id?: string | null; validation_policy_hash?: string | null;
  validation_policy?: ScorecardValidationPolicySnapshot | null; validation_policy_integrity_valid?: boolean;
  validation_snapshot_id?: string | null; validation_snapshot_hash?: string | null;
  oot_snapshot_id?: string | null; oot_snapshot_hash?: string | null;
  label_policy: {
    positive_labels: string[]; observation_start: string | null; observation_end: string | null;
    performance_window_days: number; maturity_days: number; min_sample_count: number; min_event_count: number; min_non_event_count: number;
    subject_id_field?: string; predicted_probability_field?: string | null;
    segment_fields?: string[]; sensitive_attribute_fields?: string[]; min_segment_sample_count?: number; classification_threshold?: number;
    validation_thresholds: ScorecardValidationThresholds;
    exclusion_rules: ScorecardDevelopmentExclusionRule[];
  };
  report: {
    schema_version: "scorecard-development-report-v1" | "scorecard-development-report-v2" | "scorecard-development-report-v3" | "scorecard-development-report-v4"; evidence_level: "labeled" | "degraded" | "unlabeled";
    summary: { snapshot_sample_count: number; eligible_sample_count: number; event_count: number; non_event_count: number; unlabeled_count: number; immature_count: number; outside_window_count: number; excluded_count: number; exclusion_reasons: Record<string, number>; total_information_value: number };
    gates: Record<"sample_count" | "event_count" | "non_event_count", { actual: number; required: number; passed: boolean }>;
    label_definition: { positive_labels: string[]; observation_start: string | null; observation_end: string | null; performance_window_days: number; maturity_days: number };
    indicators: Array<{
      indicator_code: string; indicator_version: string; indicator_name: string; field_path: string; sample_count: number; unmatched_count: number; missing_count: number; information_value: number; event_rate_monotonic: boolean | null;
      bins: Array<{ bin_index: number; bin_kind: "range" | "category" | "missing"; bin_label: string; configured_woe: number | null; sample_count: number; event_count: number; non_event_count: number; event_rate: number | null; calculated_woe: number | null; iv_contribution: number | null; woe_source: "sample_calculated" }>;
    }>;
    performance?: Record<"training" | "validation" | "oot", {
      sample_count: number; event_count: number; non_event_count: number;
      auc: number | null; ks: number | null; brier: number | null; probability_coverage_rate: number;
      score_psi?: number | null; score_distribution: Record<string, number>;
      calibration: Array<{ range: string; sample_count: number; predicted_rate: number | null; actual_rate: number | null }>;
    } | null>;
    split_evidence?: {
      subject_id_field: string; leakage_passed: boolean;
      overlaps: Array<{ left: string; right: string; count: number; sample_ids: string[] }>;
      snapshots: Record<"training" | "validation" | "oot", { id: string; content_hash: string; as_of_date: string } | null>;
    };
    fairness?: {
      status: "tested" | "untestable"; segment_fields: string[]; sensitive_attribute_fields: string[];
      min_segment_sample_count: number; classification_threshold: number; warnings: string[];
      splits: Record<"training" | "validation" | "oot", Record<string, {
        field_path: string; sensitive_attribute: boolean; status: "tested" | "untestable" | "too_many_groups";
        sample_count: number; covered_count: number; missing_count: number; coverage_rate: number; group_count: number;
        population_psi?: number | null; distribution: Record<string, number>;
        disparities: Record<string, number | null>;
        groups: Array<{
          group: string; sample_count: number; population_share: number; sample_sufficient: boolean;
          event_rate: number; average_score: number; auc: number | null; ks: number | null;
          false_positive_rate: number | null; false_negative_rate: number | null; probability_coverage_rate: number;
          score_psi?: number | null; score_distribution: Record<string, number>;
        }>;
      }> | null>;
    };
    validation_gate?: {
      passed: boolean; summary: string; thresholds: ScorecardValidationThresholds;
      checks: Array<{ key: string; label: string; scope: string; actual: number | null; threshold: number; operator: string; testable: boolean; passed: boolean; detail: string }>;
      violations: Array<{ key: string; label: string; scope: string; actual: number | null; threshold: number; operator: string; testable: boolean; passed: false; detail: string }>;
      warnings: string[];
    };
    warnings: string[];
  };
  evidence_hash: string; evidence_level: "labeled" | "degraded" | "unlabeled"; integrity_valid: boolean;
  review_status: "not_required" | "pending_review" | "approved" | "rejected";
  reviewed_by: string | null; reviewed_by_name: string | null; review_comment: string | null; reviewed_at: string | null;
  review_hash: string | null; review_integrity_valid: boolean; row_version: number;
  created_by: string; created_by_name: string; created_at: string | null;
};

export type ScorecardDevelopmentTrendMetricKey =
  | "validation_auc" | "validation_ks" | "validation_brier" | "validation_score_psi"
  | "oot_auc" | "oot_ks" | "oot_brier" | "oot_score_psi"
  | "max_group_score_psi" | "max_event_rate_gap" | "max_average_score_gap";

export type ScorecardDevelopmentTrendPoint = {
  run_id: string; scorecard_asset_id: string; scorecard_code: string; scorecard_version: number; scorecard_config_hash: string;
  created_at: string | null; snapshot_dates: Record<"training" | "validation" | "oot", string | null>;
  status: "pass" | "block" | "invalid" | "legacy"; evidence_level: "labeled" | "degraded" | "unlabeled";
  integrity_valid: boolean; review_status: ScorecardDevelopmentRun["review_status"]; violation_count: number; gate_summary: string | null;
  validation_policy: ScorecardValidationPolicySnapshot | null;
  metrics: Record<ScorecardDevelopmentTrendMetricKey, number | null>;
  thresholds: Record<ScorecardDevelopmentTrendMetricKey, number | null>;
};

export type ScorecardDevelopmentTrends = {
  generated_at: string;
  summary: { run_count: number; scorecard_count: number; pass_count: number; block_count: number; invalid_count: number; pending_review_count: number };
  series: Array<{
    scorecard_code: string; scorecard_versions: number[]; point_count: number; pass_rate: number | null;
    latest_status: ScorecardDevelopmentTrendPoint["status"]; latest_run_id: string; points: ScorecardDevelopmentTrendPoint[];
  }>;
};

export type ScorecardPortfolioStatus = "healthy" | "attention" | "blocked" | "invalid" | "unmonitored";
export type ScorecardPortfolioStability = {
  generated_at: string;
  summary: {
    scorecard_count: number; healthy_count: number; attention_count: number; blocked_count: number;
    invalid_count: number; unmonitored_count: number; open_event_count: number; overdue_event_count: number;
    enabled_plan_count: number;
  };
  rows: Array<{
    scorecard_code: string; scorecard_name: string; latest_version: number | null; active_asset_id: string | null;
    status: ScorecardPortfolioStatus; status_reason: string; latest_run_id: string | null; latest_run_at: string | null;
    latest_run_status: ScorecardDevelopmentTrendPoint["status"] | null; previous_run_id: string | null;
    evidence_level: ScorecardDevelopmentRun["evidence_level"] | null; integrity_valid: boolean | null;
    review_status: ScorecardDevelopmentRun["review_status"] | null;
    metrics: Partial<Record<ScorecardDevelopmentTrendMetricKey, number | null>>;
    deltas: Partial<Record<ScorecardDevelopmentTrendMetricKey, number | null>>;
    metric_health: Partial<Record<ScorecardDevelopmentTrendMetricKey, {
      value: number | null; threshold: number | null; direction: "min" | "max";
      ratio: number | null; status: "healthy" | "near" | "breach" | "untestable";
    }>>;
    threshold_signal_count: number;
    monitoring: { plan_count: number; enabled_plan_count: number; failed_plan_count: number; next_run_at: string | null; latest_plan_run_at: string | null };
    open_events: { total: number; critical: number; warning: number; overdue: number; due_soon: number };
  }>;
};

export type ScorecardMonitoringRunConfig = {
  subject_id_field: string; predicted_probability_field?: string | null;
  segment_fields: string[]; sensitive_attribute_fields: string[];
  min_segment_sample_count: number; classification_threshold: number; positive_labels: string[];
  performance_window_days: number; maturity_days: number; min_sample_count: number; min_event_count: number; min_non_event_count: number;
  exclusion_rules: ScorecardDevelopmentExclusionRule[];
};

export type ScorecardMonitoringPlan = {
  id: string; code: string; name: string; description: string;
  scorecard_asset_id: string; scorecard: { code: string; name: string; version: number; config_hash: string } | null;
  validation_policy_id: string; validation_policy: { code: string; name: string; version: number; config_hash: string; active: boolean } | null;
  training_dataset_id: string; validation_dataset_id: string | null; oot_dataset_id: string | null;
  datasets: Record<"training" | "validation" | "oot", { id: string; code: string; name: string } | null>;
  run_config: ScorecardMonitoringRunConfig; cadence: "monthly" | "quarterly"; timezone_name: "Asia/Shanghai" | "UTC";
  enabled: boolean; next_run_at: string; owner: string; last_scheduled_for: string | null; last_run_at: string | null;
  last_run_id: string | null; last_status: "completed" | "failed" | null; last_error: string | null; row_version: number;
  created_by: string; updated_by: string; created_at: string | null; updated_at: string | null;
};

export type ScorecardMonitoringEventType = "gate_failed" | "consecutive_deterioration" | "evidence_integrity_failed" | "policy_integrity_failed" | "scheduled_run_failed";
export type ScorecardMonitoringSlaRule = { response_hours: number; due_soon_ratio: number; escalation_after_hours: number };
export type ScorecardMonitoringSlaPolicy = {
  id: string; code: string; name: string; description: string; version: number;
  status: "draft" | "submitted" | "published" | "rejected"; is_active: boolean; is_default: boolean;
  applicable_scorecard_codes: string[]; applicable_event_types: ScorecardMonitoringEventType[];
  severity_rules: Record<"critical" | "warning", ScorecardMonitoringSlaRule>; config_hash: string;
  change_reason: string; created_by: string; created_by_name: string; reviewed_by_name: string | null;
  review_comment: string | null; row_version: number; created_at: string | null; submitted_at: string | null; published_at: string | null;
};
export type ScorecardMonitoringSlaPolicySnapshot = {
  id: string | null; code: string; name: string; version: number; config_hash: string;
  applicable_scorecard_codes: string[]; applicable_event_types: ScorecardMonitoringEventType[];
  severity_rules: Record<"critical" | "warning", ScorecardMonitoringSlaRule>;
};

export type ScorecardMonitoringEvent = {
  id: string; plan_id: string; run_id: string | null; evidence_hash: string | null;
  event_type: ScorecardMonitoringEventType;
  severity: "critical" | "warning"; metric_key: string | null; metric_label: string | null;
  metric_value: number | null; threshold_value: number | null; threshold_operator: string | null;
  title: string; description: string; details: Record<string, unknown>;
  status: "open" | "acknowledged" | "in_remediation" | "pending_revalidation" | "closed"; assignee: string | null;
  sla_policy_id: string | null; sla_policy_snapshot: ScorecardMonitoringSlaPolicySnapshot | null;
  sla_policy_snapshot_hash: string | null; sla_policy_integrity_valid: boolean;
  sla_started_at: string; sla_due_at: string; sla_status: "normal" | "due_soon" | "overdue" | "escalated";
  escalation_level: number; last_escalated_at: string | null;
  acknowledged_by: string | null; acknowledged_at: string | null; remediation_plan: string | null; remediation_result: string | null;
  remediated_by: string | null; remediated_at: string | null; revalidation_run_id: string | null; revalidation_evidence_hash: string | null;
  revalidation_conclusion: string | null; revalidated_by: string | null; revalidated_by_name: string | null; revalidated_at: string | null;
  closed_by: string | null; closed_at: string | null; row_version: number; created_by: string; created_at: string | null; updated_at: string | null;
};

export type ScorecardMonitoringEventFilters = {
  status?: ScorecardMonitoringEvent["status"];
  severity?: ScorecardMonitoringEvent["severity"];
  event_type?: ScorecardMonitoringEventType;
  assignee?: string;
  plan_id?: string;
  scorecard_code?: string;
  sla_status?: ScorecardMonitoringEvent["sla_status"];
};

export type ScorecardMonitoringSavedView = {
  id: string; owner_subject: string; name: string; filters: ScorecardMonitoringEventFilters;
  is_default: boolean; row_version: number; created_at: string; updated_at: string;
};

export type ScorecardMonitoringBulkAssignResult = {
  batch_id: string; assigned_count: number; assignee: string; events: ScorecardMonitoringEvent[];
};

export type ScorecardMonitoringExecution = {
  plan: ScorecardMonitoringPlan; run: ScorecardDevelopmentRun | null; events: ScorecardMonitoringEvent[]; idempotent: boolean;
};

export type ScorecardMonitoringTick = {
  as_of: string; due_count: number; completed_count: number; failed_count: number; results: ScorecardMonitoringExecution[];
};

export type ScorecardMonitoringSchedulerRun = {
  id: string; run_key: string; trigger_type: "manual" | "scheduler" | "retry" | "recovery";
  status: "running" | "completed" | "partial_failed" | "failed" | "dead_letter";
  as_of: string; started_at: string; last_heartbeat_at: string | null; completed_at: string | null;
  actor: string; attempt_number: number; max_attempts: number; recovery_of_run_id: string | null; recovery_reason: string | null;
  due_count: number; completed_count: number; failed_count: number; backlog_before: number; backlog_after: number;
  oldest_due_at: string | null; error_type: string | null; error_message: string | null;
  progress: { completed: number; total: number; last_plan_id: string } | null;
  can_retry: boolean; can_recover: boolean;
};

export type ScorecardMonitoringSchedulerExecution = {
  run: ScorecardMonitoringSchedulerRun | null; tick: ScorecardMonitoringTick | null; deduplicated: boolean;
  status?: "skipped"; skip_reason?: "scheduler_busy"; active_lease?: ScorecardMonitoringSchedulerHealth["lease"];
};

export type ScorecardMonitoringSchedulerHealth = {
  generated_at: string; health: "healthy" | "degraded" | "blocked" | "never";
  expected_cadence_minutes: number; stale_after_minutes: number; max_attempts: number;
  lease: {
    status: "idle" | "active" | "expired"; execution_id: string | null; run_key: string | null;
    actor: string | null; trigger_type: string | null; acquired_at: string | null; expires_at: string | null;
    last_heartbeat_at: string | null; heartbeat_count: number; heartbeat_age_seconds: number | null; remaining_seconds: number;
  };
  backlog: { count: number; oldest_due_at: string | null; oldest_age_seconds: number };
  scheduler: { last_run_at: string | null; last_status: string | null; minutes_since_last_run: number | null; next_expected_at: string | null };
  summary: { returned_runs: number; completed: number; failed: number; dead_letter: number; running: number };
  runs: ScorecardMonitoringSchedulerRun[];
};

export type ModelScorecardBinding = {
  scorecard_asset_id: string; code: string; version: number; config_hash: string; config: ScorecardDefinitionPayload;
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
  scorecard_binding: ModelScorecardBinding | null;
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

export type ModelRiskCatalog = {
  code: string; level: "low" | "medium" | "high"; name: string; basis: string[];
  acceptance_roles: string[]; review_days: number; regulatory_mapping: string[]; required_evidence: string[];
};

export type ModelRiskPolicy = {
  id: string; tenant_id: string; version: number; name: string; description: string;
  levels: ModelRiskCatalog[]; config_hash: string;
  status: "draft" | "pending_review" | "published" | "rejected" | "retired"; is_active: boolean;
  change_reason: string; created_by: string; created_by_name: string; submitted_at: string | null;
  reviewed_by: string | null; reviewed_by_name: string | null; reviewed_at: string | null;
  review_comment: string | null; published_at: string | null; row_version: number;
  created_at: string | null; updated_at: string | null;
};

export type ModelRiskCatalogResponse = {
  source: "platform_default" | "tenant_policy"; version: string; policy: ModelRiskPolicy | null;
  items: ModelRiskCatalog[]; config_hash: string;
};

export type ModelRiskAcceptanceRole = "model_owner" | "risk_manager" | "model_risk_committee";

export type ModelRiskAcceptance = {
  id: string; tenant_id: string; model_change_id: string; policy_id: string; policy_version: number;
  policy_config_hash: string; evidence_binding_hash: string; risk_level: "low" | "medium" | "high";
  required_roles: ModelRiskAcceptanceRole[];
  approvals: Array<{ acceptance_role: ModelRiskAcceptanceRole; platform_role: string; actor_subject: string; actor_name: string; note: string; accepted_at: string }>;
  status: "pending" | "accepted" | "revoked";
  effective_status: "pending" | "accepted" | "revoked" | "overdue" | "policy_stale" | "evidence_stale";
  rationale: string; created_by: string; created_by_name: string; accepted_at: string | null;
  review_due_at: string | null; revoked_by: string | null; revoked_by_name: string | null;
  revoked_at: string | null; revocation_reason: string | null; row_version: number; created_at: string | null;
  idempotent?: boolean;
};

export type ModelRiskReviewQueueItem = {
  acceptance_id: string; model_change_id: string; risk_level: "low" | "medium" | "high";
  policy_version: number; review_due_at: string; days_remaining: number;
  level: "upcoming" | "due_soon" | "overdue";
  responsible: Array<{ subject: string; role: string; name: string }>;
};

export type ModelRiskReacceptanceReviewQueueItem = {
  reacceptance_id: string; model_release_id: string; model_change_id: string;
  risk_level: "low" | "medium" | "high"; model_version: string | null;
  review_due_at: string; days_remaining: number; level: "upcoming" | "due_soon" | "overdue";
  runtime_impact: "at_risk" | "blocked"; pending_renewal_id: string | null;
  evidence_level: string;
  responsible: Array<{ subject: string; role: string; name: string }>;
};

export type ModelRiskUnifiedReviewQueueItem = {
  id: string;
  source: "risk_acceptance" | "risk_reacceptance" | "monitoring_gate" | "monitoring_diff_case";
  priority: "P0" | "P1" | "P2" | "P3" | "P4";
  priority_reason: string;
  state: string;
  title: string;
  summary: string;
  due_at: string | null;
  days_remaining: number | null;
  model_key: string | null;
  model_version: string | null;
  model_change_id: string | null;
  model_release_id: string | null;
  policy_id: string | null;
  monitoring_run_id: string | null;
  diff_case_id: string | null;
  evidence_level: string | null;
  source_row_version?: number;
  responsible: Array<{ subject: string | null; role: string; name: string }>;
  action: { target: "model-risk-policy" | "release-approval-dashboard" | "tenant-rollout-governance"; label: string };
};

export type ModelRiskReviewAssignment = {
  id: string; item_id: string; source: string; assigned_role: string;
  assigned_to: string | null; assigned_to_name: string | null; reason: string;
  assigned_by: string; assigned_by_name: string; row_version: number;
  created_at: string | null; updated_at: string | null;
};

export type ModelRiskReviewWorkbench = {
  schema_version: "model-risk-review-queue-v2"; as_of: string;
  filters: { template_key: string | null; horizon_days: number; source: string | null; priority: string | null; owner_subject: string | null; owner_role: string | null; ownership: string; evidence_level: string | null; query: string | null };
  counts: { total: number; p0: number; p1: number; p2: number; p3: number; p4: number; mine: number; unassigned: number; [key: string]: number };
  items: Array<ModelRiskUnifiedReviewQueueItem & { assignment: ModelRiskReviewAssignment | null; delegated: boolean; delegated_from: { subject: string; name: string; role: string } | null; delegation_id: string | null }>;
  available_owners: Array<{ subject: string; role: string; name: string }>;
  available_roles: string[];
};

export type ModelRiskReviewMember = {
  subject: string; name: string; roles: string[]; expires_at: string | null;
};

export type ModelRiskReviewDelegation = {
  id: string; principal_subject: string; principal_name: string; delegate_subject: string; delegate_name: string;
  assigned_role: string; starts_at: string; ends_at: string; status: "active" | "revoked";
  effective_status: "scheduled" | "active" | "expired" | "revoked"; reason: string;
  created_by: string; created_by_name: string; revoked_by: string | null; revoked_by_name: string | null;
  revoked_at: string | null; revocation_reason: string | null; row_version: number;
  created_at: string | null; updated_at: string | null;
};

export type ModelRiskReviewAssignmentHistory = {
  item_id: string;
  items: Array<{
    id: string; event_type: string; actor: string; actor_name: string | null; action: "assign" | "handoff" | "unassign";
    previous: { subject: string | null; name: string | null; role: string | null };
    next: { subject: string | null; name: string | null; role: string | null };
    reason: string; batch_id: string; event_hash: string; created_at: string | null;
  }>;
};

export type ModelRiskReviewSavedView = {
  id: string; tenant_id: string; owner_subject: string; name: string;
  filters: Record<string, unknown>; is_default: boolean; row_version: number;
  created_at: string | null; updated_at: string | null;
};

export type ModelRiskReviewSlaTrend = {
  schema_version: "model-risk-review-sla-trend-v1"; days: number; template_key: string | null;
  items: Array<{ id: string; snapshot_date: string; template_key: string | null; counts: Record<string, number>; source_counts: Record<string, number>; owner_counts: Record<string, number>; evidence_hash: string; created_at: string | null }>;
};

export type ModelRiskReacceptance = {
  id: string; tenant_id: string; model_release_id: string; model_change_id: string; prior_acceptance_id: string;
  policy_id: string; policy_version: number; policy_config_hash: string; source_evidence_binding_hash: string;
  release_config_hash: string; operational_evidence: { evidence_reference: string; evidence_summary: string; observed_from: string; observed_to: string; captured_at: string; monitoring_binding?: { evidence_level: "supervised" | "non_supervised"; status: string }; [key: string]: unknown };
  operational_evidence_hash: string; risk_level: "low" | "medium" | "high"; required_roles: ModelRiskAcceptanceRole[];
  monitoring_run_id: string | null; monitoring_evidence_hash: string | null; label_evidence_id: string | null;
  approvals: ModelRiskAcceptance["approvals"]; status: "pending" | "accepted" | "revoked";
  effective_status: "pending" | "accepted" | "revoked" | "overdue" | "policy_stale" | "evidence_stale" | "release_stale";
  rationale: string; created_by: string; created_by_name: string; accepted_at: string | null; review_due_at: string | null;
  revoked_by: string | null; revoked_by_name: string | null; revoked_at: string | null; revocation_reason: string | null;
  row_version: number; created_at: string | null; idempotent?: boolean;
};

export type ModelRiskReacceptanceAuditPackage = {
  schema_version: "model-risk-reacceptance-audit-package-v1";
  tenant_id: string; generated_at: string; package_hash: string;
  reacceptance: ModelRiskReacceptance;
  prior_acceptance: ModelRiskAcceptance | null;
  release: { id: string; template_key: string; model_version: string; config_hash: string; published_at: string | null } | null;
  policy: ModelRiskPolicy | null;
  model_change: { id: string; candidate_version: string; supervised_validation_binding_hash: string } | null;
  monitoring_run: ModelMonitoringRun | null;
  supervised_evaluation: { id: string; tenant_id: string; policy_id: string; status: string; evidence_level: string; evidence_hash: string; label_definition_id: string | null; label_definition_version: number | null; label_definition_hash: string | null; label_watermark: Record<string, unknown>; coverage: Record<string, unknown>; metrics: Record<string, unknown>; reviewed_at: string | null } | null;
  audit_events: Array<{ id: string; event_type: string; actor: string; payload: Record<string, unknown>; previous_hash: string; event_hash: string; created_at: string | null }>;
};

export type ModelRiskReacceptanceRegulatoryReport = {
  schema_version: "model-risk-reacceptance-regulatory-report-v1";
  tenant_id: string; generated_at: string; reacceptance_id: string; report_hash: string;
  model: { release_id: string | null; template_key: string | null; model_version: string | null; config_hash: string | null; published_at: string | null };
  observation_window: { observed_from: string | null; observed_to: string | null; captured_at: string | null; evidence_reference: string | null };
  governance: { risk_level: string; policy_id: string; policy_version: number; policy_config_hash: string; required_evidence: string[]; required_roles: string[]; signed_roles: string[]; four_eyes: { required: boolean; passed: boolean; distinct_signer_count: number }; approvals: ModelRiskAcceptance["approvals"] };
  evidence: { level: string; source: string; coverage: Record<string, unknown>; metrics: Record<string, unknown>; tenant_supervised_evaluation_id: string | null; supervised_evidence_hash: string | null; label_definition_id: string | null; label_definition_version: number | null; downgrade: { status: string; reason: string } | null };
  runtime_impact: { status: "accepted" | "at_risk" | "blocked" | "evidence_stale"; effective_status: string; review_due_at: string | null };
  integrity: { package_hash: string; operational_evidence_hash: string; monitoring_evidence_hash: string | null; supervised_evidence_hash: string | null; audit_event_count: number; audit_chain_scope: string };
  signing: { signature_algorithm: string; signing_key_id: string | null; signing_public_key: string | null; public_key_fingerprint: string | null; signature: string; signature_body: Record<string, unknown>; key_metadata: { status: string; trust_class: string; issuer: string | null; rotation_id: string | null; not_before: string | null; not_after: string | null; trust_directory_id: string | null; revocation_reference: string | null }; signature_valid: boolean; timestamp_mode: string };
};

export type ModelValidationAttachment = {
  id: string; tenant_id: string; model_change_id: string; name: string; reference: string;
  content_type: string; size_bytes: number; sha256: string; status: "active" | "revoked"; scan_status: "not_scanned" | "pending" | "passed" | "rejected";
  scan_engine: string | null; scan_result_reason: string | null; scan_completed_by: string | null; scan_completed_by_name: string | null; scan_completed_at: string | null; row_version: number;
  uploaded_by_name: string; uploaded_at: string | null; revoked_at: string | null;
};

export type ModelValidationReportIssuance = {
  id: string; tenant_id: string; model_change_id: string; report_template_version: string;
  report_hash: string; evidence_binding_hash: string; package_hash: string;
  signature_algorithm: string; signing_key_id: string | null; public_key_fingerprint: string | null; signature: string; issued_by: string; issued_by_name: string;
  issued_at: string; status: "active" | "revoked"; revoked_by: string | null;
  revoked_by_name: string | null; revoked_at: string | null; revocation_reason: string | null;
  supersedes_issuance_id: string | null; replacement_issuance_id: string | null; reissue_reason: string | null;
  package_hash_valid: boolean; signature_valid: boolean; registry_valid: boolean; trust_eligible: boolean;
  row_version: number; package?: Record<string, unknown>; idempotent?: boolean;
};

export type ModelReleaseApprovalDashboard = {
  schema_version: "model-release-approval-dashboard-v1"; tenant_id: string;
  counts: { total: number; blocked: number; pending_validation: number; pending_release: number; published: number; restart_eligible: number };
  rows: Array<{
    change_id: string; template_key: string; base_version: string; candidate_version: string;
    change_status: string; created_by_name: string; created_at: string | null; supervised: boolean;
    report_hash: string | null; risk_level: "low" | "medium" | "high" | null;
    independent_validation_status: string; release_approval_status: string;
    attachment_count: number; attachment_hashes: string[]; issuance: ModelValidationReportIssuance | null;
    risk_policy: { source: "platform_default" | "tenant_policy"; version: string; config_hash: string };
    risk_acceptance: ModelRiskAcceptance | null;
    release: { id: string; model_version: string; is_active: boolean } | null;
    restart_status: "draft_created" | "eligible" | "awaiting_release" | "awaiting_terminal_policy" | "not_applicable";
    source_policy_id: string | null; in_service_risk?: { required?: boolean; effective_status: string; release_id?: string; reacceptance: ModelRiskReacceptance | null; pending_renewal?: ModelRiskReacceptance | null } | null; blockers: string[]; ready_for_submit: boolean; ready_for_release: boolean;
  }>;
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
    scorecard_binding?: ModelScorecardBinding | null;
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
    scorecard_binding_changed: boolean;
    risk_screening_impacted_count: number;
    max_abs_risk_screening_delta: number;
    average_limit_delta: number;
    details: Array<Record<string, string | number>>;
  };
  comparison_evidence: {
    comparison_run_id?: string;
    comparison_evidence_hash?: string;
    dataset_snapshot_id?: string;
    dataset_snapshot_hash?: string;
    champion_model_key?: string;
    champion_model_version?: string;
    challenger_model_key?: string;
    challenger_model_version?: string;
    challenger_config_hash?: string;
    gate?: RuleCenterReplayComparison["gate"];
    effective_status?: RuleCenterReplayComparison["effective_status"];
    current_gate?: RuleCenterReplayComparison["gate"];
    current_effective_status?: RuleCenterReplayComparison["effective_status"] | "invalid";
    latest_exception?: RuleCenterReplayComparisonException | null;
    evidence_level?: "labeled" | "unlabeled";
    valid_until?: string;
    binding_hash?: string;
    current_error?: string;
  };
  scorecard_validation_evidence: {
    validation_run_id?: string;
    scorecard_asset_id?: string; scorecard_code?: string; scorecard_version?: number; scorecard_config_hash?: string;
    dataset_snapshot_id?: string; dataset_snapshot_hash?: string;
    validation_snapshot_id?: string | null; validation_snapshot_hash?: string | null;
    oot_snapshot_id?: string | null; oot_snapshot_hash?: string | null;
    report_schema_version?: string; evidence_level?: "labeled" | "degraded" | "unlabeled";
    evidence_hash?: string; validation_gate_hash?: string; validation_gate_summary?: string;
    review_hash?: string; reviewed_by_name?: string; reviewed_at?: string;
    bound_at?: string; bound_by_name?: string; binding_hash?: string;
    current_valid?: boolean; current_error?: string;
  };
  calibration_evidence: {
    schema_version?: string; dataset_snapshot_id?: string; dataset_snapshot_hash?: string;
    plan_id?: string; plan_code?: string; plan_version?: number; plan_config_hash?: string;
    plan_reviewed_by?: string; calibration_run_id?: string;
    template_key?: string; base_model_version?: string; baseline_config_hash?: string;
    candidate_config_hash?: string; analysis?: CreditCalibrationResult;
    bound_at?: string; bound_by?: string; bound_by_name?: string; binding_hash?: string;
    current_valid?: boolean; current_error?: string;
  };
  supervised_validation_evidence: {
    schema_version?: string; tenant_id?: string; policy_id?: string; evaluation_id?: string;
    evaluation_evidence_hash?: string; report_hash?: string; report_template_version?: string;
    evidence_level?: "supervised" | "insufficient_maturity" | "insufficient_labels";
    candidate_version?: string; model_change_id?: string; binding_hash?: string;
    risk_classification?: { proposed_level?: "low" | "medium" | "high"; method?: string; manual_confirmation_required?: boolean };
    independent_validation?: { status?: "pending" | "approved" | "rejected"; risk_level?: "low" | "medium" | "high"; opinion?: string; reviewed_by_name?: string; reviewed_at?: string; attachments?: Array<{ name: string; reference: string; sha256: string }> };
    release_approval?: { status?: "pending" | "approved" | "blocked"; approved_by_name?: string; approved_at?: string; comment?: string };
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
  evidence_hash: string;
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

export type ApiErrorShape = {
  detail?: string | { code?: string; message?: string };
  error?: { code: string; message: string; trace_id: string; details: Record<string, unknown> };
};

export type DecisionResolvedAssetRef = {
  asset_type: "model" | "scorecard" | "pipeline" | "rule_set" | "rule";
  key?: string;
  code?: string;
  version: string | number;
  config_hash: string;
  runtime_config_hash?: string;
  source_scope: TenantAssetResolution["source_scope"] | "platform_execution_pin";
  asset_id: string;
  binding_id?: string;
  override_id?: string;
  resolution_hash: string;
};

export type TenantRolloutPolicy = {
  id: string;
  tenant_id: string;
  name: string;
  status: "draft" | "pending_review" | "scheduled" | "active" | "paused" | "rolled_back" | "completed" | "rejected";
  effective_status: string;
  champion: { model_key: string; model_version: string; pipeline_code: string; pipeline_version: string | null };
  challenger: { model_key: string; model_version: string; pipeline_code: string; pipeline_version: string | null };
  comparison: { run_id: string; evidence_hash: string; assets_hash: string };
  routing_key_field: "counterparty_id";
  traffic_basis_points: number;
  traffic_percent: number;
  observation_window_minutes: number;
  min_sample_size: number;
  thresholds: { max_challenger_failure_rate: number; max_latency_increase_ratio: number; max_score_psi: number; max_admission_distribution_shift: number };
  config_hash: string;
  assets_hash: string;
  starts_at: string;
  ends_at: string;
  change_reason: string;
  created_by: string;
  created_by_name: string;
  reviewed_by_name: string | null;
  review_comment: string | null;
  terminal_reason: string | null;
  incident_status: "not_applicable" | "open" | "acknowledged" | "resolution_pending" | "resolved";
  incident_evaluation_id: string | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  acknowledgement_note: string | null;
  resolution_requested_by: string | null;
  resolution_requested_at: string | null;
  resolution_note: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  row_version: number;
  created_at: string | null;
};

export type TenantRoutingDecision = {
  id: string; policy_id: string; channel: string; request_ref: string; routing_key_hash: string;
  bucket: number; selected_arm: "champion" | "challenger"; selected_assets_hash: string;
  status: "selected" | "completed" | "failed"; elapsed_ms: number | null; score: number | null;
  rating: string | null; admission: string | null; error_code: string | null; evidence_hash: string | null;
  created_at: string | null; completed_at: string | null;
};

export type TenantRolloutEvaluation = {
  id: string; policy_id: string; trigger_type: "manual" | "automatic" | "scheduler"; sample_count: number;
  evidence_level: "unlabeled_online"; metrics: {
    champion: { sample_count: number; failure_rate: number | null; average_latency_ms: number | null };
    challenger: { sample_count: number; failure_rate: number | null; average_latency_ms: number | null };
    latency_increase_ratio: number | null; score_psi: number | null; admission_distribution_shift: number | null;
    supervised_metrics_available: false; degraded_reason: string;
  };
  gate: { eligible: boolean; passed: boolean; summary: string; violations: Array<{ key: string; label: string; actual: number; threshold: number }> };
  action: "continue" | "insufficient_evidence" | "automatic_rollback";
  evidence_hash: string; created_at: string | null;
};

export type TenantOutcomeLabel = {
  id: string; tenant_id: string; policy_id: string; routing_decision_id: string; decision_execution_id: string | null;
  source: string; external_label_id: string; counterparty_id: string; label_definition: string;
  label_definition_id: string | null; label_definition_version: number | null; label_definition_hash: string | null;
  observed_event: boolean; observation_end: string; maturity_status: "mature" | "immature";
  loss_amount: number | null; exposure_amount: number | null; evidence_reference: string;
  link_status: "route_only" | "decision_execution"; selected_arm: "champion" | "challenger";
  model_key: string; model_version: string; predicted_score: number; risk_score: number;
  rating: string | null; admission: string | null; routing_evidence_hash: string;
  execution_evidence_hash: string | null; selected_assets_hash: string; evidence_hash: string;
  evidence_schema_version: "tenant-outcome-label-v3" | "tenant-outcome-label-v4" | null;
  import_batch_id: string | null; record_status: "active" | "superseded";
  supersedes_label_id: string | null; superseded_by_label_id: string | null;
  correction_reason: string | null; corrected_by: string | null; corrected_at: string | null;
  verification_status: "pending_verification" | "verified" | "rejected";
  verified_by_name: string | null; verified_at: string | null; verification_note: string | null;
  row_version: number; created_by_name: string; created_at: string | null; idempotent?: boolean;
};

export type TenantOutcomeImport = {
  id: string; tenant_id: string; policy_id: string; import_key: string; source: string; label_definition: string;
  label_definition_id: string | null; label_definition_version: number | null; label_definition_hash: string | null;
  expected_count: number; received_count: number; created_count: number; idempotent_count: number;
  rejected_count: number; corrected_count: number; payload_hash: string;
  results: Array<{ index: number; external_label_id: string; status: "created" | "idempotent" | "rejected"; label_id: string | null; error_code: string | null; error: string | null }>;
  status: "processing" | "completed" | "completed_with_exceptions" | "failed";
  evidence_hash: string; created_by_name: string; completed_at: string | null; created_at: string;
  idempotent?: boolean;
};

export type TenantMonitoringRun = {
  id: string; tenant_id: string; policy_id: string; run_key: string;
  model_key: string; model_version: string; observed_from: string; observed_to: string;
  dataset_id: string; evidence_level: "supervised" | "non_supervised";
  status: "completed" | "failed" | "cancelled"; label_definition_id: string | null;
  governance_status: "draft" | "pending_review" | "published" | "rejected" | "retracted";
  label_definition_version: number | null; label_definition_hash: string | null;
  label_watermark: Record<string, unknown>; monitoring: Record<string, unknown>;
  evidence_hash: string; submitted_by: string | null; submitted_by_name: string | null; submitted_at: string | null;
  reviewed_by: string | null; reviewed_by_name: string | null; reviewed_at: string | null; review_comment: string | null;
  retracted_by: string | null; retracted_by_name: string | null; retracted_at: string | null; retraction_reason: string | null;
  row_version: number; created_by_name: string; created_at: string | null;
  monitoring_gate?: {
    schema_version: "tenant-monitoring-gate-v1";
    status: "accepted" | "at_risk" | "blocked" | "evidence_stale";
    reasons: string[]; gate_hash: string;
    checks: Array<{ key: string; label: string; direction: "min" | "max"; value: number | null; threshold: number | null; testable: boolean; passed: boolean | null }>;
  };
  idempotent?: boolean;
};

export type TenantMonitoringDiffCase = {
  id: string; tenant_id: string; policy_id: string;
  base_run_id: string; against_run_id: string;
  base_evidence_hash: string; against_evidence_hash: string; diff_hash: string;
  comparison: Record<string, unknown>;
  status: "open" | "assigned" | "recomputing" | "pending_disposition" | "resolved" | "rejected";
  severity: "info" | "warning" | "critical"; reason: string;
  assigned_role: string; assigned_to: string | null; assigned_to_name: string | null;
  due_at: string; overdue: boolean;
  recompute_status: "not_started" | "running" | "completed" | "failed";
  recomputed_run_id: string | null; recomputed_diff_hash: string | null;
  recomputed_by: string | null; recomputed_by_name: string | null; recomputed_at: string | null;
  recompute_error: string | null;
  disposition: "accepted_change" | "data_issue" | "calculation_issue" | "model_drift" | "policy_threshold_change_required" | "superseded" | null;
  conclusion: string | null; resolved_by: string | null; resolved_by_name: string | null; resolved_at: string | null;
  row_version: number; created_by: string; created_by_name: string; created_at: string; updated_at: string;
  idempotent?: boolean;
};

export type MonitoringDiffSlaDashboard = {
  schema_version: "monitoring-diff-sla-dashboard-v1";
  tenant_id: string;
  template_key: string | null;
  as_of: string;
  counts: {
    open: number;
    normal: number;
    due_soon: number;
    overdue: number;
    escalated: number;
    unassigned: number;
    pending_disposition: number;
    critical: number;
  };
  by_policy: Array<{
    policy_id: string;
    policy_name: string;
    open_count: number;
    due_soon_count: number;
    overdue_count: number;
    escalated_count: number;
    unassigned_count: number;
  }>;
  by_model: Array<{
    model_key: string | null;
    model_version: string | null;
    open_count: number;
    due_soon_count: number;
    overdue_count: number;
    escalated_count: number;
    unassigned_count: number;
  }>;
  items: Array<TenantMonitoringDiffCase & {
    sla: {
      status: "normal" | "due_soon" | "overdue" | "escalated" | "stopped";
      remaining_hours: number;
      overdue_hours: number;
      due_soon_hours: number;
      escalation_after_hours: number;
    };
    model_key: string | null;
    model_version: string | null;
    policy_name: string;
    policy_status: string | null;
  }>;
};

export type TenantSupervisedEvaluation = {
  id: string; tenant_id: string; policy_id: string; evaluation_as_of: string;
  config: { min_mature_samples: number; min_events: number; min_non_events: number; min_reliable_samples_per_arm: number; high_risk_threshold: number; bootstrap_resamples: number; label_definition_id: string | null };
  coverage: {
    submitted_count: number; superseded_count: number; verified_count: number; rejected_count: number; pending_verification_count: number;
    mature_count: number; immature_count: number; event_count: number; non_event_count: number;
    execution_linked_count: number; route_only_count: number;
  };
  metrics: {
    champion: TenantSupervisedArmMetrics; challenger: TenantSupervisedArmMetrics;
    comparison: {
      auc_delta: number; ks_delta: number; event_rate_delta: number; loss_rate_delta: number | null;
      auc_difference_confidence_interval: TenantConfidenceInterval | null;
      ks_difference_confidence_interval: TenantConfidenceInterval | null;
      auc_difference_signal: "significant_challenger_better" | "significant_champion_better" | "directional_only" | "not_evaluable";
      ks_difference_signal: "significant_challenger_better" | "significant_champion_better" | "directional_only" | "not_evaluable";
      confidence_interval_overlap: { auc: boolean | null; ks: boolean | null };
      stability_summary: { arms: Record<"champion" | "challenger", TenantStabilityTrend | null>; direction_alignment: "aligned" | "divergent" };
      promotion_readiness: "ready" | "directional_only"; reliability_reasons: string[]; conclusion: string;
    } | null;
    supervised_metrics_available: boolean; degraded_reason: string | null; note: string;
  };
  evidence_level: "supervised" | "insufficient_maturity" | "insufficient_labels";
  label_definition_id: string | null; label_definition_version: number | null; label_definition_hash: string | null;
  tenant_monitoring_run_id: string | null; tenant_monitoring_evidence_hash: string | null;
  label_watermark: { label_count: number; label_ids: string[]; label_evidence_hashes: string[]; routing_evidence_hashes: string[]; policy_config_hash: string; policy_assets_hash: string };
  evidence_hash: string; status: "draft" | "pending_review" | "approved" | "rejected";
  governance_decision: "retain_champion" | "promote_candidate" | "reject_candidate" | "continue_observation" | null;
  submitted_by_name: string | null; submitted_at: string | null; reviewed_by_name: string | null;
  reviewed_at: string | null; review_comment: string | null; row_version: number;
  created_by_name: string; created_at: string;
  upgrade_decision: { id: string; status: "ready" | "draft_created"; model_change_id: string | null; candidate_version: string; evidence_hash: string; auto_submitted: false; auto_published: false; traffic_changed: false } | null;
};

export type TenantSupervisedVerificationReport = {
  schema_version: "tenant-supervised-verification-report-v1";
  report_type: "supervised_model_validation";
  generated_at: string;
  tenant_id: string;
  policy: { id: string; name: string; status: string; champion_model_key: string; champion_model_version: string; challenger_model_key: string; challenger_model_version: string; config_hash: string; assets_hash: string };
  evaluation: TenantSupervisedEvaluation;
  coverage: TenantSupervisedEvaluation["coverage"];
  metrics: TenantSupervisedEvaluation["metrics"];
  caveats: string[];
  governance_boundary: { model_change_created: boolean; auto_submitted: false; auto_published: false; traffic_changed: false };
  report_hash: string;
};

export type TenantSupervisedArmMetrics = {
  sample_count: number; event_count: number; non_event_count: number; event_rate: number | null;
  event_rate_confidence_interval: { lower: number; upper: number; confidence: number; method: string } | null;
  auc: number | null; ks: number | null; auc_confidence_interval: TenantConfidenceInterval | null; ks_confidence_interval: TenantConfidenceInterval | null;
  bootstrap_resamples: number; bootstrap_method: string | null; average_score: number | null; metrics_ready: boolean;
  observed_loss_count: number; total_loss_amount: number; total_exposure_amount: number; loss_rate: number | null;
  loss_rate_confidence_interval: { lower: number; upper: number; confidence: number; method: string } | null;
  average_loss_amount: number | null; statistical_reliability: "statistically_reliable" | "directional"; reliability_reasons: string[];
  confusion_matrix: { true_positive: number; false_positive: number; true_negative: number; false_negative: number; threshold: number };
  segments: Array<{ dimension: "rating" | "admission"; value: string; sample_count: number; event_count: number; event_rate: number; average_score: number }>;
  segment_stability: {
    dimensions: Record<"rating" | "admission", { group_count: number; min_group_sample_count: number; max_event_rate_gap: number | null; max_average_score_gap: number | null; reliability: "statistically_reliable" | "directional" }>;
    fairness_audit: "not_evaluable"; fairness_reason: string;
  };
  stability_trend: TenantStabilityTrend;
};

export type TenantConfidenceInterval = { lower: number; upper: number; confidence: number; method: string; resamples?: number; valid_resamples?: number; seed?: string };

export type TenantStabilityTrend = {
  granularity: "month"; periods: Array<{ period: string; sample_count: number; event_count: number; event_rate: number; auc: number | null; ks: number | null; metrics_ready: boolean }>;
  period_count: number; event_rate_delta: number | null; direction: "increasing" | "decreasing" | "stable" | "insufficient_periods";
};

export type TenantOutcomeLabelDefinition = {
  id: string; tenant_id: string; code: string; version: number; name: string; description: string;
  event_type: "default" | "delinquency" | "loss" | "recovery"; event_threshold: Record<string, unknown>;
  observation_window_days: number; maturity_grace_days: number;
  source_priorities: Array<{ source: string; priority: number }>;
  applicable_model_keys: string[]; require_loss_amount: boolean; require_exposure_amount: boolean;
  status: "draft" | "pending_review" | "published" | "rejected" | "retired"; is_active: boolean;
  config_hash: string; submitted_by_name: string | null; submitted_at: string | null;
  reviewed_by_name: string | null; reviewed_at: string | null; review_comment: string | null;
  row_version: number; created_by: string; created_by_name: string; created_at: string; updated_at: string;
};

export type TenantSupervisedUpgradeDecision = {
  id: string; tenant_id: string; policy_id: string; evaluation_id: string;
  decision: "promote_candidate"; status: "draft_created"; evidence_hash: string;
  model_change_id: string; candidate_version: string; model_change: ModelChangeRecord;
  auto_submitted: false; auto_published: false; traffic_changed: false; idempotent: boolean;
  created_by: string; created_by_name: string; created_at: string;
};

export type TenantRolloutScan = {
  id: string; run_key: string; tenant_id: string; trigger_type: "manual" | "scheduler";
  status: "no_due" | "completed" | "partial" | "failed"; scan_at: string;
  results: Array<{ tenant_id: string; policy_id: string; action: "activate" | "evaluate" | "close"; status: "completed" | "failed"; policy_status?: string; error_type?: string }>;
  evidence_hash: string; created_at: string;
};

export type DecisionExecution = {
  tenant_id: string;
  client_id: string;
  request_id: string;
  trace_id: string;
  status: "completed";
  idempotent: boolean;
  counterparty_id: string;
  decision: RatingResult & { counterparty_name?: string; final_admission?: "approve" | "manual_review" | "reject" };
  assets: {
    model: DecisionResolvedAssetRef & { key: string };
    scorecard?: DecisionResolvedAssetRef | null;
    pipeline: DecisionResolvedAssetRef & { code: string };
    rule_sets: Array<DecisionResolvedAssetRef & { code: string }>;
    rules: Array<DecisionResolvedAssetRef & { code: string }>;
    resolution_hash: string;
    degraded_reason?: string | null;
  };
  trace: {
    trace_id: string;
    status: string;
    started_at: string;
    completed_at: string;
    elapsed_ms: number;
    request: { tenant_id: string; client_id: string; request_id: string; source_system: string; scenario: string };
    input: { source: "platform_counterparty" | "inline_input"; counterparty_id: string; input_hash: string };
    assets: DecisionExecution["assets"];
    pipeline: { pipeline_code: string; pipeline_version: number; stages: Array<{ index: number; stage_type: string; rule_set_code?: string | null; output: Record<string, unknown> }> };
    output: { result_hash: string; rating?: string; access_strategy?: string; final_admission?: string };
  };
  evidence: {
    request_hash: string;
    input_hash: string;
    assets_hash: string;
    result_hash: string;
    trace_hash: string;
    evidence_hash: string;
  };
  elapsed_ms: number;
  created_by: string;
  created_by_name: string;
  created_at: string | null;
};

export type DecisionRequestPayload = {
  request_id: string;
  counterparty_id: string | null;
  input: Record<string, unknown> | null;
  assets: {
    model_key: string;
    model_version: string | null;
    pipeline_code: string | null;
    pipeline_version: number | string | null;
    rule_set_versions: Record<string, number | string>;
    rule_versions: Record<string, number | string>;
  };
  metadata: { source_system: string; scenario: string };
};

export type DecisionContract = {
  contract_version: string;
  tenant_id: string;
  endpoint: string;
  idempotency: string;
  version_policy: string;
  input_modes: string[];
  error_codes: string[];
  models: Array<{
    key: string;
    name: string;
    active_version: string | null;
    source_scope: TenantAssetResolution["source_scope"];
    resolution_hash: string;
    versions: Array<DecisionResolvedAssetRef & { version: string; name: string; runtime_config_hash: string; pipeline_code: string | null; scorecard?: DecisionResolvedAssetRef | null }>;
  }>;
  pipelines: Array<{
    code: string;
    name: string;
    version: number | string;
    is_active: boolean;
    config_hash: string;
    source_scope: TenantAssetResolution["source_scope"];
    asset_id: string;
    binding_id?: string;
    override_id?: string;
    resolution_hash: string;
    stages: Array<{ stage_type: string; rule_set_code?: string }>;
    rule_set_codes: string[];
  }>;
  unavailable_assets: Array<{ asset_type: string; asset_code: string; code: string; message: string }>;
};

export type DecisionSandboxPackage = {
  environment: "sandbox";
  production_credentials_exposed: false;
  notice: string;
  samples: Array<{
    counterparty_id: string;
    name: string;
    counterparty_type: "supplier" | "customer";
    current_rating?: string;
    input: Counterparty;
  }>;
  request_example: DecisionRequestPayload;
};

export type DecisionJob = {
  id: string;
  job_key: string;
  tenant_id: string;
  client_id: string;
  status: "queued" | "running" | "completed" | "completed_with_errors" | "failed";
  total_count: number;
  succeeded_count: number;
  failed_count: number;
  results: Array<{ index: number; request_id: string; counterparty_id: string; rating?: string; final_admission?: string; total_score?: number; trace_id: string; evidence_hash: string; idempotent: boolean }>;
  failures: Array<{ index: number; request_id: string; code: string; message: string; details: Record<string, unknown> }>;
  callback: { mode: "none" | "sandbox"; endpoint_url?: string; secret_reference?: string; max_attempts?: number; simulation_plan_hash?: string };
  evidence: { request_hash: string; result_hash: string | null; evidence_hash: string | null };
  idempotent: boolean;
  started_at: string | null;
  completed_at: string | null;
  created_by_name: string;
  row_version: number;
  created_at: string | null;
};

export type DecisionWebhook = {
  id: string;
  job_id: string;
  event_type: string;
  endpoint_url: string;
  secret_reference: string;
  payload: Record<string, unknown>;
  payload_hash: string;
  signature_timestamp: string;
  signature: string;
  signature_headers: Record<string, string>;
  attempt_count: number;
  max_attempts: number;
  status: "pending" | "retry_scheduled" | "delivered" | "dead_letter";
  last_status_code: number | null;
  last_error: string | null;
  next_attempt_at: string | null;
  history: Array<{ attempt: number; attempted_at: string; status_code: number; outcome: string; manual: boolean }>;
  manual_redelivery_count: number;
  delivered_at: string | null;
};

export type DecisionClientProfile = {
  tenant_id: string;
  tenant_name: string;
  deployment_mode: "saas" | "dedicated";
  client_id: string;
  client_name: string;
  key_id: string;
  key_fingerprint: string;
  status: "active" | "disabled";
  qps_limit: number;
  concurrent_job_limit: number;
  daily_item_quota: number;
  allowed_cidrs: string[];
  environment: "sandbox";
  production_secret_exposed: false;
  authentication: string;
  signature_algorithm: string;
  signature_input: string;
  signature_headers: string[];
  rotated_at: string | null;
  expires_at: string | null;
  last_used_at: string | null;
};

export type DecisionFieldMappingPayload = {
  source: Record<string, unknown>;
  mappings: Array<{ source_field: string; target_path: string; enum_mapping?: Record<string, string>; multiplier?: number; default_value?: unknown; required?: boolean }>;
};

export type DecisionFieldMappingResult = {
  status: "ready" | "blocked";
  normalized_input: Record<string, unknown>;
  coverage: { required_count: number; mapped_required_count: number; coverage_rate: number };
  missing_required: string[];
  transformations: Array<{ source_field: string; target_path: string; operations: string[]; output_value: unknown }>;
  errors: Array<{ source_field: string | null; target_path: string; code: string; message: string }>;
  preview_hash: string;
};

export type TaskAction = {
  page?: "documents" | "approvals" | "facilities" | "indicators";
  counterparty_id?: string;
  case_id?: string;
  correction_id?: string;
  facility_id?: string;
  condition_id?: string;
  monitoring_event_id?: string;
  run_id?: string | null;
  plan_id?: string;
};

export type NotificationRecord = {
  id: string;
  case_id: string | null;
  counterparty_id: string | null;
  recipient_role: string;
  recipient_subject: string | null;
  category: string;
  level: "due_soon" | "overdue" | "escalated" | "opened" | "pending_revalidation" | "closed" | "reminder" | "assignment" | "extension" | "task_created" | "resubmitted" | "reopened" | "completed" | "resumed" | "supervisor_reminder" | "lease_due_soon" | "lease_expired" | "policy_blocked" | "scan_failed";
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
  task_type: "approval" | "correction" | "facility_control" | "control_extension" | "scorecard_monitoring";
  title: string;
  description: string;
  counterparty_id: string | null;
  counterparty_name: string;
  case_id: string | null;
  stage: string;
  stage_label: string;
  correction_id: string | null;
  document_type: string | null;
  facility_id?: string | null;
  condition_id?: string | null;
  extension_id?: string | null;
  monitoring_event_id?: string | null;
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
    scorecard_monitoring: number;
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
  post_credit_sla: { active_facilities: number; pending_controls: number; normal: number; due_soon: number; overdue: number; escalated: number; pending_extensions: number };
  unread_notifications: { total: number; info: number; warning: number; critical: number };
  last_scan: { run_id: string; run_at: string | null; actor: string; active_cases_scanned: number; active_corrections_scanned: number; notifications_created: number; workflow_notifications_created: number; expired_assignments_released: number; active_facilities_scanned: number; facility_alerts_opened: number; control_conditions_scanned: number; control_conditions_escalated: number; control_notifications_created: number } | null;
  stage_distribution: Array<{ stage: string; label: string; count: number }>;
};

export type SlaScanResult = {
  run_id: string;
  run_key: string | null;
  run_at: string;
  trigger_type: "manual" | "scheduler" | "retry";
  status: "completed";
  deduplicated: boolean;
  active_cases_scanned: number;
  due_soon_cases: number;
  overdue_cases: number;
  escalated_cases: number;
  active_corrections_scanned: number;
  due_soon_corrections: number;
  overdue_corrections: number;
  escalated_corrections: number;
  workflow_notifications_created: number;
  notifications_created: number;
  expired_assignments_released: number;
  active_facilities_scanned: number;
  facilities_expired: number;
  facility_alerts_opened: number;
  control_conditions_scanned: number;
  control_alerts_opened: number;
  control_conditions_escalated: number;
  control_notifications_created: number;
  scorecard_monitoring_events_scanned: number;
  scorecard_monitoring_due_soon: number;
  scorecard_monitoring_overdue: number;
  scorecard_monitoring_escalated: number;
  scorecard_monitoring_notifications_created: number;
  failure_notifications_resolved: number;
  execution_id: string;
  execution_tracked: boolean;
};

export type SlaScanRetryResult = {
  run_id: string;
  run_key: string;
  run_at: string;
  trigger_type: "scheduler" | "retry";
  status: "completed" | "failed" | "aborted";
  deduplicated: boolean;
  error_type?: string;
  error_message?: string;
  execution_id: string;
  execution_tracked: boolean;
  retry: {
    run_key: string;
    retry_number: number;
    reason: string;
    requested_at: string;
    status: "completed" | "failed";
    actor: string;
  };
};

export type SlaScanExecution = {
  execution_id: string;
  started_at: string;
  finished_at: string | null;
  elapsed_seconds: number;
  actor: string;
  trigger_type: "manual" | "scheduler" | "retry" | "legacy";
  run_key: string | null;
  status: "running" | "completed" | "failed" | "aborted" | "timed_out" | "force_released" | "late_completed" | "late_failed" | "late_aborted";
  result_run_id: string | null;
  deduplicated: boolean;
  error_type: string | null;
  terminal_actor: string | null;
  termination_reason: string | null;
  released_by: string | null;
  lease_lost_at: string | null;
  event_count: number;
  evidence_integrity: {
    state: "verified" | "broken";
    chain_complete: boolean;
    hashes_valid: boolean;
    checked_event_count: number;
    invalid_hash_count: number;
    issue_type: "missing_root" | "multiple_roots" | "broken_link" | "hash_mismatch" | null;
    message: string;
    terminal_hash: string | null;
  };
  evidence_events: Array<{
    event_type: string;
    actor: string;
    occurred_at: string;
    reason: string | null;
    error_type: string | null;
    event_hash: string;
    previous_hash: string;
    hash_valid: boolean;
    link_valid: boolean;
  }>;
};

export type SlaScanRun = {
  event_id: string;
  run_id: string;
  run_key: string | null;
  run_at: string;
  actor: string;
  trigger_type: "manual" | "scheduler" | "retry" | "legacy";
  status: "completed" | "failed";
  error_type: string | null;
  error_message: string | null;
  active_cases_scanned: number;
  active_corrections_scanned: number;
  active_facilities_scanned: number;
  control_conditions_scanned: number;
  notifications_created: number;
  workflow_notifications_created: number;
  facility_alerts_opened: number;
  control_alerts_opened: number;
  alerts_opened: number;
  escalated_cases: number;
  escalated_corrections: number;
  control_conditions_escalated: number;
  escalations_triggered: number;
  facilities_expired: number;
  expired_assignments_released: number;
  failure_notifications_resolved: number;
  risk_actions_created: number;
  notification_delta: number;
  alert_delta: number;
  escalation_delta: number;
  risk_action_delta: number;
  risk_increased: boolean;
  recovered: boolean;
  can_retry: boolean;
  retry_count: number;
  last_retry_at: string | null;
  last_retry_actor: string | null;
  last_retry_status: "requested" | "completed" | "failed" | null;
  last_retry_reason: string | null;
};

export type SlaScanHistory = {
  generated_at: string;
  health: "healthy" | "stale" | "never" | "blocked";
  expected_cadence_minutes: number;
  stale_after_minutes: number;
  execution_timeout_minutes: number;
  execution_lease_expiry_minutes: number;
  execution_heartbeat_interval_seconds: number;
  execution_summary: {
    returned_executions: number;
    running: number;
    timed_out: number;
    force_released: number;
    aborted: number;
    failed: number;
    evidence_verified: number;
    evidence_broken: number;
    evidence_events_checked: number;
    last_started_at: string | null;
  };
  execution_lease: {
    status: "idle" | "active" | "overdue" | "expired";
    execution_id: string | null;
    run_key: string | null;
    actor: string | null;
    trigger_type: "manual" | "scheduler" | "retry" | "legacy" | null;
    acquired_at: string | null;
    expires_at: string | null;
    remaining_seconds: number;
    warning_after_seconds: number;
    last_heartbeat_at: string | null;
    heartbeat_count: number;
    heartbeat_health: {
      state: "idle" | "healthy" | "delayed" | "lost";
      age_seconds: number | null;
      missed_heartbeats: number;
      next_expected_at: string | null;
      delayed_after_seconds: number;
      lost_after_seconds: number;
    };
  };
  executions: SlaScanExecution[];
  scheduler_health: {
    state: "healthy" | "stale" | "never" | "blocked";
    last_run_at: string | null;
    last_status: "completed" | "failed" | null;
    recovered: boolean;
    error_type: string | null;
    error_message: string | null;
    next_expected_run_at: string | null;
    minutes_since_last_run: number | null;
    missed_intervals: number;
  };
  summary: {
    returned_runs: number;
    scheduler_runs: number;
    manual_runs: number;
    retry_runs: number;
    legacy_runs: number;
    failed_runs: number;
    last_run_at: string | null;
    minutes_since_last_run: number | null;
    missed_intervals: number;
    short_interval_runs: number;
    runs_with_new_risk: number;
    total_notifications: number;
    total_alerts: number;
    total_escalations: number;
  };
  runs: SlaScanRun[];
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
  escalation_role: "risk_manager" | "approver" | "operations" | null;
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

export type TenantAssetType = "indicator" | "scorecard" | "model" | "rule" | "rule_set" | "pipeline";

export type TenantAssetBinding = {
  id: string;
  tenant_id: string;
  asset_type: TenantAssetType;
  asset_code: string;
  binding_mode: "inherit_active" | "pinned";
  pinned_version: string | null;
  allow_tenant_override: boolean;
  status: "active" | "suspended";
  resolved_scope: string | null;
  resolved_asset_id: string | null;
  resolved_version: string | null;
  resolved_config_hash: string | null;
  change_reason: string;
  created_by: string;
  created_by_name: string;
  updated_by: string;
  updated_by_name: string;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type TenantAssetOverride = {
  id: string;
  tenant_id: string;
  asset_type: TenantAssetType;
  asset_code: string;
  version: number;
  base_asset_id: string;
  base_version: string;
  base_config_hash: string;
  config: Record<string, unknown>;
  config_hash: string;
  status: "draft" | "pending_review" | "published" | "rejected" | "retired";
  is_active: boolean;
  change_reason: string;
  created_by: string;
  created_by_name: string;
  submitted_at: string | null;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  published_at: string | null;
  row_version: number;
  created_at: string | null;
  updated_at: string | null;
};

export type TenantAssetResolution = {
  tenant_id: string;
  asset_type: TenantAssetType;
  asset_code: string;
  asset_name: string;
  source_scope: "tenant_override" | "platform_pinned" | "platform_inherited" | "implicit_platform_default";
  asset_id: string;
  version: string;
  config_hash: string;
  config: Record<string, unknown>;
  binding_id: string | null;
  override_id: string | null;
  resolution_hash: string;
};

export type TenantAssetCatalogItem = {
  asset_type: TenantAssetType;
  asset_code: string;
  asset_name: string;
  available_versions: string[];
  active_platform_version: string | null;
  binding: TenantAssetBinding | null;
  overrides: TenantAssetOverride[];
  resolution: TenantAssetResolution | null;
  resolution_error: { code: string; message: string } | null;
};

export type TenantAssetCatalog = {
  tenant_id: string;
  entitlement?: { mode: "governed" | "blocked" | "implicit_compatibility"; entitlement_id: string | null; package_code: string | null; package_version: number | null };
  summary: {
    asset_count: number;
    explicit_binding_count: number;
    pinned_count: number;
    suspended_count: number;
    active_override_count: number;
    pending_review_count: number;
    implicit_default_count: number;
  };
  items: TenantAssetCatalogItem[];
};

export type TenantSummary = {
  id: string; name: string; deployment_mode: "saas" | "dedicated"; status: "active" | "suspended" | "disabled";
  data_region: string; membership_count: number; api_client_count: number; row_version: number;
  created_at: string | null; updated_at: string | null;
};

export type ProductPackageAsset = {
  asset_type: TenantAssetType; asset_code: string; asset_name?: string;
  binding_mode: "inherit_active" | "pinned"; pinned_version: string | null; allow_tenant_override: boolean;
};

export type ProductPackageQuotas = {
  qps_limit: number; concurrent_job_limit: number; daily_item_quota: number; max_asset_bindings: number;
};

export type ProductPackage = {
  id: string; code: string; version: number; name: string; description: string;
  status: "draft" | "pending_review" | "published" | "rejected" | "retired"; is_active: boolean;
  environment_scopes: Array<"sandbox" | "production">; assets: ProductPackageAsset[];
  quotas: ProductPackageQuotas; expiry_policy: "block"; config_hash: string;
  change_reason: string; created_by: string; created_by_name: string; submitted_at: string | null;
  reviewed_by: string | null; reviewed_by_name: string | null; reviewed_at: string | null;
  review_comment: string | null; published_at: string | null; row_version: number;
  created_at: string | null; updated_at: string | null;
};

export type TenantEntitlement = {
  id: string; tenant_id: string; product_package_id: string; package_code: string; package_version: number;
  package_config_hash: string; package_snapshot: Record<string, unknown>; effective_quotas: ProductPackageQuotas;
  initialized_assets: TenantAssetBinding[]; activation_hash: string | null;
  status: "draft" | "pending_review" | "scheduled" | "active" | "suspended" | "expired" | "terminated";
  effective_status: string; starts_at: string; expires_at: string; change_reason: string;
  created_by: string; created_by_name: string; submitted_at: string | null; reviewed_by: string | null;
  reviewed_by_name: string | null; reviewed_at: string | null; review_comment: string | null;
  activated_at: string | null; suspended_at: string | null; expired_at: string | null; terminated_at: string | null;
  row_version: number; created_at: string | null; updated_at: string | null;
};

export type EntitlementPreview = {
  tenant_id: string; package_code: string; package_version: number; package_config_hash: string;
  effective_quotas: ProductPackageQuotas; assets_to_create: ProductPackageAsset[];
  assets_to_update: ProductPackageAsset[]; assets_to_suspend: ProductPackageAsset[];
  clients_to_update: number; warnings: string[]; preview_hash: string;
};

export type EntitlementLifecycleResult = {
  entitlement_id: string; tenant_id: string; package_code: string; package_version: number;
  action: "activate" | "expire" | "supersede"; status: "completed" | "failed"; error: string | null;
};

export type EntitlementLifecycleRun = {
  id: string; run_key: string; trigger_type: "scheduler" | "manual" | "retry";
  status: "no_due" | "completed" | "partial" | "failed"; scan_at: string;
  activated_count: number; expired_count: number; superseded_count: number; failed_count: number;
  results: EntitlementLifecycleResult[]; evidence_hash: string; error_summary: string | null;
  incident_status: "not_applicable" | "open" | "acknowledged" | "resolved";
  acknowledged_by: string | null; acknowledged_by_name: string | null; acknowledged_at: string | null;
  acknowledgement_note: string | null; resolved_by: string | null; resolved_by_name: string | null;
  resolved_at: string | null; resolution_note: string | null; retry_of_run_id: string | null;
  resolved_by_run_id: string | null; actor_subject: string; actor_name: string;
  started_at: string; completed_at: string | null; row_version: number; created_at: string | null;
};

export type EntitlementLifecycleStatus = {
  health: "healthy" | "incident" | "stale" | "not_started"; observed_at: string;
  scan_interval_minutes: number; next_scan_at: string; due_activations: number;
  due_expirations: number; open_incidents: number; latest_scheduler_run: EntitlementLifecycleRun | null;
};

export type TenantUsageDailyRecord = {
  id: string; tenant_id: string; usage_date: string; usage: Record<string, number | null>;
  source_watermark: Record<string, unknown>; evidence_hash: string; computed_at: string | null;
};

export type TenantUsageStatement = {
  id: string; tenant_id: string; billing_month: string; statement_version: number; status: "generated";
  statement: Record<string, unknown>; statement_hash: string; generated_by: string; generated_by_name: string; created_at: string | null;
};

export type TenantUsageSummary = {
  tenant_id: string; billing_month: string; daily_records: TenantUsageDailyRecord[];
  totals: Record<string, number>; quota_snapshot: Record<string, string | number | null>;
  metering_scope: { source: string; billable_dimensions: string[]; enforcement_scope: string; asset_scope: string };
  statements: TenantUsageStatement[];
};

export type TenantNotificationChannel = {
  id: string; tenant_id: string; name: string; channel_type: "webhook";
  delivery_mode: "sandbox" | "live"; endpoint_url: string; secret_reference: string;
  subscribed_categories: string[]; recipient_roles: string[];
  minimum_severity: "info" | "warning" | "critical"; max_attempts: number;
  timeout_seconds: number; require_receipt: boolean; sandbox_status_sequence: number[];
  status: "active" | "disabled"; created_by: string; created_by_name: string;
  preflight_status: "not_required" | "required" | "passed" | "failed";
  last_test_delivery_id: string | null; last_tested_at: string | null;
  row_version: number; created_at: string | null; updated_at: string | null;
};

export type TenantNotificationChannelPayload = Omit<TenantNotificationChannel,
  "id" | "tenant_id" | "channel_type" | "created_by" | "created_by_name" | "row_version" | "preflight_status" | "last_test_delivery_id" | "last_tested_at" | "created_at" | "updated_at"
>;

export type TenantNotificationDeliveryStatus = "pending" | "retry_scheduled" | "delivered" | "dead_letter" | "cancelled";

export type TenantNotificationDelivery = {
  id: string; tenant_id: string; channel_id: string; notification_id: string;
  idempotency_key: string; event_type: string; endpoint_url: string;
  delivery_mode: "sandbox" | "live"; secret_reference: string;
  payload: { notification?: { title?: string; category?: string; severity?: string; recipient_role?: string }; [key: string]: unknown };
  payload_hash: string; channel_config_hash: string; signature_timestamp: string; signature: string;
  signature_headers: Record<string, string>; attempt_count: number; max_attempts: number;
  status: TenantNotificationDeliveryStatus; last_status_code: number | null; last_error: string | null;
  next_attempt_at: string | null;
  history: Array<{ attempt: number; attempted_at: string; status_code: number | null; outcome: string; manual: boolean; receipt_verified: boolean; error: string | null }>;
  receipt: { verified?: boolean; event_id?: string | null; acknowledged_at?: string | null; mode?: string; response_hash?: string };
  manual_redelivery_count: number; delivered_at: string | null; row_version: number;
  created_at: string | null; updated_at: string | null;
};

export type TenantNotificationDeliveryLedger = {
  counts: Record<TenantNotificationDeliveryStatus, number>;
  items: TenantNotificationDelivery[];
};

export type TenantNotificationDispatchResult = {
  scanned_at: string; channels: number; notifications_scanned: number;
  deliveries_created: number; attempted: number; delivered: number;
  retry_scheduled: number; dead_letter: number;
};

export type TenantNotificationChannelTestResult = {
  channel_id: string; passed: boolean; channel_config_hash: string;
  delivery: TenantNotificationDelivery;
};

export type NotificationDeliveryOperations = {
  schema_version: "notification-delivery-operations-v1"; tenant_id: string;
  observed_at: string; window_hours: number;
  health: "healthy" | "degraded" | "incident" | "not_configured";
  sla: { dead_letter_minutes: number };
  channels: {
    total: number; active: number;
    items: Array<{
      channel_id: string; name: string; status: "active" | "disabled"; delivery_mode: "sandbox" | "live";
      preflight_status: TenantNotificationChannel["preflight_status"]; attempted: number; delivered: number;
      dead_letter: number; retry_scheduled: number; delivery_rate: number | null;
      latest_success_at: string | null; latest_error: string | null;
    }>;
  };
  deliveries: {
    created: number; attempted: number; delivered: number; pending: number; retry_scheduled: number;
    retry_due: number; dead_letter: number; dead_letter_sla_breaches: number; cancelled: number;
    delivery_rate: number | null; p95_end_to_end_latency_ms: number | null; oldest_open_seconds: number;
  };
  last_dispatch_at: string | null;
  recent_failures: Array<{
    delivery_id: string; channel_id: string; status: TenantNotificationDeliveryStatus;
    status_code: number | null; error: string; attempt_count: number; occurred_at: string;
  }>;
};
