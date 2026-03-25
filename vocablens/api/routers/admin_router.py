from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, Depends, Header, Query
from fastapi import HTTPException

from vocablens.api.dependencies import (
    get_admin_token,
    get_analytics_service,
    get_daily_loop_health_signal_service,
    get_decision_trace_service,
    get_experiment_registry_service,
    get_experiment_results_service,
    get_learning_health_signal_service,
    get_lifecycle_health_signal_service,
    get_monetization_health_signal_service,
    get_notification_policy_registry_service,
    get_session_health_signal_service,
    get_subscription_service,
)
from vocablens.api.schemas import (
    ConversionMetricsResponse,
    DailyLoopHealthDashboardResponse,
    DailyLoopOperatorReportResponse,
    DecisionTraceDetailResponse,
    DecisionTraceListResponse,
    ExperimentRegistryAuditResponse,
    ExperimentRegistryDetailResponse,
    ExperimentHealthDashboardResponse,
    ExperimentRegistryListResponse,
    ExperimentOperatorReportResponse,
    ExperimentRegistryUpsertRequest,
    ExperimentResultsResponse,
    LearningHealthDashboardResponse,
    LifecycleDiagnosticsResponse,
    LifecycleHealthDashboardResponse,
    LifecycleOperatorReportResponse,
    MonetizationDiagnosticsResponse,
    MonetizationHealthDashboardResponse,
    MonetizationOperatorReportResponse,
    NotificationOperatorReportResponse,
    NotificationPolicyAuditResponse,
    NotificationPolicyDetailResponse,
    NotificationPolicyHealthDashboardResponse,
    NotificationPolicyListResponse,
    NotificationPolicyOperatorReportResponse,
    NotificationPolicyUpsertRequest,
    OnboardingDiagnosticsResponse,
    RetentionAnalyticsResponse,
    SessionHealthDashboardResponse,
    UsageAnalyticsResponse,
)
from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.services.analytics_service import AnalyticsService
from vocablens.services.decision_trace_service import DecisionTraceService
from vocablens.services.experiment_registry_service import (
    ExperimentRegistryService,
    ExperimentRegistryUpsert,
    ExperimentRegistryVariantInput,
)
from vocablens.services.experiment_results_service import ExperimentResultsService
from vocablens.services.experiment_health_signal_service import ExperimentHealthSignalService
from vocablens.services.learning_health_signal_service import LearningHealthSignalService
from vocablens.services.daily_loop_health_signal_service import DailyLoopHealthSignalService
from vocablens.services.lifecycle_health_signal_service import LifecycleHealthSignalService
from vocablens.services.notification_policy_registry_service import (
    NotificationPolicyRegistryService,
    NotificationPolicyRegistryUpsert,
)
from vocablens.services.monetization_health_signal_service import MonetizationHealthSignalService
from vocablens.services.session_health_signal_service import SessionHealthSignalService
from vocablens.services.subscription_service import SubscriptionService


def _response_payload(value):
    if is_dataclass(value):
        return asdict(value)
    return value


