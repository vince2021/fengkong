from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.authority_policy_repository import AuthorityPolicyRepository
from backend.database import get_db_session
from backend.repository import ApprovalCaseRepository, AuditRepository, CreditFacilityRepository, CreditReportRepository, DecisionGovernanceRepository, DemoRepository, DocumentRepository, EnterpriseDataRepository, EnterpriseIndicatorObservationRepository, ModelGovernanceRepository, ModelMonitoringRepository, NotificationRepository, PortfolioRatingBatchRepository, RatingRunRepository
from backend.storage import ObjectStorage, build_object_storage


demo_repository = DemoRepository()
object_storage = build_object_storage()


def get_demo_repository() -> DemoRepository:
    return demo_repository


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
