from tests.conftest import run_async
from vocablens.services.decision_trace_service import DecisionTraceService


class StubDecisionTraceService(DecisionTraceService):
    def __init__(self):
        super().__init__(lambda: None)

    async def lifecycle_detail(self, user_id: int) -> dict:
        return {
            "lifecycle_transitions": [
                {
                    "id": 4,
                    "user_id": user_id,
                    "from_stage": "new_user",
                    "to_stage": "activating",
                    "reasons": ["user is building toward activation"],
                    "source": "lifecycle_service.evaluate",
                    "reference_id": f"lifecycle:{user_id}",
                    "payload": {},
                    "created_at": "2026-03-23T12:04:30",
                }
            ],
            "events": [
                {"id": 41, "event_type": "paywall_viewed", "payload": {}, "created_at": "2026-03-23T12:01:00"},
                {"id": 42, "event_type": "session_started", "payload": {}, "created_at": "2026-03-23T12:04:00"},
            ],
            "traces": [
                {
                    "id": 7,
                    "user_id": user_id,
                    "trace_type": "lifecycle_action_plan",
                    "source": "lifecycle_service.evaluate",
                    "reference_id": f"lifecycle:{user_id}",
                    "policy_version": "v1",
                    "inputs": {},
                    "outputs": {"action_types": ["wow_moment_push"]},
                    "reason": "Built the lifecycle action bundle before the final lifecycle decision.",
                    "created_at": "2026-03-23T12:04:20",
                },
                {
                    "id": 8,
                    "user_id": user_id,
                    "trace_type": "lifecycle_decision",
                    "source": "lifecycle_service.evaluate",
                    "reference_id": f"lifecycle:{user_id}",
                    "policy_version": "v1",
                    "inputs": {},
                    "outputs": {"stage": "activating"},
                    "reason": "user is building toward activation",
                    "created_at": "2026-03-23T12:04:30",
                },
            ],
        }

    async def monetization_detail(self, user_id: int, *, geography: str | None = None) -> dict:
        return {
            "monetization_events": [
                {
                    "id": 51,
                    "event_type": "decision_evaluated",
                    "offer_type": "trial",
                    "paywall_type": "soft_paywall",
                    "strategy": "high_intent:early:premium_anchor:trial:us",
                    "geography": geography or "global",
                    "payload": {},
                    "created_at": "2026-03-23T12:01:10",
                }
            ],
            "events": [
                {"id": 41, "event_type": "paywall_viewed", "payload": {}, "created_at": "2026-03-23T12:01:00"},
            ],
            "traces": [
                {
                    "id": 9,
                    "user_id": user_id,
                    "trace_type": "monetization_decision",
                    "source": "monetization_engine",
                    "reference_id": f"user:{user_id}",
                    "policy_version": "v1",
                    "inputs": {},
                    "outputs": {"offer_type": "trial"},
                    "reason": "Monetization shown after wow moment for a high-intent activating user.",
                    "created_at": "2026-03-23T12:01:10",
                }
            ],
        }

    async def daily_loop_detail(self, user_id: int) -> dict:
        return {
            "engagement_state": {
                "user_id": user_id,
                "current_streak": 5,
                "longest_streak": 7,
                "momentum_score": 0.88,
                "total_sessions": 12,
                "sessions_last_3_days": 5,
                "last_session_at": "2026-03-23T12:05:00",
                "shields_used_this_week": 1,
                "daily_mission_completed_at": "2026-03-23T12:07:00",
                "interaction_stats": {"lessons_completed": 9},
                "updated_at": "2026-03-23T12:07:00",
            },
            "progress_state": {
                "user_id": user_id,
                "xp": 145,
                "level": 4,
                "milestones": [1, 2, 3],
                "updated_at": "2026-03-23T12:07:00",
            },
            "retention": {
                "state": "active",
                "drop_off_risk": 0.12,
                "session_frequency": 4.1,
                "current_streak": 5,
                "longest_streak": 7,
                "last_active_at": "2026-03-23T12:05:00",
                "is_high_engagement": True,
                "suggested_actions": [],
            },
            "missions": [
                {
                    "id": 11,
                    "user_id": user_id,
                    "mission_date": "2026-03-23",
                    "status": "completed",
                    "weak_area": "grammar",
                    "mission_max_sessions": 3,
                    "steps": [{"kind": "warmup"}],
                    "loss_aversion_message": "Finish today to keep the streak clean.",
                    "streak_at_issue": 5,
                    "momentum_score": 0.88,
                    "notification_preview": {"title": "Finish your mission"},
                    "completed_at": "2026-03-23T12:07:00",
                    "created_at": "2026-03-23T08:00:00",
                    "updated_at": "2026-03-23T12:07:00",
                }
            ],
            "reward_chests": [
                {
                    "id": 21,
                    "user_id": user_id,
                    "mission_id": 11,
                    "status": "unlocked",
                    "xp_reward": 25,
                    "badge_hint": "Consistency",
                    "payload": {"coins": 10},
                    "unlocked_at": "2026-03-23T12:07:00",
                    "claimed_at": None,
                    "created_at": "2026-03-23T08:00:00",
                    "updated_at": "2026-03-23T12:07:00",
                }
            ],
            "events": [
                {
                    "id": 61,
                    "event_type": "daily_mission_completed",
                    "payload": {"mission_id": 11},
                    "created_at": "2026-03-23T12:07:00",
                },
                {
                    "id": 62,
                    "event_type": "reward_chest_unlocked",
                    "payload": {"reward_chest_id": 21},
                    "created_at": "2026-03-23T12:07:05",
                },
            ],
            "traces": [
                {
                    "id": 12,
                    "user_id": user_id,
                    "trace_type": "daily_mission_generation",
                    "source": "daily_loop_service.build_daily_loop",
                    "reference_id": "daily_loop:2026-03-23",
                    "policy_version": "v1",
                    "inputs": {},
                    "outputs": {"mission_id": 11},
                    "reason": "Issued the daily mission from canonical loop state.",
                    "created_at": "2026-03-23T08:00:00",
                },
                {
                    "id": 13,
                    "user_id": user_id,
                    "trace_type": "reward_chest_resolution",
                    "source": "daily_loop_service.complete_mission",
                    "reference_id": "daily_loop:2026-03-23",
                    "policy_version": "v1",
                    "inputs": {},
                    "outputs": {"reward_chest_id": 21, "status": "unlocked"},
                    "reason": "Unlocked the reward chest after canonical mission completion.",
                    "created_at": "2026-03-23T12:07:05",
                },
            ],
        }

    async def notification_detail(self, user_id: int, *, policy_key: str = "default") -> dict:
        return {
            "notification_policy": {
                "policy_key": policy_key,
                "status": "active",
                "is_killed": False,
                "description": "Canonical notification policy.",
                "policy": {
                    "cooldown_hours": 4,
                    "default_frequency_limit": 2,
                },
                "created_at": "2026-03-23T07:00:00",
                "updated_at": "2026-03-23T12:00:00",
            },
            "notification_state": {
                "user_id": user_id,
                "preferred_channel": "push",
                "preferred_time_of_day": 18,
                "frequency_limit": 2,
                "lifecycle_stage": "at_risk",
                "lifecycle_policy_version": "v1",
                "lifecycle_policy": {"lifecycle_notifications_enabled": True},
                "suppression_reason": None,
                "suppressed_until": None,
                "cooldown_until": "2026-03-23T16:00:00",
                "sent_count_day": "2026-03-23",
                "sent_count_today": 1,
                "last_sent_at": "2026-03-23T12:08:00",
                "last_delivery_channel": "push",
                "last_delivery_status": "sent",
                "last_delivery_category": "reengagement",
                "last_reference_id": f"lifecycle:{user_id}",
                "last_decision_at": "2026-03-23T12:07:50",
                "last_decision_reason": "At-risk user matched the reengagement policy.",
                "updated_at": "2026-03-23T12:08:00",
            },
            "notification_suppression_events": [
                {
                    "id": 73,
                    "user_id": user_id,
                    "event_type": "lifecycle_notification_suppressed",
                    "source": "notification_state_service.apply_lifecycle_policy",
                    "reference_id": f"lifecycle:{user_id}",
                    "lifecycle_stage": "engaged",
                    "suppression_reason": "quiet engaged users",
                    "suppressed_until": "2026-03-23T10:00:00",
                    "payload": {"recovery_window_hours": 24},
                    "created_at": "2026-03-22T10:00:00",
                }
            ],
            "notification_deliveries": [
                {
                    "id": 81,
                    "user_id": user_id,
                    "category": "reengagement",
                    "provider": "push",
                    "status": "sent",
                    "title": "Pick up your streak",
                    "body": "One short round keeps your progress moving.",
                    "payload": {"campaign": "at_risk_recovery"},
                    "error_message": None,
                    "attempt_count": 1,
                    "created_at": "2026-03-23T12:08:00",
                    "updated_at": "2026-03-23T12:08:03",
                },
                {
                    "id": 80,
                    "user_id": user_id,
                    "category": "reengagement",
                    "provider": "push",
                    "status": "skipped",
                    "title": "Keep going",
                    "body": "You are close to another clean streak day.",
                    "payload": {"campaign": "at_risk_recovery"},
                    "error_message": "cooldown_active",
                    "attempt_count": 1,
                    "created_at": "2026-03-23T09:00:00",
                    "updated_at": "2026-03-23T09:00:01",
                },
            ],
            "events": [
                {
                    "id": 91,
                    "event_type": "notification_emitted",
                    "payload": {"provider": "push", "status": "sent"},
                    "created_at": "2026-03-23T12:08:03",
                }
            ],
            "traces": [
                {
                    "id": 71,
                    "user_id": user_id,
                    "trace_type": "notification_selection",
                    "source": "notification_decision_engine",
                    "reference_id": f"lifecycle:{user_id}",
                    "policy_version": "v1",
                    "inputs": {"lifecycle_stage": "at_risk"},
                    "outputs": {"should_send": True, "category": "reengagement", "channel": "push"},
                    "reason": "At-risk user matched the reengagement policy.",
                    "created_at": "2026-03-23T12:07:50",
                }
            ],
        }