def create_admin_router() -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["Admin"])

    @router.get("/reports/conversions", response_model=ConversionMetricsResponse)
    async def conversion_metrics(
        _: str = Depends(get_admin_token),
        service: SubscriptionService = Depends(get_subscription_service),
    ):
        metrics = await service.conversion_metrics()
        return {
            "data": {
                "conversion_metrics": metrics.counts_by_event if hasattr(metrics, "counts_by_event") else metrics,
            },
            "meta": {"source": "admin.conversions"},
        }

    @router.get("/analytics/retention", response_model=RetentionAnalyticsResponse)
    async def retention_analytics(
        _: str = Depends(get_admin_token),
        service: AnalyticsService = Depends(get_analytics_service),
    ):
        metrics = await service.retention_report()
        return {
            "data": {"retention": _response_payload(metrics)},
            "meta": {"source": "admin.analytics.retention"},
        }

    @router.get("/analytics/usage", response_model=UsageAnalyticsResponse)
    async def usage_analytics(
        _: str = Depends(get_admin_token),
        service: AnalyticsService = Depends(get_analytics_service),
    ):
        metrics = await service.usage_report()
        return {
            "data": {"usage": _response_payload(metrics)},
            "meta": {"source": "admin.analytics.usage"},
        }

    @router.get("/experiments/results", response_model=ExperimentResultsResponse)
    async def experiment_results(
        experiment_key: str | None = Query(default=None),
        _: str = Depends(get_admin_token),
        service: ExperimentResultsService = Depends(get_experiment_results_service),
    ):
        results = await service.results(experiment_key)
        return {
            "data": {"experiment_results": _response_payload(results)},
            "meta": {"source": "admin.experiments.results"},
        }

    @router.get("/experiments/registry", response_model=ExperimentRegistryListResponse)
    async def experiment_registry_list(
        _: str = Depends(get_admin_token),
        service: ExperimentRegistryService = Depends(get_experiment_registry_service),
    ):
        registries = await service.list_registries()
        return {
            "data": registries,
            "meta": {"source": "admin.experiments.registry.list"},
        }

    @router.get("/experiments/registry/{experiment_key}", response_model=ExperimentRegistryDetailResponse)
    async def experiment_registry_detail(
        experiment_key: str,
        _: str = Depends(get_admin_token),
        service: ExperimentRegistryService = Depends(get_experiment_registry_service),
    ):
        try:
            detail = await service.get_registry(experiment_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.experiments.registry.detail",
                "experiment_key": experiment_key,
            },
        }

    @router.put("/experiments/registry/{experiment_key}", response_model=ExperimentRegistryDetailResponse)
    async def experiment_registry_upsert(
        experiment_key: str,
        request: ExperimentRegistryUpsertRequest,
        admin_actor: str | None = Header(default=None, alias="X-Admin-Actor"),
        _: str = Depends(get_admin_token),
        service: ExperimentRegistryService = Depends(get_experiment_registry_service),
    ):
        try:
            detail = await service.upsert_registry(
                experiment_key=experiment_key,
                command=ExperimentRegistryUpsert(
                    status=request.status,
                    rollout_percentage=request.rollout_percentage,
                    holdout_percentage=request.holdout_percentage,
                    is_killed=request.is_killed,
                    baseline_variant=request.baseline_variant,
                    description=request.description,
                    variants=tuple(
                        ExperimentRegistryVariantInput(name=item.name, weight=item.weight)
                        for item in request.variants
                    ),
                    eligibility={
                        key: tuple(values)
                        for key, values in request.eligibility.items()
                    },
                    mutually_exclusive_with=tuple(request.mutually_exclusive_with),
                    prerequisite_experiments=tuple(request.prerequisite_experiments),
                    change_note=request.change_note,
                ),
                changed_by=admin_actor,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.experiments.registry.update",
                "experiment_key": experiment_key,
            },
        }

    @router.get("/experiments/registry/{experiment_key}/audit", response_model=ExperimentRegistryAuditResponse)
    async def experiment_registry_audit(
        experiment_key: str,
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: ExperimentRegistryService = Depends(get_experiment_registry_service),
    ):
        try:
            audits = await service.list_audit_history(experiment_key, limit=limit)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": audits,
            "meta": {
                "source": "admin.experiments.registry.audit",
                "experiment_key": experiment_key,
            },
        }

    @router.get("/experiments/registry/{experiment_key}/report", response_model=ExperimentOperatorReportResponse)
    async def experiment_registry_report(
        experiment_key: str,
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: ExperimentRegistryService = Depends(get_experiment_registry_service),
    ):
        try:
            report = await service.get_operator_report(experiment_key, limit=limit)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": report,
            "meta": {
                "source": "admin.experiments.registry.report",
                "experiment_key": experiment_key,
            },
        }

    @router.get("/experiments/health/report", response_model=ExperimentHealthDashboardResponse)
    async def experiment_health_report(
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: ExperimentRegistryService = Depends(get_experiment_registry_service),
    ):
        report = await service.get_health_dashboard(limit=limit)
        return {
            "data": report,
            "meta": {"source": "admin.experiments.health_report"},
        }

    @router.get("/notifications/policies", response_model=NotificationPolicyListResponse)
    async def notification_policy_list(
        _: str = Depends(get_admin_token),
        service: NotificationPolicyRegistryService = Depends(get_notification_policy_registry_service),
    ):
        policies = await service.list_policies()
        return {
            "data": policies,
            "meta": {"source": "admin.notifications.policies.list"},
        }

    @router.get("/notifications/policies/health/report", response_model=NotificationPolicyHealthDashboardResponse)
    async def notification_policy_health_report(
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: NotificationPolicyRegistryService = Depends(get_notification_policy_registry_service),
    ):
        report = await service.get_health_dashboard(limit=limit)
        return {
            "data": report,
            "meta": {"source": "admin.notifications.policies.health_report"},
        }

    @router.get("/monetization/health/report", response_model=MonetizationHealthDashboardResponse)
    async def monetization_health_report(
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: MonetizationHealthSignalService = Depends(get_monetization_health_signal_service),
    ):
        report = await service.get_health_dashboard(limit=limit)
        return {
            "data": report,
            "meta": {"source": "admin.monetization.health_report"},
        }

    @router.get("/lifecycle/health/report", response_model=LifecycleHealthDashboardResponse)
    async def lifecycle_health_report(
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: LifecycleHealthSignalService = Depends(get_lifecycle_health_signal_service),
    ):
        report = await service.get_health_dashboard(limit=limit)
        return {
            "data": report,
            "meta": {"source": "admin.lifecycle.health_report"},
        }

    @router.get("/daily-loop/health/report", response_model=DailyLoopHealthDashboardResponse)
    async def daily_loop_health_report(
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: DailyLoopHealthSignalService = Depends(get_daily_loop_health_signal_service),
    ):
        report = await service.get_health_dashboard(limit=limit)
        return {
            "data": report,
            "meta": {"source": "admin.daily_loop.health_report"},
        }

    @router.get("/sessions/health/report", response_model=SessionHealthDashboardResponse)
    async def session_health_report(
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: SessionHealthSignalService = Depends(get_session_health_signal_service),
    ):
        report = await service.get_health_dashboard(limit=limit)
        return {
            "data": report,
            "meta": {"source": "admin.sessions.health_report"},
        }

    @router.get("/learning/health/report", response_model=LearningHealthDashboardResponse)
    async def learning_health_report(
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: LearningHealthSignalService = Depends(get_learning_health_signal_service),
    ):
        report = await service.get_health_dashboard(limit=limit)
        return {
            "data": report,
            "meta": {"source": "admin.learning.health_report"},
        }

    @router.get("/notifications/policies/{policy_key}", response_model=NotificationPolicyDetailResponse)
    async def notification_policy_detail(
        policy_key: str,
        _: str = Depends(get_admin_token),
        service: NotificationPolicyRegistryService = Depends(get_notification_policy_registry_service),
    ):
        try:
            detail = await service.get_policy(policy_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.notifications.policies.detail",
                "policy_key": policy_key,
            },
        }

    @router.put("/notifications/policies/{policy_key}", response_model=NotificationPolicyDetailResponse)
    async def notification_policy_upsert(
        policy_key: str,
        request: NotificationPolicyUpsertRequest,
        admin_actor: str | None = Header(default=None, alias="X-Admin-Actor"),
        _: str = Depends(get_admin_token),
        service: NotificationPolicyRegistryService = Depends(get_notification_policy_registry_service),
    ):
        try:
            detail = await service.upsert_policy(
                policy_key=policy_key,
                command=NotificationPolicyRegistryUpsert(
                    status=request.status,
                    is_killed=request.is_killed,
                    description=request.description,
                    policy=request.policy.model_dump(),
                    change_note=request.change_note,
                ),
                changed_by=admin_actor,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.notifications.policies.update",
                "policy_key": policy_key,
            },
        }

    @router.get("/notifications/policies/{policy_key}/audit", response_model=NotificationPolicyAuditResponse)
    async def notification_policy_audit(
        policy_key: str,
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: NotificationPolicyRegistryService = Depends(get_notification_policy_registry_service),
    ):
        try:
            audits = await service.list_audit_history(policy_key, limit=limit)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": audits,
            "meta": {
                "source": "admin.notifications.policies.audit",
                "policy_key": policy_key,
            },
        }

    @router.get("/notifications/policies/{policy_key}/report", response_model=NotificationPolicyOperatorReportResponse)
    async def notification_policy_report(
        policy_key: str,
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: NotificationPolicyRegistryService = Depends(get_notification_policy_registry_service),
    ):
        try:
            report = await service.get_operator_report(policy_key, limit=limit)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": report,
            "meta": {
                "source": "admin.notifications.policies.report",
                "policy_key": policy_key,
            },
        }

    @router.get("/notifications/{user_id}/report", response_model=NotificationOperatorReportResponse)
    async def notification_report(
        user_id: int,
        policy_key: str = Query(default="default", min_length=1, max_length=128),
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.notification_report(user_id, policy_key=policy_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.notifications.report",
                "user_id": user_id,
                "policy_key": policy_key,
            },
        }

    @router.get("/decision-traces", response_model=DecisionTraceListResponse)
    async def decision_traces(
        user_id: int | None = Query(default=None, ge=1),
        trace_type: str | None = Query(default=None, min_length=3, max_length=64),
        reference_id: str | None = Query(default=None, min_length=3, max_length=128),
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        traces = await service.list_recent(
            user_id=user_id,
            trace_type=trace_type,
            reference_id=reference_id,
            limit=limit,
        )
        return {
            "data": traces,
            "meta": {
                "source": "admin.decision_traces",
                "filters": {
                    "user_id": user_id,
                    "trace_type": trace_type,
                    "reference_id": reference_id,
                    "limit": limit,
                },
            },
        }

    @router.get("/decision-traces/{reference_id}", response_model=DecisionTraceDetailResponse)
    async def decision_trace_detail(
        reference_id: str,
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.session_detail(reference_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.decision_traces.detail",
                "reference_id": reference_id,
            },
        }

    @router.get("/onboarding/{user_id}", response_model=OnboardingDiagnosticsResponse)
    async def onboarding_detail(
        user_id: int,
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.onboarding_detail(user_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.onboarding.detail",
                "user_id": user_id,
            },
        }

    @router.get("/lifecycle/{user_id}", response_model=LifecycleDiagnosticsResponse)
    async def lifecycle_detail(
        user_id: int,
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.lifecycle_detail(user_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.lifecycle.detail",
                "user_id": user_id,
            },
        }

    @router.get("/lifecycle/{user_id}/report", response_model=LifecycleOperatorReportResponse)
    async def lifecycle_report(
        user_id: int,
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.lifecycle_report(user_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.lifecycle.report",
                "user_id": user_id,
            },
        }

    @router.get("/monetization/{user_id}", response_model=MonetizationDiagnosticsResponse)
    async def monetization_detail(
        user_id: int,
        geography: str | None = Query(default=None, min_length=2, max_length=16),
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.monetization_detail(user_id, geography=geography)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.monetization.detail",
                "user_id": user_id,
                "geography": geography,
            },
        }

    @router.get("/monetization/{user_id}/report", response_model=MonetizationOperatorReportResponse)
    async def monetization_report(
        user_id: int,
        geography: str | None = Query(default=None, min_length=2, max_length=16),
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.monetization_report(user_id, geography=geography)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.monetization.report",
                "user_id": user_id,
                "geography": geography,
            },
        }

    @router.get("/daily-loop/{user_id}/report", response_model=DailyLoopOperatorReportResponse)
    async def daily_loop_report(
        user_id: int,
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.daily_loop_report(user_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "data": detail,
            "meta": {
                "source": "admin.daily_loop.report",
                "user_id": user_id,
            },
        }

    return router
