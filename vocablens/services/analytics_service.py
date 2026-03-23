from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.report_models import (
    RetentionCohort,
    RetentionCurve,
    RetentionReport,
    UsageEngagementDistribution,
    UsageReport,
)


class AnalyticsService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def retention_report(self) -> RetentionReport:
        now = utc_now()
        async with self._uow_factory() as uow:
            users = await uow.users.list_all()
            events = await uow.events.list_since(now - timedelta(days=61), limit=20000)
            await uow.commit()

        active_dates_by_user: dict[int, set] = defaultdict(set)
        for event in events:
            if getattr(event, "created_at", None) is not None:
                active_dates_by_user[event.user_id].add(event.created_at.date())

        cohorts: dict[str, list] = defaultdict(list)
        for user in users:
            cohorts[user.created_at.date().isoformat()].append(user)

        cohort_rows = []
        retained_d30 = 0
        eligible_d30 = 0
        for cohort_date, cohort_users in sorted(cohorts.items()):
            signup_date = cohort_users[0].created_at.date()
            size = len(cohort_users)
            d1 = self._retention_rate(cohort_users, active_dates_by_user, signup_date, 1)
            d7 = self._retention_rate(cohort_users, active_dates_by_user, signup_date, 7)
            d30 = self._retention_rate(cohort_users, active_dates_by_user, signup_date, 30)
            eligible = sum(1 for user in cohort_users if (now.date() - user.created_at.date()).days >= 30)
            retained = sum(
                1
                for user in cohort_users
                if eligible > 0 and signup_date + timedelta(days=30) in active_dates_by_user.get(user.id, set())
            )
            eligible_d30 += eligible
            retained_d30 += retained
            cohort_rows.append(
                RetentionCohort(
                    cohort_date=cohort_date,
                    size=size,
                    d1_retention=d1,
                    d7_retention=d7,
                    d30_retention=d30,
                    retention_curve=RetentionCurve(d1=d1, d7=d7, d30=d30),
                )
            )

        churn_rate = 0.0
        if eligible_d30:
            churn_rate = round(100.0 - ((retained_d30 / eligible_d30) * 100), 1)

        return RetentionReport(cohorts=cohort_rows, churn_rate=churn_rate)

    async def usage_report(self) -> UsageReport:
        now = utc_now()
        async with self._uow_factory() as uow:
            events = await uow.events.list_since(
                now - timedelta(days=31),
                event_types=["session_started", "session_ended", "message_sent"],
                limit=40000,
            )
            await uow.commit()

        dau_users = {
            event.user_id
            for event in events
            if getattr(event, "created_at", None) is not None and event.created_at.date() == now.date()
        }
        mau_users = {
            event.user_id
            for event in events
            if getattr(event, "created_at", None) is not None and event.created_at >= now - timedelta(days=30)
        }
        session_lengths = self._session_lengths(events)
        session_counts: dict[int, int] = defaultdict(int)
        for event in events:
            if getattr(event, "event_type", None) == "session_started":
                session_counts[event.user_id] += 1

        total_sessions = sum(session_counts.values())
        user_count = len(session_counts)
        dau = len(dau_users)
        mau = len(mau_users)
        avg_session_length = round(sum(session_lengths) / len(session_lengths), 1) if session_lengths else 0.0
        sessions_per_user = round(total_sessions / user_count, 2) if user_count else 0.0

        return UsageReport(
            dau=dau,
            mau=mau,
            dau_mau_ratio=round((dau / mau), 3) if mau else 0.0,
            avg_session_length_seconds=avg_session_length,
            sessions_per_user=sessions_per_user,
            engagement_distribution=self._engagement_distribution(session_counts),
        )

    def _retention_rate(self, cohort_users, active_dates_by_user, signup_date, day_offset: int) -> float:
        eligible_users = [
            user for user in cohort_users
            if (utc_now().date() - user.created_at.date()).days >= day_offset
        ]
        if not eligible_users:
            return 0.0
        retained = sum(
            1
            for user in eligible_users
            if signup_date + timedelta(days=day_offset) in active_dates_by_user.get(user.id, set())
        )
        return round((retained / len(eligible_users)) * 100, 1)

    def _session_lengths(self, events) -> list[float]:
        lengths: list[float] = []
        by_user: dict[int, list] = defaultdict(list)
        for event in events:
            by_user[event.user_id].append(event)
        for user_events in by_user.values():
            open_session = None
            for event in sorted(user_events, key=lambda item: getattr(item, "created_at", utc_now())):
                if event.event_type == "session_started":
                    open_session = event.created_at
                elif event.event_type == "session_ended" and open_session is not None:
                    lengths.append(max(0.0, (event.created_at - open_session).total_seconds()))
                    open_session = None
        return lengths

    def _engagement_distribution(self, session_counts: dict[int, int]) -> UsageEngagementDistribution:
        distribution = {"low": 0, "medium": 0, "high": 0}
        for count in session_counts.values():
            if count <= 2:
                distribution["low"] += 1
            elif count <= 5:
                distribution["medium"] += 1
            else:
                distribution["high"] += 1
        return UsageEngagementDistribution(**distribution)
