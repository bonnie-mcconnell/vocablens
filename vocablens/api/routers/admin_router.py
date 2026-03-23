from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException

from vocablens.api.dependencies import (
    get_admin_token,
    get_analytics_service,
    get_decision_trace_service,
    get_experiment_results_service,
    get_subscription_service,
)
from vocablens.api.schemas import APIResponse
from vocablens.domain.errors import NotFoundError
from vocablens.services.analytics_service import AnalyticsService
from vocablens.services.decision_trace_service import DecisionTraceService
from vocablens.services.experiment_results_service import ExperimentResultsService
from vocablens.services.subscription_service import SubscriptionService


def create_admin_router() -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["Admin"])

    @router.get("/reports/conversions", response_model=APIResponse)
    async def conversion_metrics(
        _: str = Depends(get_admin_token),
        service: SubscriptionService = Depends(get_subscription_service),
    ):
        metrics = await service.conversion_metrics()
        return APIResponse(
            data={"conversion_metrics": metrics},
            meta={"source": "admin.conversions"},
        )

    @router.get("/analytics/retention", response_model=APIResponse)
    async def retention_analytics(
        _: str = Depends(get_admin_token),
        service: AnalyticsService = Depends(get_analytics_service),
    ):
        metrics = await service.retention_report()
        return APIResponse(
            data={"retention": metrics},
            meta={"source": "admin.analytics.retention"},
        )

    @router.get("/analytics/usage", response_model=APIResponse)
    async def usage_analytics(
        _: str = Depends(get_admin_token),
        service: AnalyticsService = Depends(get_analytics_service),
    ):
        metrics = await service.usage_report()
        return APIResponse(
            data={"usage": metrics},
            meta={"source": "admin.analytics.usage"},
        )

    @router.get("/experiments/results", response_model=APIResponse)
    async def experiment_results(
        experiment_key: str | None = Query(default=None),
        _: str = Depends(get_admin_token),
        service: ExperimentResultsService = Depends(get_experiment_results_service),
    ):
        results = await service.results(experiment_key)
        return APIResponse(
            data={"experiment_results": results},
            meta={"source": "admin.experiments.results"},
        )

    @router.get("/decision-traces", response_model=APIResponse)
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
        return APIResponse(
            data=traces,
            meta={
                "source": "admin.decision_traces",
                "filters": {
                    "user_id": user_id,
                    "trace_type": trace_type,
                    "reference_id": reference_id,
                    "limit": limit,
                },
            },
        )

    @router.get("/decision-traces/{reference_id}", response_model=APIResponse)
    async def decision_trace_detail(
        reference_id: str,
        _: str = Depends(get_admin_token),
        service: DecisionTraceService = Depends(get_decision_trace_service),
    ):
        try:
            detail = await service.session_detail(reference_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return APIResponse(
            data=detail,
            meta={
                "source": "admin.decision_traces.detail",
                "reference_id": reference_id,
            },
        )

    return router
