from tests.conftest import run_async
from vocablens.services.decision_trace_service import DecisionTraceService


class StubDecisionTraceService(DecisionTraceService):
    def __init__(self):
        super().__init__(lambda: None)

    async def session_detail(self, reference_id: str) -> dict:
        return {
            "session": {
                "session_id": reference_id,
                "user_id": 13,
                "status": "completed",
                "contract_version": "v2",
                "duration_seconds": 220,
                "mode": "game_round",
                "weak_area": "grammar",
                "lesson_target": "past tense",
                "goal_label": "Fix one grammar pattern cleanly",
                "success_criteria": "Use the corrected form.",
                "review_window_minutes": 15,
                "max_response_words": 12,
                "session_payload": {"phases": [{"name": "warmup"}, {"name": "core_challenge"}]},
                "created_at": "2026-03-23T11:58:00",
                "expires_at": "2026-03-23T12:13:00",
                "completed_at": "2026-03-23T12:00:00",
                "last_evaluated_at": "2026-03-23T12:00:00",
                "evaluation_count": 1,
            },
            "evaluation": {
                "trace_type": "session_evaluation",
                "source": "session_engine",
                "is_correct": False,
                "improvement_score": 0.74,
                "highlighted_mistakes": ["past_tense_irregular"],
                "recommended_next_step": "retry_with_correction",
                "reason": "Evaluated the stored structured session and completed canonical state projection.",
                "created_at": "2026-03-23T12:00:00",
            },
            "attempts": [
                {
                    "id": 7,
                    "session_id": reference_id,
                    "user_id": 13,
                    "submission_id": "submit_12345678",
                    "learner_response": "I goed there yesterday",
                    "response_word_count": 4,
                    "response_char_count": 23,
                    "is_correct": False,
                    "improvement_score": 0.74,
                    "validation_payload": {"response_word_count": 4, "max_response_words": 12},
                    "feedback_payload": {"corrected_response": "I went there yesterday."},
                    "created_at": "2026-03-23T12:00:00",
                }
            ],
            "events": [
                {
                    "id": 20,
                    "event_type": "session_submission_rejected",
                    "payload": {"session_id": reference_id, "reason": "stale_contract"},
                    "created_at": "2026-03-23T11:59:00",
                },
                {
                    "id": 21,
                    "event_type": "session_ended",
                    "payload": {"session_id": reference_id, "improvement_score": 0.74},
                    "created_at": "2026-03-23T12:00:00",
                },
            ],
            "traces": [
                {
                    "id": 3,
                    "user_id": 13,
                    "trace_type": "session_evaluation",
                    "source": "session_engine",
                    "reference_id": reference_id,
                    "policy_version": "v1",
                    "inputs": {"learner_response": "I goed there yesterday"},
                    "outputs": {"improvement_score": 0.74},
                    "reason": "Evaluated the stored structured session and completed canonical state projection.",
                    "created_at": "2026-03-23T12:00:00",
                }
            ],
        }

    async def session_report(self, user_id: int) -> dict:
        detail = await self.session_detail(f"sess_{user_id}")
        attempts = list(detail["attempts"])
        events = list(detail["events"])
        traces = list(detail["traces"])
        rejection_events = [
            event
            for event in events
            if event["event_type"] == "session_submission_rejected"
        ]
        return {
            "detail": detail,
            "latest_decisions": {
                "latest_session": detail["session"],
                "latest_attempt": attempts[-1] if attempts else None,
                "latest_evaluation": traces[0] if traces else None,
                "latest_rejection": rejection_events[-1] if rejection_events else None,
            },
            "event_summary": {
                "total_events": len(events),
                "counts_by_type": {
                    event["event_type"]: sum(1 for item in events if item["event_type"] == event["event_type"])
                    for event in events
                },
                "latest_event_at": events[-1]["created_at"] if events else None,
            },
            "trace_summary": {
                "total_traces": len(traces),
                "counts_by_type": {
                    trace["trace_type"]: sum(1 for item in traces if item["trace_type"] == trace["trace_type"])
                    for trace in traces
                },
                "latest_trace_at": traces[-1]["created_at"] if traces else None,
            },
        }

    async def lifecycle_detail(self, user_id: int) -> dict:
        return {
            "notification_eligibility": {
                "lifecycle_stage": "activating",
                "lifecycle_reasons": ["user is building toward activation"],
                "notification_lifecycle_stage": "activating",
                "state_aligned": True,
                "lifecycle_notifications_enabled": True,
                "suppression_reason": None,
                "suppression_active": False,
                "suppressed_until": None,
                "cooldown_active": False,
                "cooldown_until": None,
                "frequency_limit": 2,
                "sent_count_today": 0,
                "daily_limit_reached": False,
                "next_eligible_at": None,
                "blocking_reasons": [],
            },
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
            "notification_eligibility": {
                "lifecycle_stage": "at_risk",
                "lifecycle_reasons": ["retention engine marked user as at risk"],
                "notification_lifecycle_stage": "at_risk",
                "state_aligned": True,
                "lifecycle_notifications_enabled": True,
                "suppression_reason": None,
                "suppression_active": False,
                "suppressed_until": None,
                "cooldown_active": True,
                "cooldown_until": "2026-03-23T16:00:00",
                "frequency_limit": 2,
                "sent_count_today": 1,
                "daily_limit_reached": False,
                "next_eligible_at": "2026-03-23T16:00:00",
                "blocking_reasons": ["cooldown active"],
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
    assert report["latest_decisions"]["notification_eligibility"]["state_aligned"] is True
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
    assert report["latest_decisions"]["notification_eligibility"]["cooldown_active"] is True
    assert report["latest_decisions"]["active_policy"]["policy_key"] == "default"
    assert report["latest_decisions"]["latest_delivery"]["status"] == "sent"
    assert report["delivery_summary"]["counts_by_status"]["skipped"] == 1
    assert report["suppression_summary"]["counts_by_type"]["lifecycle_notification_suppressed"] == 1


def test_session_report_promotes_latest_session_attempt_and_trace():
    service = StubDecisionTraceService()

    report = run_async(service.session_report(13))

    assert report["latest_decisions"]["latest_session"]["session_id"] == "sess_13"
    assert report["latest_decisions"]["latest_attempt"]["submission_id"] == "submit_12345678"
    assert report["latest_decisions"]["latest_evaluation"]["trace_type"] == "session_evaluation"
    assert report["event_summary"]["counts_by_type"]["session_ended"] == 1
    assert report["trace_summary"]["counts_by_type"]["session_evaluation"] == 1
