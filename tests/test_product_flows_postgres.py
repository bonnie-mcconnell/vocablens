from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from tests.conftest import run_async
from tests.postgres_harness import postgres_harness, seed_user
from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import (
    DailyMissionORM,
    DecisionTraceORM,
    EventORM,
    ExperimentAssignmentORM,
    ExperimentExposureORM,
    ExperimentOutcomeAttributionORM,
    LearningSessionORM,
    NotificationDeliveryORM,
    RewardChestORM,
    SubscriptionORM,
    UserEngagementStateORM,
    UserLifecycleStateORM,
    UserMonetizationStateORM,
    UserNotificationStateORM,
)
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.services.adaptive_paywall_service import AdaptivePaywallService
from vocablens.services.daily_loop_service import DailyLoopService
from vocablens.services.event_service import EventService
from vocablens.services.experiment_attribution_service import ExperimentAttributionService
from vocablens.services.experiment_service import ExperimentService
from vocablens.services.gamification_service import GamificationService
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.monetization_engine import MonetizationEngine
from vocablens.services.monetization_state_service import MonetizationStateService
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.notification_delivery_service import (
    NotificationDeliveryService,
    PushDeliveryBackend,
)
from vocablens.services.progress_service import ProgressService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.session_engine import SessionEngine
from vocablens.services.subscription_service import SubscriptionService
from vocablens.services.wow_engine import WowEngine


@dataclass(frozen=True)
class ScenarioSnapshot:
    session: LearningSessionORM
    engagement_state: UserEngagementStateORM
    lifecycle_state: UserLifecycleStateORM | None
    notification_state: UserNotificationStateORM | None
    monetization_state: UserMonetizationStateORM
    subscription: SubscriptionORM | None
    daily_missions: list[DailyMissionORM]
    reward_chests: list[RewardChestORM]
    experiment_assignments: list[ExperimentAssignmentORM]
    experiment_exposures: list[ExperimentExposureORM]
    experiment_attributions: list[ExperimentOutcomeAttributionORM]
    notification_deliveries: list[NotificationDeliveryORM]
    events: list[EventORM]
    traces: list[DecisionTraceORM]


class DeterministicLearningEngine:
    def __init__(self, delegate: LearningEngine):
        self._delegate = delegate

    async def get_next_lesson(self, user_id: int):
        return SimpleNamespace(
            action="practice_grammar",
            target="past tense",
            reason="Grammar skill below threshold",
            lesson_difficulty="medium",
            review_frequency_multiplier=1.0,
            content_type="mixed",
            review_priority=0.8,
            skill_focus="grammar",
            due_items_count=0,
            goal_label="Fix one grammar pattern cleanly",
            review_window_minutes=15,
        )

    async def apply_session_result(self, user_id: int, session_result, *, source: str, uow=None, reference_id: str | None = None):
        return await self._delegate.apply_session_result(
            user_id,
            session_result,
            source=source,
            uow=uow,
            reference_id=reference_id,
        )


class StaticOnboardingFlowService:
    def __init__(self, state: dict):
        self._state = dict(state)

    async def current_state(self, user_id: int) -> dict:
        return dict(self._state)


class StaticBusinessMetricsService:
    async def dashboard(self) -> dict:
        return {
            "revenue": {
                "ltv": 360.0,
                "mrr": 2400.0,
            }
        }


async def _seed_experiment_registries(uow_factory) -> None:
    experiments = {
        "paywall_offer": [
            {"name": "control", "weight": 70},
            {"name": "annual_anchor", "weight": 30},
        ],
        "paywall_trigger_timing": [
            {"name": "control", "weight": 50},
            {"name": "wow_gate", "weight": 50},
        ],
        "paywall_pricing_messaging": [
            {"name": "standard", "weight": 50},
            {"name": "premium_anchor", "weight": 50},
        ],
        "paywall_trial_length": [
            {"name": "control", "weight": 50},
            {"name": "trial_7d", "weight": 50},
        ],
    }
    async with uow_factory() as uow:
        for experiment_key, variants in experiments.items():
            await uow.experiment_registries.upsert(
                experiment_key=experiment_key,
                status="active",
                rollout_percentage=100,
                holdout_percentage=0,
                is_killed=False,
                baseline_variant=variants[0]["name"],
                description=f"{experiment_key} integration coverage.",
                variants=variants,
                eligibility={},
                mutually_exclusive_with=[],
                prerequisite_experiments=[],
            )
        await uow.commit()