def test_lifecycle_report_promotes_latest_artifacts_and_summaries():
    service = StubDecisionTraceService()

    report = run_async(service.lifecycle_report(7))

    assert report["latest_decisions"]["lifecycle_decision"]["trace_type"] == "lifecycle_decision"
    assert report["latest_decisions"]["lifecycle_action_plan"]["trace_type"] == "lifecycle_action_plan"
    assert report["event_summary"]["counts_by_type"]["paywall_viewed"] == 1
    assert report["trace_summary"]["counts_by_type"]["lifecycle_decision"] == 1


def test_monetization_report_promotes_latest_artifacts_and_summaries():
    service = StubDecisionTraceService()

    report = run_async(service.monetization_report(9, geography="us"))

    assert report["latest_decisions"]["monetization_decision"]["trace_type"] == "monetization_decision"
    assert report["latest_decisions"]["latest_monetization_event"]["event_type"] == "decision_evaluated"
    assert report["monetization_event_summary"]["counts_by_type"]["decision_evaluated"] == 1


def test_daily_loop_report_promotes_latest_artifacts_and_summaries():
    service = StubDecisionTraceService()

    report = run_async(service.daily_loop_report(5))

    assert report["latest_decisions"]["daily_mission_generation"]["trace_type"] == "daily_mission_generation"
    assert report["latest_decisions"]["reward_chest_resolution"]["trace_type"] == "reward_chest_resolution"
    assert report["latest_decisions"]["latest_mission"]["status"] == "completed"
    assert report["reward_chest_summary"]["counts_by_status"]["unlocked"] == 1


def test_notification_report_promotes_policy_delivery_and_suppression_artifacts():
    service = StubDecisionTraceService()

    report = run_async(service.notification_report(11))

    assert report["latest_decisions"]["notification_selection"]["trace_type"] == "notification_selection"
    assert report["latest_decisions"]["active_policy"]["policy_key"] == "default"
    assert report["latest_decisions"]["latest_delivery"]["status"] == "sent"
    assert report["delivery_summary"]["counts_by_status"]["skipped"] == 1
    assert report["suppression_summary"]["counts_by_type"]["lifecycle_notification_suppressed"] == 1
