from fastapi.testclient import TestClient

from tests.conftest import make_user
from vocablens.api.dependencies import (
    get_admin_token,
    get_analytics_service,
    get_current_user,
    get_decision_trace_service,
    get_experiment_registry_service,
    get_experiment_results_service,
    get_frontend_service,
    get_onboarding_flow_service,
    get_subscription_service,
)
from vocablens.main import create_app


class FakeFrontendService:
    async def dashboard(self, user_id: int):
        return {
            "progress": {
                "vocabulary_total": 12,
                "due_reviews": 3,
                "streak": 4,
                "session_frequency": 2.5,
                "retention_state": "active",
                "metrics": {
                    "vocabulary_mastery_percent": 58.3,
                    "accuracy_rate": 81.0,
                    "response_speed_seconds": 14.2,
                    "fluency_score": 63.0,
                },
                "daily": {"words_learned": 2, "reviews_completed": 4, "messages_sent": 3, "accuracy_rate": 80.0},
                "weekly": {"words_learned": 8, "reviews_completed": 15, "messages_sent": 11, "accuracy_rate": 82.0},
                "trends": {"weekly_words_learned_delta": 3, "weekly_reviews_completed_delta": 4, "weekly_messages_sent_delta": 2, "weekly_accuracy_rate_delta": 5.0, "fluency_score": 63.0},
                "skill_breakdown": {"grammar": 70.0, "vocabulary": 60.0, "fluency": 63.0},
            },
            "subscription": {"tier": "pro", "tutor_depth": "standard", "explanation_quality": "standard", "personalization_level": "standard"},
            "skills": {"grammar": 0.7, "vocabulary": 0.6},
            "next_action": {"action": "review_word", "target": "hola", "reason": "Due review", "difficulty": "medium", "content_type": "vocab"},
            "retention": {"state": "active", "drop_off_risk": 0.2, "actions": []},
            "weak_areas": {"clusters": [], "mistakes": []},
            "roadmap": {"review_words": 3},
        }

    async def recommendations(self, user_id: int):
        return {
            "next_action": {"action": "learn_new_word", "target": "travel", "reason": "Weak cluster", "difficulty": "medium", "content_type": "vocab"},
            "retention_actions": [{"kind": "review_reminder", "reason": "3 reviews waiting", "target": "hola"}],
        }

    async def weak_areas(self, user_id: int):
        return {
            "weak_skills": [{"skill": "vocabulary", "score": 0.55}],
            "weak_clusters": [{"cluster": "travel", "weakness": 1.1, "words": ["hola", "adios"]}],
            "mistake_patterns": [{"category": "grammar", "pattern": "verb tense", "count": 2}],
        }

    async def paywall(self, user_id: int):
        return {
            "show": True,
            "type": "soft_paywall",
            "reason": "usage pressure high",
            "usage_percent": 82,
            "trial_active": False,
            "allow_access": True,
        }

    def meta(self, *, source: str, difficulty: str | None = None, next_action: str | None = None):
        meta = {"source": source}
        if difficulty:
            meta["difficulty"] = difficulty
        if next_action:
            meta["next_action"] = next_action
        return meta


class FakeSubscriptionService:
    async def conversion_metrics(self):
        return {"tier_upgraded": 4, "feature_gate_blocked": 9}


class FakeAnalyticsService:
    async def retention_report(self):
        return {"cohorts": [{"cohort_date": "2026-03-01", "d1_retention": 60.0}]}

    async def usage_report(self):
        return {"dau": 12, "mau": 40, "dau_mau_ratio": 0.3}


class FakeExperimentResultsService:
    async def results(self, experiment_key: str | None = None):
        return {
            "experiments": [
                {
                    "experiment_key": experiment_key or "paywall_offer",
                    "variants": [{"variant": "control", "retention_rate": 40.0, "conversion_rate": 10.0, "engagement": {"sessions_per_user": 1.5}}],
                    "comparisons": [],
                }
            ]
        }