async def _set_profile(uow_factory, *, user_id: int, last_active_at, session_frequency: float, current_streak: int, longest_streak: int, drop_off_risk: float, preferred_channel: str = "push", preferred_time_of_day: int = 18, frequency_limit: int = 2) -> None:
    async with uow_factory() as uow:
        await uow.profiles.get_or_create(user_id)
        await uow.profiles.update(
            user_id,
            last_active_at=last_active_at,
            session_frequency=session_frequency,
            current_streak=current_streak,
            longest_streak=longest_streak,
            drop_off_risk=drop_off_risk,
            preferred_channel=preferred_channel,
            preferred_time_of_day=preferred_time_of_day,
            frequency_limit=frequency_limit,
        )
        await uow.commit()


async def _set_engagement(uow_factory, *, user_id: int, total_sessions: int, sessions_last_3_days: int, current_streak: int, longest_streak: int, momentum_score: float) -> None:
    async with uow_factory() as uow:
        await uow.engagement_states.get_or_create(user_id)
        await uow.engagement_states.update(
            user_id,
            total_sessions=total_sessions,
            sessions_last_3_days=sessions_last_3_days,
            current_streak=current_streak,
            longest_streak=longest_streak,
            momentum_score=momentum_score,
        )
        await uow.commit()


async def _load_snapshot(session_factory, *, user_id: int, session_id: str) -> ScenarioSnapshot:
    async with session_factory() as session:
        session_row = (
            await session.execute(
                select(LearningSessionORM).where(LearningSessionORM.session_id == session_id)
            )
        ).scalar_one()
        engagement_state = (
            await session.execute(
                select(UserEngagementStateORM).where(UserEngagementStateORM.user_id == user_id)
            )
        ).scalar_one()
        lifecycle_state = (
            await session.execute(
                select(UserLifecycleStateORM).where(UserLifecycleStateORM.user_id == user_id)
            )
        ).scalar_one_or_none()
        notification_state = (
            await session.execute(
                select(UserNotificationStateORM).where(UserNotificationStateORM.user_id == user_id)
            )
        ).scalar_one_or_none()
        monetization_state = (
            await session.execute(
                select(UserMonetizationStateORM).where(UserMonetizationStateORM.user_id == user_id)
            )
        ).scalar_one()
        subscription = (
            await session.execute(
                select(SubscriptionORM).where(SubscriptionORM.user_id == user_id)
            )
        ).scalar_one_or_none()
        daily_missions = (
            await session.execute(
                select(DailyMissionORM)
                .where(DailyMissionORM.user_id == user_id)
                .order_by(DailyMissionORM.created_at.asc(), DailyMissionORM.id.asc())
            )
        ).scalars().all()
        reward_chests = (
            await session.execute(
                select(RewardChestORM)
                .where(RewardChestORM.user_id == user_id)
                .order_by(RewardChestORM.created_at.asc(), RewardChestORM.id.asc())
            )
        ).scalars().all()
        experiment_assignments = (
            await session.execute(
                select(ExperimentAssignmentORM)
                .where(ExperimentAssignmentORM.user_id == user_id)
                .order_by(ExperimentAssignmentORM.experiment_key.asc())
            )
        ).scalars().all()
        experiment_exposures = (
            await session.execute(
                select(ExperimentExposureORM)
                .where(ExperimentExposureORM.user_id == user_id)
                .order_by(ExperimentExposureORM.experiment_key.asc())
            )
        ).scalars().all()
        experiment_attributions = (
            await session.execute(
                select(ExperimentOutcomeAttributionORM)
                .where(ExperimentOutcomeAttributionORM.user_id == user_id)
                .order_by(ExperimentOutcomeAttributionORM.experiment_key.asc())
            )
        ).scalars().all()
        notification_deliveries = (
            await session.execute(
                select(NotificationDeliveryORM)
                .where(NotificationDeliveryORM.user_id == user_id)
                .order_by(NotificationDeliveryORM.created_at.asc(), NotificationDeliveryORM.id.asc())
            )
        ).scalars().all()
        events = (
            await session.execute(
                select(EventORM)
                .where(EventORM.user_id == user_id)
                .order_by(EventORM.created_at.asc(), EventORM.id.asc())
            )
        ).scalars().all()
        traces = (
            await session.execute(
                select(DecisionTraceORM)
                .where(DecisionTraceORM.user_id == user_id)
                .order_by(DecisionTraceORM.created_at.asc(), DecisionTraceORM.id.asc())
            )
        ).scalars().all()
        await session.commit()
    return ScenarioSnapshot(
        session=session_row,
        engagement_state=engagement_state,
        lifecycle_state=lifecycle_state,
        notification_state=notification_state,
        monetization_state=monetization_state,
        subscription=subscription,
        daily_missions=list(daily_missions),
        reward_chests=list(reward_chests),
        experiment_assignments=list(experiment_assignments),
        experiment_exposures=list(experiment_exposures),
        experiment_attributions=list(experiment_attributions),
        notification_deliveries=list(notification_deliveries),
        events=list(events),
        traces=list(traces),
    )


