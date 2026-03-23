from __future__ import annotations

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.analytics_service import AnalyticsService
from vocablens.services.conversion_funnel_service import ConversionFunnelService
from vocablens.services.report_models import (
    BusinessFunnelSummary,
    BusinessMetricsDashboard,
    FunnelStageMetrics,
    RetentionCohort,
    RetentionCurvePoint,
    RetentionReport,
    RetentionVisualization,
    RetentionVisualizationCurve,
    RevenueMetrics,
)


TIER_MONTHLY_PRICES = {
    "free": 0.0,
    "pro": 20.0,
    "premium": 50.0,
}


class BusinessMetricsService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        analytics_service: AnalyticsService,
        conversion_funnel_service: ConversionFunnelService,
    ):
        self._uow_factory = uow_factory
        self._analytics = analytics_service
        self._funnel = conversion_funnel_service

    async def dashboard(self) -> BusinessMetricsDashboard:
        async with self._uow_factory() as uow:
            users = await uow.users.list_all()
            await uow.commit()

        subscriptions = await self._subscriptions_by_user(users)
        revenue = self._revenue_metrics(subscriptions, user_count=len(users))
        funnel = await self._funnel.metrics()
        retention = await self._analytics.retention_report()

        return BusinessMetricsDashboard(
            revenue=RevenueMetrics(
                pricing_assumptions=TIER_MONTHLY_PRICES,
                **revenue,
            ),
            funnel=BusinessFunnelSummary(
                conversion_per_stage=[
                    row if isinstance(row, FunnelStageMetrics) else FunnelStageMetrics(**row)
                    for row in (funnel.stages if hasattr(funnel, "stages") else funnel.get("stages", []))
                ],
            ),
            retention_visualization=self._retention_visualization(retention),
        )

    async def _subscriptions_by_user(self, users) -> list:
        rows = []
        async with self._uow_factory() as uow:
            for user in users:
                subscription = await uow.subscriptions.get_by_user(user.id)
                if subscription is not None:
                    rows.append(subscription)
            await uow.commit()
        return rows

    def _revenue_metrics(self, subscriptions, *, user_count: int) -> dict:
        mrr = 0.0
        paying_count = 0
        for subscription in subscriptions:
            tier = (getattr(subscription, "tier", "free") or "free").lower()
            price = TIER_MONTHLY_PRICES.get(tier, 0.0)
            if price > 0:
                paying_count += 1
                mrr += price
        arpu = round(mrr / max(1, paying_count), 2) if paying_count else 0.0
        arpu_all_users = round(mrr / max(1, user_count), 2) if user_count else 0.0
        churn_rate = self._estimated_monthly_churn(subscriptions)
        ltv = round(arpu / churn_rate, 2) if churn_rate > 0 else 0.0
        return {
            "mrr": round(mrr, 2),
            "arpu": arpu,
            "arpu_all_users": arpu_all_users,
            "ltv": ltv,
            "paying_users": paying_count,
        }

    def _estimated_monthly_churn(self, subscriptions) -> float:
        if not subscriptions:
            return 0.0
        active_trials = sum(
            1 for subscription in subscriptions
            if getattr(subscription, "trial_tier", None) and getattr(subscription, "trial_ends_at", None) is not None
        )
        churn_proxy = active_trials / max(1, len(subscriptions))
        return round(max(0.05, churn_proxy), 4)

    def _retention_visualization(self, retention: RetentionReport | dict) -> RetentionVisualization:
        if isinstance(retention, RetentionReport):
            cohorts = retention.cohorts
            churn_rate = retention.churn_rate
        else:
            cohorts = retention.get("cohorts", [])
            churn_rate = retention.get("churn_rate", 0.0)

        return RetentionVisualization(
            curves=[
                RetentionVisualizationCurve(
                    cohort_date=row.cohort_date if isinstance(row, RetentionCohort) else row["cohort_date"],
                    points=[
                        RetentionCurvePoint(
                            day=1,
                            retention=row.retention_curve.d1 if isinstance(row, RetentionCohort) else row["retention_curve"]["d1"],
                        ),
                        RetentionCurvePoint(
                            day=7,
                            retention=row.retention_curve.d7 if isinstance(row, RetentionCohort) else row["retention_curve"]["d7"],
                        ),
                        RetentionCurvePoint(
                            day=30,
                            retention=row.retention_curve.d30 if isinstance(row, RetentionCohort) else row["retention_curve"]["d30"],
                        ),
                    ],
                )
                for row in cohorts
            ],
            churn_rate=churn_rate,
        )
