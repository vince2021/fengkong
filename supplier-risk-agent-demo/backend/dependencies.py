from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.authority_policy_repository import AuthorityPolicyRepository
from backend.database import get_db_session
from backend.repository import ApprovalCaseRepository, AuditRepository, CreditFacilityRepository, CreditReportRepository, DecisionGovernanceRepository, DecisionPipelineRepository, DemoRepository, DocumentRepository, EnterpriseDataRepository, EnterpriseIndicatorObservationRepository, ModelGovernanceRepository, ModelMonitoringRepository, NotificationRepository, PortfolioRatingBatchRepository, RatingRunRepository, RuleCenterGovernanceRepository, RuleCenterReleasePackageRepository, RuleCenterReplayComparisonRepository, RuleCenterReplayDatasetRepository, RuleDefinitionRepository, RuleSetDefinitionRepository
from backend.storage import ObjectStorage, build_object_storage
from backend.supervised_validation_attachment_repository import SupervisedValidationAttachmentRepository
from backend.model_validation_issuance_repository import ModelValidationIssuanceRepository
from backend.model_risk_policy_repository import ModelRiskPolicyRepository
from backend.scorecard_repository import ScorecardRepository
from backend.credit_calibration_repository import CreditCalibrationRepository
from backend.counterparty_import_repository import CounterpartyImportRepository
from backend.counterparty_mapping_repository import CounterpartyImportMappingRepository
from backend.counterparty_repository import CounterpartyRepository
from backend.tenant_admin_repository import TenantAdminRepository
from backend.product_package_repository import ProductPackageRepository
from backend.governance_evidence import CounterpartyGovernanceEvidenceRepository
from backend.tenant_asset_repository import TenantAssetRepository
from backend.tenant_runtime_assets import TenantRuntimeAssetResolver
from backend.tenant_rollout_repository import TenantRolloutRepository
from backend.tenant_outcome_repository import TenantOutcomeRepository
from backend.tenant_usage_repository import TenantUsageRepository
from backend.notification_delivery_repository import NotificationDeliveryRepository


demo_repository = DemoRepository()
object_storage = build_object_storage()


def get_demo_repository() -> DemoRepository:
    return demo_repository


def get_tenant_admin_repository(session: Session = Depends(get_db_session)) -> TenantAdminRepository:
    return TenantAdminRepository(session)


def get_product_package_repository(session: Session = Depends(get_db_session)) -> ProductPackageRepository:
    return ProductPackageRepository(session)


def get_tenant_usage_repository(session: Session = Depends(get_db_session)) -> TenantUsageRepository:
    return TenantUsageRepository(session)


def get_tenant_asset_repository(session: Session = Depends(get_db_session)) -> TenantAssetRepository:
    return TenantAssetRepository(session)


def get_tenant_runtime_asset_resolver(
    session: Session = Depends(get_db_session),
    repository: DemoRepository = Depends(get_demo_repository),
) -> TenantRuntimeAssetResolver:
    return TenantRuntimeAssetResolver(TenantAssetRepository(session), repository)


def get_tenant_rollout_repository(
    session: Session = Depends(get_db_session),
    repository: DemoRepository = Depends(get_demo_repository),
) -> TenantRolloutRepository:
    return TenantRolloutRepository(session, repository)


def get_tenant_outcome_repository(session: Session = Depends(get_db_session)) -> TenantOutcomeRepository:
    return TenantOutcomeRepository(session)


def get_counterparty_repository(session: Session = Depends(get_db_session)) -> CounterpartyRepository:
    return CounterpartyRepository(session)


def get_counterparty_governance_evidence_repository(
    session: Session = Depends(get_db_session),
) -> CounterpartyGovernanceEvidenceRepository:
    return CounterpartyGovernanceEvidenceRepository(session)


def get_counterparty_import_repository(session: Session = Depends(get_db_session)) -> CounterpartyImportRepository:
    return CounterpartyImportRepository(session)


def get_counterparty_mapping_repository(session: Session = Depends(get_db_session)) -> CounterpartyImportMappingRepository:
    return CounterpartyImportMappingRepository(session)


def get_approval_repository(session: Session = Depends(get_db_session)) -> ApprovalCaseRepository:
    return ApprovalCaseRepository(session)