async def _run_first_week_flow(harness) -> ScenarioSnapshot:
    uow_factory = UnitOfWorkFactory(harness.session_factory)
    await seed_user(harness.session_factory, user_id=601)
    await _seed_experiment_registries(uow_factory)
    await _set_profile(
        uow_factory,
        user_id=601,
        last_active_at=utc_now(),
        session_frequency=1.0,
        current_streak=0,
        longest_streak=0,
        drop_off_risk=0.18,
    )

    attribution_service = ExperimentAttributionService(uow_factory)
    event_service = EventService(uow_factory, attribution_service, use_buffer=False)
    experiment_service = ExperimentService(
        uow_factory,
        event_service=event_service,
        attribution_service=attribution_service,
    )
    retention_engine = RetentionEngine(uow_factory)
    progress_service = ProgressService(uow_factory)
    gamification_service = GamificationService(uow_factory, progress_service, retention_engine, event_service)
    real_learning_engine = LearningEngine(uow_factory, retention_engine=retention_engine)
    learning_engine = DeterministicLearningEngine(real_learning_engine)
    session_engine = SessionEngine(
        uow_factory,
        learning_engine,
        WowEngine(uow_factory),
        gamification_service=gamification_service,
        event_service=event_service,
        experiment_attribution_service=attribution_service,
    )
    notification_engine = NotificationDecisionEngine(uow_factory)
    delivery_service = NotificationDeliveryService(
        uow_factory,
        backends={"push": PushDeliveryBackend()},
    )
    daily_loop_service = DailyLoopService(
        uow_factory,
        learning_engine,
        gamification_service,
        notification_engine,
        retention_engine,
        event_service=event_service,
    )
    monetization_state_service = MonetizationStateService(uow_factory)
    adaptive_paywall_service = AdaptivePaywallService(
        uow_factory,
        event_service=event_service,
        experiment_service=experiment_service,
        monetization_state_service=monetization_state_service,
    )
    lifecycle_service = LifecycleService(
        uow_factory,
        retention_engine,
        progress_service,
        notification_engine,
        adaptive_paywall_service,
    )
    monetization_engine = MonetizationEngine(
        uow_factory,
        adaptive_paywall_service,
        StaticBusinessMetricsService(),
        StaticOnboardingFlowService(
            {
                "current_step": "completed",
                "paywall": {"trial_recommended": True},
                "progress_illusion": {"enabled": True},
            }
        ),
        lifecycle_service,
        monetization_state_service=monetization_state_service,
    )
    subscription_service = SubscriptionService(
        uow_factory,
        experiment_service=experiment_service,
        event_service=event_service,
        paywall_service=adaptive_paywall_service,
        monetization_state_service=monetization_state_service,
    )

    started = await session_engine.start_session(601)
    await session_engine.evaluate_session(
        601,
        started["session_id"],
        "I goed there yesterday",
        submission_id="first_week_submit",
        contract_version=started["contract_version"],
    )
    await event_service.flush()

    await daily_loop_service.build_daily_loop(601)
    await daily_loop_service.complete_daily_mission(601)
    await daily_loop_service.claim_reward_chest(601)
    await event_service.flush()

    await lifecycle_service.evaluate(601)
    monetization_decision = await monetization_engine.evaluate(601, geography="us", wow_score=0.84)
    assert monetization_decision.show_paywall is True
    await subscription_service.start_trial(601, duration_days=3)
    await event_service.flush()

    return await _load_snapshot(
        harness.session_factory,
        user_id=601,
        session_id=started["session_id"],
    )