class FakeExperimentRegistryService:
    async def list_registries(self):
        return {
            "experiments": [
                {
                    "experiment_key": "paywall_offer",
                    "status": "active",
                    "rollout_percentage": 100,
                    "is_killed": False,
                    "description": "Controls paywall offer composition.",
                    "variants": [{"name": "control", "weight": 70}, {"name": "annual_anchor", "weight": 30}],
                    "created_at": "2026-03-23T12:00:00",
                    "updated_at": "2026-03-24T09:00:00",
                    "assignment_count": 120,
                    "exposure_count": 118,
                    "exposure_gap": 2,
                    "assignment_variants": {"annual_anchor": 31, "control": 89},
                    "exposure_variants": {"annual_anchor": 30, "control": 88},
                    "latest_change": {
                        "id": 4,
                        "experiment_key": "paywall_offer",
                        "action": "updated",
                        "changed_by": "ops@vocablens",
                        "change_note": "Raised annual anchor weight after review.",
                        "previous_config": {"rollout_percentage": 100},
                        "new_config": {"rollout_percentage": 100},
                        "created_at": "2026-03-24T09:00:00",
                    },
                }
            ]
        }

    async def get_registry(self, experiment_key: str):
        return {
            "experiment": {
                "experiment_key": experiment_key,
                "status": "active",
                "rollout_percentage": 100,
                "is_killed": False,
                "description": "Controls paywall offer composition.",
                "variants": [{"name": "control", "weight": 70}, {"name": "annual_anchor", "weight": 30}],
                "created_at": "2026-03-23T12:00:00",
                "updated_at": "2026-03-24T09:00:00",
                "health": {
                    "assignment_count": 120,
                    "exposure_count": 118,
                    "exposure_gap": 2,
                    "exposure_coverage_percent": 98.33,
                    "assignment_variants": {"annual_anchor": 31, "control": 89},
                    "exposure_variants": {"annual_anchor": 30, "control": 88},
                },
                "audit_entries": [
                    {
                        "id": 4,
                        "experiment_key": experiment_key,
                        "action": "updated",
                        "changed_by": "ops@vocablens",
                        "change_note": "Raised annual anchor weight after review.",
                        "previous_config": {"variants": [{"name": "control", "weight": 80}]},
                        "new_config": {"variants": [{"name": "control", "weight": 70}]},
                        "created_at": "2026-03-24T09:00:00",
                    }
                ],
            }
        }

    async def upsert_registry(self, *, experiment_key: str, command, changed_by: str | None):
        return {
            "experiment": {
                "experiment_key": experiment_key,
                "status": command.status,
                "rollout_percentage": command.rollout_percentage,
                "is_killed": command.is_killed,
                "description": command.description,
                "variants": [{"name": item.name, "weight": item.weight} for item in command.variants],
                "created_at": "2026-03-23T12:00:00",
                "updated_at": "2026-03-24T10:00:00",
                "health": {
                    "assignment_count": 120,
                    "exposure_count": 118,
                    "exposure_gap": 2,
                    "exposure_coverage_percent": 98.33,
                    "assignment_variants": {"annual_anchor": 31, "control": 89},
                    "exposure_variants": {"annual_anchor": 30, "control": 88},
                },
                "audit_entries": [
                    {
                        "id": 5,
                        "experiment_key": experiment_key,
                        "action": "updated",
                        "changed_by": changed_by or "system_admin",
                        "change_note": command.change_note,
                        "previous_config": {"status": "active"},
                        "new_config": {"status": command.status},
                        "created_at": "2026-03-24T10:00:00",
                    }
                ],
            }
        }

    async def list_audit_history(self, experiment_key: str, *, limit: int = 50):
        return {
            "audit_entries": [
                {
                    "id": 5,
                    "experiment_key": experiment_key,
                    "action": "updated",
                    "changed_by": "ops@vocablens",
                    "change_note": "Raised annual anchor weight after review.",
                    "previous_config": {"status": "active"},
                    "new_config": {"status": "active"},
                    "created_at": "2026-03-24T10:00:00",
                }
            ][:limit]
        }


class FakeOnboardingFlowService:
    async def start(self, user_id: int):
        return {
            "current_step": "identity_selection",
            "onboarding_state": {"current_step": "identity_selection", "steps_completed": []},
            "ui_directives": {"show_identity_picker": True},
            "messaging": {"encouragement_message": "Choose your goal.", "urgency_message": "", "reward_message": ""},
            "next_action": {"action": "select_identity", "target": ["fluency"], "reason": "Start motivation capture."},
        }

    async def next(self, user_id: int, payload: dict | None = None):
        return {
            "current_step": "personalization",
            "onboarding_state": {"current_step": "personalization", "steps_completed": ["identity_selection"]},
            "ui_directives": {"show_personalization_form": True},
            "messaging": {"encouragement_message": "We will tailor this fast.", "urgency_message": "", "reward_message": ""},
            "next_action": {"action": "set_preferences", "target": {"skill_level": "beginner"}, "reason": "Tailor the first win."},
        }