def get_authority_policy_repository(session: Session = Depends(get_db_session)) -> AuthorityPolicyRepository:
    return AuthorityPolicyRepository(session)


def get_rating_run_repository(session: Session = Depends(get_db_session)) -> RatingRunRepository:
    return RatingRunRepository(session)


def get_portfolio_rating_batch_repository(session: Session = Depends(get_db_session)) -> PortfolioRatingBatchRepository:
    return PortfolioRatingBatchRepository(session)


def get_audit_repository(session: Session = Depends(get_db_session)) -> AuditRepository:
    return AuditRepository(session)


def get_document_repository(session: Session = Depends(get_db_session)) -> DocumentRepository:
    return DocumentRepository(session)


def get_notification_repository(session: Session = Depends(get_db_session)) -> NotificationRepository:
    return NotificationRepository(session)


def get_notification_delivery_repository(session: Session = Depends(get_db_session)) -> NotificationDeliveryRepository:
    return NotificationDeliveryRepository(session)


def get_model_governance_repository(session: Session = Depends(get_db_session)) -> ModelGovernanceRepository:
    return ModelGovernanceRepository(session)


def get_model_monitoring_repository(session: Session = Depends(get_db_session)) -> ModelMonitoringRepository:
    return ModelMonitoringRepository(session)


def get_credit_facility_repository(session: Session = Depends(get_db_session)) -> CreditFacilityRepository:
    return CreditFacilityRepository(session)


def get_credit_report_repository(session: Session = Depends(get_db_session)) -> CreditReportRepository:
    return CreditReportRepository(session)


def get_decision_governance_repository(session: Session = Depends(get_db_session)) -> DecisionGovernanceRepository:
    return DecisionGovernanceRepository(session)


def get_enterprise_data_repository(session: Session = Depends(get_db_session)) -> EnterpriseDataRepository:
    return EnterpriseDataRepository(session)


def get_enterprise_indicator_observation_repository(session: Session = Depends(get_db_session)) -> EnterpriseIndicatorObservationRepository:
    return EnterpriseIndicatorObservationRepository(session)


def get_object_storage() -> ObjectStorage:
    return object_storage


def get_supervised_validation_attachment_repository(
    session: Session = Depends(get_db_session),
    storage: ObjectStorage = Depends(get_object_storage),
) -> SupervisedValidationAttachmentRepository:
    return SupervisedValidationAttachmentRepository(session, storage)


def get_model_validation_issuance_repository(
    session: Session = Depends(get_db_session),
    storage: ObjectStorage = Depends(get_object_storage),
) -> ModelValidationIssuanceRepository:
    return ModelValidationIssuanceRepository(session, storage)


def get_model_risk_policy_repository(
    session: Session = Depends(get_db_session),
) -> ModelRiskPolicyRepository:
    return ModelRiskPolicyRepository(session)


def get_rule_definition_repository(
    session: Session = Depends(get_db_session),
) -> RuleDefinitionRepository:
    return RuleDefinitionRepository(session)


def get_rule_set_definition_repository(
    session: Session = Depends(get_db_session),
) -> RuleSetDefinitionRepository:
    return RuleSetDefinitionRepository(session)


def get_decision_pipeline_repository(
    session: Session = Depends(get_db_session),
) -> DecisionPipelineRepository:
    return DecisionPipelineRepository(session)


def get_rule_center_governance_repository(
    session: Session = Depends(get_db_session),
) -> RuleCenterGovernanceRepository:
    return RuleCenterGovernanceRepository(session)


def get_rule_center_release_package_repository(
    session: Session = Depends(get_db_session),
) -> RuleCenterReleasePackageRepository:
    return RuleCenterReleasePackageRepository(session)


def get_rule_center_replay_dataset_repository(
    session: Session = Depends(get_db_session),
) -> RuleCenterReplayDatasetRepository:
    return RuleCenterReplayDatasetRepository(session)


def get_rule_center_replay_comparison_repository(
    session: Session = Depends(get_db_session),
) -> RuleCenterReplayComparisonRepository:
    return RuleCenterReplayComparisonRepository(session)


def get_scorecard_repository(
    session: Session = Depends(get_db_session),
) -> ScorecardRepository:
    return ScorecardRepository(session)


def get_credit_calibration_repository(
    session: Session = Depends(get_db_session),
) -> CreditCalibrationRepository:
    return CreditCalibrationRepository(session)