async def _run_comeback_flow(harness) -> ScenarioSnapshot:
    uow_factory = UnitOfWorkFactory(harness.session_factory)
    await seed_user(harness.session_factory, user_id=602)
    await _seed_experiment_registries(uow_factory)
    await _set_profile(
        uow_factory,
        user_id=602,
        last_active_at=utc_now().replace(hour=8, minute=0, second=0, microsecond=0),
        session_frequency=0.4,
        current_streak=0,
        longest_streak=4,
        drop_off_risk=0.72,
        preferred_channel="push",
        preferred_time_of_day=20,
        frequency_limit=2,
    )
    await _set_engagement(
        uow_factory,
        user_id=602,
        total_sessions=5,
        sessions_last_3_days=0,
        current_streak=0,
        longest_streak=4,
        momentum_score=0.12,
    )
    async with uow_factory() as uow:
        stale_last_active = utc_now() - timedelta(days=6)
        await uow.profiles.get_or_create(602)
        await uow.profiles.update(
            602,
            last_active_at=stale_last_active,
            session_frequency=0.3,
            current_streak=0,
            longest_streak=4,
            drop_off_risk=0.78,
        )
        await uow.commit()

    attribution_service = ExperimentAttributionService(uow_factory)
    event_service = EventService(uow_factory, attribution_service, use_buffer=False)
    experiment_service = ExperimentService(
        uow_factory,
        event_service=event_service,
        attribution_service=attribution_service,
    )
    retention_engine = RetentionEngine(uow_factory)
    progress_service = ProgressService(uow_factory)
    gamification_service = GamificationService(uow_factory, progress_service, retention_engine, event_service)
    real_learning_engine = LearningEngine(uow_factory, retention_engine=retention_engine)
    learning_engine = DeterministicLearningEngine(real_learning_engine)
    session_engine = SessionEngine(
        uow_factory,
        learning_engine,
        WowEngine(uow_factory),
        gamification_service=gamification_service,
        event_service=event_service,
        experiment_attribution_service=attribution_service,
    )
    notification_engine = NotificationDecisionEngine(uow_factory)
    delivery_service = NotificationDeliveryService(
        uow_factory,
        backends={"push": PushDeliveryBackend()},
    )
    daily_loop_service = DailyLoopService(
        uow_factory,
        learning_engine,
        gamification_service,
        notification_engine,
        retention_engine,
        event_service=event_service,
    )
    monetization_state_service = MonetizationStateService(uow_factory)
    adaptive_paywall_service = AdaptivePaywallService(
        uow_factory,
        event_service=event_service,
        experiment_service=experiment_service,
        monetization_state_service=monetization_state_service,
    )
    lifecycle_service = LifecycleService(
        uow_factory,
        retention_engine,
        progress_service,
        notification_engine,
        adaptive_paywall_service,
    )
    monetization_engine = MonetizationEngine(
        uow_factory,
        adaptive_paywall_service,
        StaticBusinessMetricsService(),
        StaticOnboardingFlowService(
            {
                "current_step": "completed",
                "paywall": {"trial_recommended": False},
                "progress_illusion": {},
            }
        ),
        lifecycle_service,
        monetization_state_service=monetization_state_service,
    )
    subscription_service = SubscriptionService(
        uow_factory,
        experiment_service=experiment_service,
        event_service=event_service,
        paywall_service=adaptive_paywall_service,
        monetization_state_service=monetization_state_service,
    )

    lifecycle_plan = await lifecycle_service.evaluate(602)
    retention = await retention_engine.assess_user(602)
    notification_decision = await notification_engine.decide(
        602,
        retention,
        reference_id="lifecycle:602",
        source_context="lifecycle_service.notification",
    )
    if notification_decision.should_send and notification_decision.message is not None:
        await delivery_service.send(notification_decision.message)
    await event_service.flush()

    started = await session_engine.start_session(602)
    await session_engine.evaluate_session(
        602,
        started["session_id"],
        "I goed there yesterday",
        submission_id="comeback_submit",
        contract_version=started["contract_version"],
    )
    await event_service.flush()

    await daily_loop_service.build_daily_loop(602)
    await daily_loop_service.complete_daily_mission(602)
    await daily_loop_service.claim_reward_chest(602)
    await event_service.flush()

    monetization_decision = await monetization_engine.evaluate(602, geography="us", wow_score=0.82)
    assert lifecycle_plan.stage in {"at_risk", "churned"}
    assert monetization_decision.show_paywall is True
    await subscription_service.register_upgrade_click(602, source="integration_test.comeback")
    await subscription_service.upgrade_tier(602, "pro")
    await event_service.flush()

    return await _load_snapshot(
        harness.session_factory,
        user_id=602,
        session_id=started["session_id"],
    )