class FakeDecisionTraceService:
    async def list_recent(
        self,
        *,
        user_id: int | None = None,
        trace_type: str | None = None,
        reference_id: str | None = None,
        limit: int = 100,
    ):
        return {
            "traces": [
                {
                    "id": 1,
                    "user_id": user_id or 1,
                    "trace_type": trace_type or "session_evaluation",
                    "source": "session_engine",
                    "reference_id": reference_id or "sess_123",
                    "policy_version": "v1",
                    "inputs": {"lesson_target": "past tense"},
                    "outputs": {"is_correct": False, "improvement_score": 0.74},
                    "reason": "Evaluated the stored structured session and completed canonical state projection.",
                    "created_at": "2026-03-23T12:00:00",
                }
            ]
        }

    async def session_detail(self, reference_id: str):
        return {
            "session": {
                "session_id": reference_id,
                "user_id": 1,
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
                    "user_id": 1,
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
                    "id": 21,
                    "event_type": "session_ended",
                    "payload": {"session_id": reference_id, "improvement_score": 0.74},
                    "created_at": "2026-03-23T12:00:00",
                }
            ],
            "traces": [
                {
                    "id": 3,
                    "user_id": 1,
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

    async def onboarding_detail(self, user_id: int):
        return {
            "state": {
                "current_step": "soft_paywall",
                "steps_completed": ["identity_selection", "personalization", "instant_wow_moment", "progress_illusion"],
                "identity": {"motivation": "travel"},
                "personalization": {"skill_level": "beginner", "daily_goal": 10, "learning_intent": "conversation"},
                "wow": {"score": 0.84, "qualifies": True, "triggered": True, "understood_percent": 81.0},
                "early_success_score": 84.0,
                "progress_illusion": {"xp_gain": 49, "relative_ranking_percentile": 79},
                "paywall": {"show": True, "trial_recommended": True, "strategy": "high_intent:early:premium_anchor"},
                "habit_lock_in": {},
            },
            "latest_transition": {
                "trace_type": "onboarding_transition",
                "source": "onboarding_flow_service",
                "from_step": "progress_illusion",
                "to_step": "soft_paywall",
                "reason": "User completed the progress illusion step and qualified for the next onboarding step.",
                "created_at": "2026-03-23T12:00:00",
            },
            "paywall_entry": {
                "trace_type": "onboarding_paywall_entry",
                "source": "onboarding_flow_service",
                "next_step": "soft_paywall",
                "paywall_strategy": "high_intent:early:premium_anchor",
                "trial_recommended": True,
                "reason": "Paywall shown after progress illusion because wow or engagement threshold qualified.",
                "created_at": "2026-03-23T12:01:00",
            },
            "events": [
                {
                    "id": 31,
                    "event_type": "onboarding_state_updated",
                    "payload": {"current_step": "soft_paywall", "steps_completed_count": 4},
                    "created_at": "2026-03-23T12:01:00",
                }
            ],
            "traces": [
                {
                    "id": 8,
                    "user_id": user_id,
                    "trace_type": "onboarding_paywall_entry",
                    "source": "onboarding_flow_service",
                    "reference_id": f"onboarding:{user_id}",
                    "policy_version": "v1",
                    "inputs": {"wow_score": 0.84, "lifecycle_stage": "new_user"},
                    "outputs": {"next_step": "soft_paywall", "trial_recommended": True},
                    "reason": "Paywall shown after progress illusion because wow or engagement threshold qualified.",
                    "created_at": "2026-03-23T12:01:00",
                }
            ],
        }

    async def lifecycle_detail(self, user_id: int):
        return {
            "onboarding_state": {
                "current_step": "soft_paywall",
                "steps_completed": ["identity_selection", "personalization", "instant_wow_moment", "progress_illusion"],
                "identity": {"motivation": "travel"},
                "personalization": {"skill_level": "beginner", "daily_goal": 10, "learning_intent": "conversation"},
                "wow": {"score": 0.84, "qualifies": True, "triggered": True, "understood_percent": 81.0},
                "early_success_score": 84.0,
                "progress_illusion": {"xp_gain": 49, "relative_ranking_percentile": 79},
                "paywall": {"show": True, "trial_recommended": True, "strategy": "high_intent:early:premium_anchor"},
                "habit_lock_in": {},
            },
            "learning_state": {
                "user_id": user_id,
                "skills": {"grammar": 0.62, "fluency": 0.58},
                "weak_areas": ["grammar"],
                "mastery_percent": 41.0,
                "accuracy_rate": 78.0,
                "response_speed_seconds": 13.2,
                "updated_at": "2026-03-23T12:05:00",
            },
            "engagement_state": {
                "user_id": user_id,
                "current_streak": 2,
                "longest_streak": 2,
                "momentum_score": 0.61,
                "total_sessions": 3,
                "sessions_last_3_days": 3,
                "last_session_at": "2026-03-23T12:04:00",
                "shields_used_this_week": 0,
                "daily_mission_completed_at": None,
                "interaction_stats": {"lessons_completed": 2},
                "updated_at": "2026-03-23T12:05:00",
            },
            "profile": {
                "user_id": user_id,
                "learning_speed": 1.0,
                "retention_rate": 0.82,
                "difficulty_preference": "easy",
                "content_preference": "conversation",
                "last_active_at": "2026-03-23T12:04:00",
                "session_frequency": 3.4,
                "current_streak": 2,
                "longest_streak": 2,
                "drop_off_risk": 0.21,
                "preferred_channel": "push",
                "preferred_time_of_day": 18,
                "frequency_limit": 2,
                "updated_at": "2026-03-23T12:05:00",
            },
            "retention": {
                "state": "active",
                "drop_off_risk": 0.21,
                "session_frequency": 3.4,
                "current_streak": 2,
                "longest_streak": 2,
                "last_active_at": "2026-03-23T12:04:00",
                "is_high_engagement": False,
                "suggested_actions": [{"kind": "streak_nudge", "reason": "Current streak is 2 day(s); keep it going", "target": None}],
            },
            "lifecycle": {
                "stage": "activating",
                "reasons": ["user is building toward activation"],
                "actions": [{"type": "wow_moment_push", "message": "Guide the user toward a clean success around grammar.", "target": None}],
                "paywall": {"show": True, "type": "soft_paywall", "reason": "wow moment reached", "usage_percent": 34, "allow_access": True},
            },
            "adaptive_paywall": {
                "show_paywall": True,
                "paywall_type": "soft_paywall",
                "reason": "wow moment reached",
                "usage_percent": 34,
                "request_usage_percent": 22,
                "token_usage_percent": 34,
                "usage_requests": 22,
                "usage_tokens": 17000,
                "request_limit": 100,
                "token_limit": 50000,
                "sessions_seen": 3,
                "wow_moment_triggered": True,
                "trial_active": False,
                "trial_tier": None,
                "trial_ends_at": None,
                "allow_access": True,
                "user_segment": "high_intent",
                "strategy": "high_intent:early:premium_anchor",
                "trigger_variant": "early",
                "pricing_variant": "premium_anchor",
                "trial_days": 5,
                "wow_score": 0.84,
                "trial_recommended": True,
                "upsell_recommended": True,
            },
            "events": [
                {
                    "id": 41,
                    "event_type": "paywall_viewed",
                    "payload": {"strategy": "high_intent:early:premium_anchor"},
                    "created_at": "2026-03-23T12:01:00",
                }
            ],
            "traces": [
                {
                    "id": 9,
                    "user_id": user_id,
                    "trace_type": "lifecycle_decision",
                    "source": "lifecycle_service.evaluate",
                    "reference_id": f"lifecycle:{user_id}",
                    "policy_version": "v1",
                    "inputs": {"retention": {"state": "active"}},
                    "outputs": {
                        "stage": "activating",
                        "reasons": ["user is building toward activation"],
                        "actions": [{"type": "wow_moment_push", "message": "Guide the user toward a clean success around grammar.", "target": None}],
                        "paywall": {"show": True, "type": "soft_paywall", "reason": "wow moment reached", "usage_percent": 34, "allow_access": True},
                    },
                    "reason": "user is building toward activation",
                    "created_at": "2026-03-23T12:04:30",
                },
                {
                    "id": 8,
                    "user_id": user_id,
                    "trace_type": "onboarding_paywall_entry",
                    "source": "onboarding_flow_service",
                    "reference_id": f"onboarding:{user_id}",
                    "policy_version": "v1",
                    "inputs": {"wow_score": 0.84, "lifecycle_stage": "new_user"},
                    "outputs": {"next_step": "soft_paywall", "trial_recommended": True},
                    "reason": "Paywall shown after progress illusion because wow or engagement threshold qualified.",
                    "created_at": "2026-03-23T12:01:00",
                }
            ],
        }

    async def monetization_detail(self, user_id: int, *, geography: str | None = None):
        return {
            "onboarding_state": {
                "current_step": "soft_paywall",
                "steps_completed": ["identity_selection", "personalization", "instant_wow_moment", "progress_illusion"],
                "identity": {"motivation": "travel"},
                "personalization": {"skill_level": "beginner", "daily_goal": 10, "learning_intent": "conversation"},
                "wow": {"score": 0.84, "qualifies": True, "triggered": True, "understood_percent": 81.0},
                "early_success_score": 84.0,
                "progress_illusion": {"xp_gain": 49, "relative_ranking_percentile": 79},
                "paywall": {"show": True, "trial_recommended": True, "strategy": "high_intent:early:premium_anchor"},
                "habit_lock_in": {},
            },
            "learning_state": {
                "user_id": user_id,
                "skills": {"grammar": 0.62, "fluency": 0.58},
                "weak_areas": ["grammar"],
                "mastery_percent": 41.0,
                "accuracy_rate": 78.0,
                "response_speed_seconds": 13.2,
                "updated_at": "2026-03-23T12:05:00",
            },
            "engagement_state": {
                "user_id": user_id,
                "current_streak": 2,
                "longest_streak": 2,
                "momentum_score": 0.61,
                "total_sessions": 3,
                "sessions_last_3_days": 3,
                "last_session_at": "2026-03-23T12:04:00",
                "shields_used_this_week": 0,
                "daily_mission_completed_at": None,
                "interaction_stats": {"lessons_completed": 2},
                "updated_at": "2026-03-23T12:05:00",
            },
            "progress_state": {
                "user_id": user_id,
                "xp": 49,
                "level": 2,
                "milestones": [1],
                "updated_at": "2026-03-23T12:05:00",
            },
            "profile": {
                "user_id": user_id,
                "learning_speed": 1.0,
                "retention_rate": 0.82,
                "difficulty_preference": "easy",
                "content_preference": "conversation",
                "last_active_at": "2026-03-23T12:04:00",
                "session_frequency": 3.4,
                "current_streak": 2,
                "longest_streak": 2,
                "drop_off_risk": 0.21,
                "preferred_channel": "push",
                "preferred_time_of_day": 18,
                "frequency_limit": 2,
                "updated_at": "2026-03-23T12:05:00",
            },
            "subscription": {
                "user_id": user_id,
                "tier": "free",
                "request_limit": 100,
                "token_limit": 50000,
                "renewed_at": "2026-03-23T10:00:00",
                "trial_started_at": None,
                "trial_ends_at": None,
                "trial_tier": None,
                "created_at": "2026-03-20T10:00:00",
            },
            "monetization_state": {
                "user_id": user_id,
                "current_offer_type": "trial",
                "last_paywall_type": "soft_paywall",
                "last_paywall_reason": "wow moment reached",
                "current_strategy": "high_intent:early:premium_anchor:trial:us",
                "current_geography": geography or "global",
                "lifecycle_stage": "activating",
                "paywall_impressions": 1,
                "paywall_dismissals": 0,
                "paywall_acceptances": 0,
                "paywall_skips": 0,
                "fatigue_score": 1,
                "cooldown_until": "2026-03-24T18:00:00",
                "trial_eligible": True,
                "trial_started_at": None,
                "trial_ends_at": None,
                "trial_offer_days": 5,
                "conversion_propensity": 0.42,
                "last_offer_at": "2026-03-23T12:01:10",
                "last_impression_at": "2026-03-23T12:01:00",
                "last_dismissed_at": None,
                "last_accepted_at": None,
                "last_skipped_at": None,
                "last_pricing": {"monthly_price": 20.0},
                "last_trigger": {"trigger_reason": "wow moment reached"},
                "last_value_display": {"locked_progress_percent": 41},
                "updated_at": "2026-03-23T12:01:10",
            },
            "experiments": {
                "paywall_trigger_timing": "early",
                "paywall_pricing_messaging": "premium_anchor",
                "paywall_trial_length": "trial_5d",
            },
            "retention": {
                "state": "active",
                "drop_off_risk": 0.21,
                "session_frequency": 3.4,
                "current_streak": 2,
                "longest_streak": 2,
                "last_active_at": "2026-03-23T12:04:00",
                "is_high_engagement": False,
                "suggested_actions": [{"kind": "streak_nudge", "reason": "Current streak is 2 day(s); keep it going", "target": None}],
            },
            "lifecycle": {
                "stage": "activating",
                "reasons": ["user is building toward activation"],
                "actions": [{"type": "wow_moment_push", "message": "Guide the user toward a clean success around grammar.", "target": None}],
                "paywall": {"show": True, "type": "soft_paywall", "reason": "wow moment reached", "usage_percent": 34, "allow_access": True},
            },
            "adaptive_paywall": {
                "show_paywall": True,
                "paywall_type": "soft_paywall",
                "reason": "wow moment reached",
                "usage_percent": 34,
                "request_usage_percent": 22,
                "token_usage_percent": 34,
                "usage_requests": 22,
                "usage_tokens": 17000,
                "request_limit": 100,
                "token_limit": 50000,
                "sessions_seen": 3,
                "wow_moment_triggered": True,
                "trial_active": False,
                "trial_tier": None,
                "trial_ends_at": None,
                "allow_access": True,
                "user_segment": "high_intent",
                "strategy": "high_intent:early:premium_anchor",
                "trigger_variant": "early",
                "pricing_variant": "premium_anchor",
                "trial_days": 5,
                "wow_score": 0.84,
                "trial_recommended": True,
                "upsell_recommended": True,
            },
            "monetization": {
                "show_paywall": True,
                "paywall_type": "soft_paywall",
                "offer_type": "trial",
                "pricing": {
                    "geography": geography or "global",
                    "monthly_price": 20.0,
                    "discounted_monthly_price": 18.0,
                    "discount_percent": 10,
                    "annual_price": 180.0,
                    "annual_monthly_equivalent": 15.0,
                    "annual_savings_percent": 25,
                    "pricing_variant": "premium_anchor",
                    "annual_anchor_message": "Monthly is 20.00; annual works out to 15.00 per month.",
                    "business_context": {"ltv": 320.0, "mrr": 1800.0},
                },
                "trigger": {
                    "show_now": True,
                    "trigger_variant": "early",
                    "trigger_reason": "wow moment reached",
                    "lifecycle_stage": "activating",
                    "onboarding_step": "soft_paywall",
                    "timing_policy": "adaptive_paywall",
                },
                "value_display": {
                    "show_locked_progress": True,
                    "locked_progress_percent": 41,
                    "locked_features": ["Unlimited tutor rounds", "Full adaptive review queue"],
                    "highlight": "Keep the progress you have already built.",
                    "usage_percent": 34,
                },
                "strategy": "high_intent:early:premium_anchor:trial:global",
                "lifecycle_stage": "activating",
                "onboarding_step": "soft_paywall",
                "user_segment": "high_intent",
                "trial_days": 5,
            },
            "events": [
                {
                    "id": 41,
                    "event_type": "paywall_viewed",
                    "payload": {"strategy": "high_intent:early:premium_anchor"},
                    "created_at": "2026-03-23T12:01:00",
                }
            ],
            "monetization_events": [
                {
                    "id": 51,
                    "event_type": "decision_evaluated",
                    "offer_type": "trial",
                    "paywall_type": "soft_paywall",
                    "strategy": "high_intent:early:premium_anchor:trial:us",
                    "geography": geography or "global",
                    "payload": {"show_paywall": True, "trial_days": 5},
                    "created_at": "2026-03-23T12:01:10",
                }
            ],
            "traces": [
                {
                    "id": 9,
                    "user_id": user_id,
                    "trace_type": "monetization_decision",
                    "source": "monetization_engine",
                    "reference_id": f"user:{user_id}",
                    "policy_version": "v1",
                    "inputs": {
                        "geography": geography or "global",
                        "lifecycle_stage": "activating",
                        "onboarding_step": "soft_paywall",
                        "strategy": "high_intent:early:premium_anchor",
                    },
                    "outputs": {
                        "show_paywall": True,
                        "offer_type": "trial",
                        "pricing_variant": "premium_anchor",
                        "trigger_variant": "early",
                    },
                    "reason": "Monetization shown after wow moment for a high-intent activating user.",
                    "created_at": "2026-03-23T12:01:10",
                },
                {
                    "id": 8,
                    "user_id": user_id,
                    "trace_type": "onboarding_paywall_entry",
                    "source": "onboarding_flow_service",
                    "reference_id": f"onboarding:{user_id}",
                    "policy_version": "v1",
                    "inputs": {"wow_score": 0.84, "lifecycle_stage": "new_user"},
                    "outputs": {"next_step": "soft_paywall", "trial_recommended": True},
                    "reason": "Paywall shown after progress illusion because wow or engagement threshold qualified.",
                    "created_at": "2026-03-23T12:01:00",
                },
            ],
        }


def test_frontend_dashboard_and_related_endpoints_return_standardized_envelopes():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_frontend_service] = lambda: FakeFrontendService()
    client = TestClient(app)

    dashboard = client.get("/frontend/dashboard", headers={"Authorization": "Bearer ignored"})
    recommendations = client.get("/frontend/recommendations", headers={"Authorization": "Bearer ignored"})
    weak_areas = client.get("/frontend/weak-areas", headers={"Authorization": "Bearer ignored"})
    paywall = client.get("/frontend/paywall", headers={"Authorization": "Bearer ignored"})

    assert dashboard.status_code == 200
    assert dashboard.json()["meta"]["source"] == "frontend.dashboard"
    assert dashboard.json()["data"]["next_action"]["action"] == "review_word"
    assert dashboard.json()["data"]["progress"]["metrics"]["accuracy_rate"] == 81.0

    assert recommendations.status_code == 200
    assert recommendations.json()["meta"]["next_action"] == "learn_new_word"
    assert recommendations.json()["data"]["retention_actions"][0]["kind"] == "review_reminder"

    assert weak_areas.status_code == 200
    assert weak_areas.json()["meta"]["source"] == "frontend.weak_areas"
    assert weak_areas.json()["data"]["weak_clusters"][0]["cluster"] == "travel"

    assert paywall.status_code == 200
    assert paywall.json()["meta"]["source"] == "frontend.paywall"
    assert paywall.json()["data"]["type"] == "soft_paywall"


def test_admin_conversion_report_is_protected_and_standardized():
    app = create_app()
    app.dependency_overrides[get_admin_token] = lambda: "ok"
    app.dependency_overrides[get_subscription_service] = lambda: FakeSubscriptionService()
    app.dependency_overrides[get_analytics_service] = lambda: FakeAnalyticsService()
    app.dependency_overrides[get_experiment_results_service] = lambda: FakeExperimentResultsService()
    app.dependency_overrides[get_experiment_registry_service] = lambda: FakeExperimentRegistryService()
    app.dependency_overrides[get_decision_trace_service] = lambda: FakeDecisionTraceService()
    client = TestClient(app)

    response = client.get("/admin/reports/conversions", headers={"X-Admin-Token": "secret"})
    retention = client.get("/admin/analytics/retention", headers={"X-Admin-Token": "secret"})
    usage = client.get("/admin/analytics/usage", headers={"X-Admin-Token": "secret"})
    experiments = client.get("/admin/experiments/results?experiment_key=paywall_offer", headers={"X-Admin-Token": "secret"})
    registry_list = client.get("/admin/experiments/registry", headers={"X-Admin-Token": "secret"})
    registry_detail = client.get("/admin/experiments/registry/paywall_offer", headers={"X-Admin-Token": "secret"})
    registry_update = client.put(
        "/admin/experiments/registry/paywall_offer",
        json={
            "status": "active",
            "rollout_percentage": 100,
            "is_killed": False,
            "description": "Controls paywall offer composition.",
            "variants": [{"name": "control", "weight": 60}, {"name": "annual_anchor", "weight": 40}],
            "change_note": "Raised annual anchor weight after review.",
        },
        headers={"X-Admin-Token": "secret", "X-Admin-Actor": "ops@vocablens"},
    )
    registry_audit = client.get("/admin/experiments/registry/paywall_offer/audit?limit=10", headers={"X-Admin-Token": "secret"})
    traces = client.get(
        "/admin/decision-traces?user_id=1&trace_type=session_evaluation&reference_id=sess_123&limit=25",
        headers={"X-Admin-Token": "secret"},
    )
    detail = client.get(
        "/admin/decision-traces/sess_123",
        headers={"X-Admin-Token": "secret"},
    )
    onboarding = client.get(
        "/admin/onboarding/1",
        headers={"X-Admin-Token": "secret"},
    )
    lifecycle = client.get(
        "/admin/lifecycle/1",
        headers={"X-Admin-Token": "secret"},
    )
    monetization = client.get(
        "/admin/monetization/1?geography=us",
        headers={"X-Admin-Token": "secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["source"] == "admin.conversions"
    assert payload["data"]["conversion_metrics"]["tier_upgraded"] == 4
    assert retention.status_code == 200
    assert retention.json()["meta"]["source"] == "admin.analytics.retention"
    assert retention.json()["data"]["retention"]["cohorts"][0]["d1_retention"] == 60.0
    assert usage.status_code == 200
    assert usage.json()["meta"]["source"] == "admin.analytics.usage"
    assert usage.json()["data"]["usage"]["dau"] == 12
    assert experiments.status_code == 200
    assert experiments.json()["meta"]["source"] == "admin.experiments.results"
    assert experiments.json()["data"]["experiment_results"]["experiments"][0]["experiment_key"] == "paywall_offer"
    assert registry_list.status_code == 200
    assert registry_list.json()["meta"]["source"] == "admin.experiments.registry.list"
    assert registry_list.json()["data"]["experiments"][0]["assignment_count"] == 120
    assert registry_detail.status_code == 200
    assert registry_detail.json()["meta"]["source"] == "admin.experiments.registry.detail"
    assert registry_detail.json()["data"]["experiment"]["health"]["exposure_gap"] == 2
    assert registry_update.status_code == 200
    assert registry_update.json()["meta"]["source"] == "admin.experiments.registry.update"
    assert registry_update.json()["data"]["experiment"]["audit_entries"][0]["changed_by"] == "ops@vocablens"
    assert registry_update.json()["data"]["experiment"]["variants"][1]["weight"] == 40
    assert registry_audit.status_code == 200
    assert registry_audit.json()["meta"]["source"] == "admin.experiments.registry.audit"
    assert registry_audit.json()["data"]["audit_entries"][0]["action"] == "updated"
    assert traces.status_code == 200
    assert traces.json()["meta"]["source"] == "admin.decision_traces"
    assert traces.json()["meta"]["filters"]["trace_type"] == "session_evaluation"
    assert traces.json()["data"]["traces"][0]["reference_id"] == "sess_123"
    assert detail.status_code == 200
    assert detail.json()["meta"]["source"] == "admin.decision_traces.detail"
    assert detail.json()["data"]["session"]["session_id"] == "sess_123"
    assert detail.json()["data"]["evaluation"]["trace_type"] == "session_evaluation"
    assert detail.json()["data"]["evaluation"]["recommended_next_step"] == "retry_with_correction"
    assert detail.json()["data"]["attempts"][0]["learner_response"] == "I goed there yesterday"
    assert detail.json()["data"]["events"][0]["event_type"] == "session_ended"
    assert detail.json()["data"]["traces"][0]["trace_type"] == "session_evaluation"
    assert onboarding.status_code == 200
    assert onboarding.json()["meta"]["source"] == "admin.onboarding.detail"
    assert onboarding.json()["data"]["state"]["current_step"] == "soft_paywall"
    assert onboarding.json()["data"]["latest_transition"]["trace_type"] == "onboarding_transition"
    assert onboarding.json()["data"]["paywall_entry"]["paywall_strategy"] == "high_intent:early:premium_anchor"
    assert onboarding.json()["data"]["events"][0]["event_type"] == "onboarding_state_updated"
    assert onboarding.json()["data"]["traces"][0]["trace_type"] == "onboarding_paywall_entry"
    assert lifecycle.status_code == 200
    assert lifecycle.json()["meta"]["source"] == "admin.lifecycle.detail"
    assert lifecycle.json()["data"]["lifecycle"]["stage"] == "activating"
    assert lifecycle.json()["data"]["adaptive_paywall"]["strategy"] == "high_intent:early:premium_anchor"
    assert lifecycle.json()["data"]["traces"][0]["trace_type"] == "lifecycle_decision"
    assert lifecycle.json()["data"]["events"][0]["event_type"] == "paywall_viewed"
    assert monetization.status_code == 200
    assert monetization.json()["meta"]["source"] == "admin.monetization.detail"
    assert monetization.json()["meta"]["geography"] == "us"
    assert monetization.json()["data"]["monetization"]["offer_type"] == "trial"
    assert monetization.json()["data"]["monetization"]["pricing"]["geography"] == "us"
    assert monetization.json()["data"]["monetization_state"]["current_offer_type"] == "trial"
    assert monetization.json()["data"]["monetization_events"][0]["event_type"] == "decision_evaluated"
    assert monetization.json()["data"]["experiments"]["paywall_trigger_timing"] == "early"
    assert monetization.json()["data"]["traces"][0]["trace_type"] == "monetization_decision"


def test_onboarding_endpoints_return_standardized_envelopes():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_onboarding_flow_service] = lambda: FakeOnboardingFlowService()
    client = TestClient(app)

    start = client.post("/onboarding/start", json={}, headers={"Authorization": "Bearer ignored"})
    nxt = client.post("/onboarding/next", json={"motivation": "travel"}, headers={"Authorization": "Bearer ignored"})

    assert start.status_code == 200
    assert start.json()["meta"]["source"] == "onboarding.start"
    assert start.json()["data"]["current_step"] == "identity_selection"
    assert nxt.status_code == 200
    assert nxt.json()["meta"]["source"] == "onboarding.next"
    assert nxt.json()["data"]["current_step"] == "personalization"
