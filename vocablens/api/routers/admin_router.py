from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException

from vocablens.api.dependencies import (
    get_admin_token,
    get_analytics_service,
    get_decision_trace_service,
    get_experiment_results_service,
    get_subscription_service,
)
from vocablens.api.schemas import (
    ConversionMetricsResponse,
    DecisionTraceDetailResponse,
    DecisionTraceListResponse,
    ExperimentResultsResponse,
    RetentionAnalyticsResponse,
    UsageAnalyticsResponse,
)
from vocablens.domain.errors import NotFoundError
from vocablens.services.analytics_service import AnalyticsService
from vocablens.services.decision_trace_service import DecisionTraceService
from vocablens.services.experiment_results_service import ExperimentResultsService
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

    return router