def test_first_week_flow_persists_canonical_cross_system_state():
    with postgres_harness() as harness:
        snapshot = run_async(_run_first_week_flow(harness))

        assert snapshot.session.status == "completed"
        assert snapshot.engagement_state.total_sessions >= 1
        assert snapshot.daily_missions[0].status == "completed"
        assert snapshot.reward_chests[0].status == "claimed"
        assert snapshot.lifecycle_state is not None
        assert snapshot.lifecycle_state.current_stage in {"new_user", "activating"}
        assert snapshot.notification_state is not None
        assert snapshot.notification_state.lifecycle_stage == snapshot.lifecycle_state.current_stage
        assert snapshot.monetization_state.paywall_impressions >= 1
        assert snapshot.monetization_state.trial_started_at is not None
        assert snapshot.subscription is not None
        assert snapshot.subscription.trial_tier == "pro"
        assert len(snapshot.experiment_assignments) >= 1
        assert len(snapshot.experiment_exposures) >= 1
        assert len(snapshot.experiment_attributions) >= 1
        trace_types = {row.trace_type for row in snapshot.traces}
        assert "session_evaluation" in trace_types
        assert "daily_mission_generation" in trace_types
        assert "reward_chest_resolution" in trace_types
        assert "lifecycle_decision" in trace_types
        assert "monetization_decision" in trace_types


def test_comeback_flow_persists_notification_reactivation_and_conversion():
    with postgres_harness() as harness:
        snapshot = run_async(_run_comeback_flow(harness))

        assert snapshot.session.status == "completed"
        assert snapshot.lifecycle_state is not None
        assert snapshot.lifecycle_state.current_stage in {"at_risk", "churned", "activating"}
        assert snapshot.notification_state is not None
        assert snapshot.notification_state.last_delivery_status == "sent"
        assert len(snapshot.notification_deliveries) >= 1
        assert snapshot.daily_missions[0].status == "completed"
        assert snapshot.reward_chests[0].status == "claimed"
        assert snapshot.subscription is not None
        assert snapshot.subscription.tier == "pro"
        assert snapshot.monetization_state.paywall_acceptances >= 1
        assert snapshot.monetization_state.last_accepted_at is not None
        assert any(row.converted for row in snapshot.experiment_attributions)
        assert any(int(getattr(row, "upgrade_click_count", 0) or 0) >= 1 for row in snapshot.experiment_attributions)
        event_types = {row.event_type for row in snapshot.events}
        assert "upgrade_clicked" in event_types
        assert "subscription_upgraded" in event_types
        trace_types = {row.trace_type for row in snapshot.traces}
        assert "notification_selection" in trace_types
        assert "lifecycle_transition" in trace_types
        assert "monetization_decision" in trace_types
