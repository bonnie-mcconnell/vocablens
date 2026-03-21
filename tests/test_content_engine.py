from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.content_engine import ContentEngine
from vocablens.services.conversion_funnel_service import FunnelState
from vocablens.services.gamification_service import Badge, GamificationProfile


class FakeProgressService:
    async def build_dashboard(self, user_id: int):
        return {
            "metrics": {
                "vocabulary_mastery_percent": 58.0,
                "accuracy_rate": 83.5,
                "response_speed_seconds": 4.2,
                "fluency_score": 69.0,
            },
            "daily": {
                "words_learned": 6,
                "reviews_completed": 4,
                "messages_sent": 12,
            },
            "weekly": {
                "reviews_completed": 17,
            },
            "skill_breakdown": {
                "grammar": 62.0,
                "vocabulary": 71.0,
                "fluency": 69.0,
            },
        }


class FakeRetentionEngine:
    async def assess_user(self, user_id: int):
        return SimpleNamespace(current_streak=5)


class FakeConversionFunnelService:
    async def state(self, user_id: int):
        return FunnelState(
            stage="value_realization",
            completed_stages=["awareness", "value_realization"],
            next_action="highlight_wow_value",
            nudges=["show_value", "soft_nudge"],
            messaging={},
            paywall={"show": False},
            experiment_variant=None,
        )


class FakeViralityService:
    async def referral_summary(self, user_id: int):
        return {
            "invite_code": "VL-1-ABC123",
            "share_url": "https://example.test/invite/VL-1-ABC123",
            "referrals_count": 3,
            "total_xp_earned": 900,
            "progress_shares": 2,
        }


class FakeGamificationService:
    async def summary(self, user_id: int):
        return GamificationProfile(
            xp=645,
            level=3,
            xp_into_level=145,
            xp_to_next_level=105,
            current_streak=5,
            longest_streak=9,
            streak_milestones_reached=[3],
            next_streak_milestone=7,
            badges=[Badge("streak_keeper", "Streak Keeper", "Held a 3-day streak.")],
            stats={"sessions": 8},
        )


class FakeBusinessMetricsService:
    async def dashboard(self):
        return {
            "revenue": {
                "mrr": 240.0,
                "arpu": 24.0,
                "ltv": 180.0,
            },
            "funnel": {
                "conversion_per_stage": [
                    {"stage": "awareness", "users": 100, "drop_off_rate": 20.0},
                    {"stage": "paywall_exposure", "users": 40, "drop_off_rate": 55.0},
                ]
            },
            "retention_visualization": {
                "curves": [
                    {
                        "cohort_date": "2026-03-01",
                        "points": [
                            {"day": 1, "retention": 72.0},
                            {"day": 7, "retention": 41.0},
                            {"day": 30, "retention": 26.0},
                        ],
                    }
                ]
            },
        }


def test_content_engine_generates_user_content_ideas_from_product_signals():
    engine = ContentEngine(
        FakeProgressService(),
        FakeRetentionEngine(),
        FakeConversionFunnelService(),
        FakeViralityService(),
        FakeGamificationService(),
    )

    ideas = run_async(engine.ideas_for_user(1))

    assert len(ideas) == 5
    assert ideas[0].format == "before_after_tutor_clip"
    assert "83.5%" in ideas[0].hook
    assert any("5-day" in idea.hook for idea in ideas)
    assert any(idea.angle == "social_proof" and idea.source_signals["referrals_count"] == 3 for idea in ideas)
    assert any(idea.angle == "gamification" and idea.source_signals["level"] == 3 for idea in ideas)


def test_content_engine_generates_operator_content_from_business_metrics():
    engine = ContentEngine(
        FakeProgressService(),
        FakeRetentionEngine(),
        business_metrics_service=FakeBusinessMetricsService(),
    )

    ideas = run_async(engine.operator_ideas())

    assert len(ideas) == 3
    assert ideas[0].angle == "founder_build_in_public"
    assert "$240.0" in ideas[0].hook
    assert ideas[1].source_signals["stage"] == "paywall_exposure"
    assert "41.0%" in ideas[2].hook
