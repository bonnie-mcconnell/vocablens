from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.frontend_service import FrontendService


class FakeVocabRepo:
    async def list_all(self, user_id: int, limit: int, offset: int):
        return [SimpleNamespace(source_text="hola")]

    async def list_due(self, user_id: int):
        return [SimpleNamespace(source_text="hola")]


class FakeSkillTrackingRepo:
    async def latest_scores(self, user_id: int):
        return {"grammar": 0.6, "vocabulary": 0.7, "fluency": 0.65}


class FakeKnowledgeGraphRepo:
    async def get_weak_clusters(self, user_id: int):
        return [{"cluster": "travel", "words": ["hola"]}]


class FakeProfilesRepo:
    async def get_or_create(self, user_id: int):
        return SimpleNamespace()


class FakeMistakePatternsRepo:
    async def top_patterns(self, user_id: int, limit: int = 5):
        return [SimpleNamespace(category="grammar", pattern="verb tense", count=2)]


class FakeUOW:
    def __init__(self):
        self.vocab = FakeVocabRepo()
        self.skill_tracking = FakeSkillTrackingRepo()
        self.knowledge_graph = FakeKnowledgeGraphRepo()
        self.profiles = FakeProfilesRepo()
        self.mistake_patterns = FakeMistakePatternsRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeLearningEngine:
    def __init__(self, recommendation):
        self.recommendation = recommendation

    async def recommend(self, user_id: int):
        return self.recommendation


class FakeRoadmapService:
    async def generate_today_plan(self, user_id: int):
        return {"review_words": 3}


class FakeRetentionEngine:
    def __init__(self, assessment):
        self.assessment = assessment

    async def assess_user(self, user_id: int):
        return self.assessment


class FakeSubscriptionService:
    def __init__(self, features):
        self.features = features

    async def get_features(self, user_id: int):
        return self.features


class FakePaywallService:
    def __init__(self, decision):
        self.decision = decision

    async def evaluate(self, user_id: int):
        return self.decision


class FakeProgressService:
    def __init__(self, progress):
        self.progress = progress

    async def build_dashboard(self, user_id: int):
        return self.progress


class FakeGlobalDecisionEngine:
    def __init__(self, decision):
        self.decision = decision

    async def decide(self, user_id: int):
        return self.decision


class FakeOnboardingService:
    def __init__(self, plan):
        self.plan_data = plan

    async def plan(self, user_id: int):
        return self.plan_data


def _frontend_service(*, retention_state: str, paywall_show: bool, onboarding_stage: str, primary_action: str):
    recommendation = SimpleNamespace(
        action="review_word" if primary_action == "review" else "conversation_drill",
        target="hola",
        reason="Do this next",
        lesson_difficulty="medium",
        content_type="conversation",
    )
    retention = SimpleNamespace(
        state=retention_state,
        drop_off_risk=0.6 if retention_state != "active" else 0.2,
        current_streak=3,
        session_frequency=2.0,
        suggested_actions=[],
    )
    features = SimpleNamespace(
        tier="pro",
        tutor_depth="standard",
        explanation_quality="standard",
        personalization_level="standard",
        trial_active=False,
        trial_ends_at=None,
        usage_percent=82,
    )
    paywall = SimpleNamespace(
        show_paywall=paywall_show,
        paywall_type="soft_paywall" if paywall_show else None,
        reason="usage pressure high" if paywall_show else None,
        usage_percent=82 if paywall_show else 15,
        allow_access=True,
        trial_active=False,
        trial_ends_at=None,
    )
    progress = {
        "vocabulary_total": 12,
        "due_reviews": 3,
        "metrics": {
            "vocabulary_mastery_percent": 58.3,
            "accuracy_rate": 81.0,
            "response_speed_seconds": 14.2,
            "fluency_score": 63.0,
        },
        "daily": {"words_learned": 1, "reviews_completed": 2, "messages_sent": 3, "accuracy_rate": 80.0},
        "weekly": {"words_learned": 8, "reviews_completed": 15, "messages_sent": 11, "accuracy_rate": 82.0},
        "trends": {"weekly_words_learned_delta": 3, "weekly_reviews_completed_delta": 4, "weekly_messages_sent_delta": 2, "weekly_accuracy_rate_delta": 5.0, "fluency_score": 63.0},
        "skill_breakdown": {"grammar": 70.0, "vocabulary": 60.0, "fluency": 63.0},
    }
    decision = SimpleNamespace(
        primary_action=primary_action,
        difficulty_level="easy" if retention_state != "active" else "medium",
        session_type="quick" if retention_state != "active" else "deep",
        monetization_action="soft_paywall" if paywall_show else "none",
        engagement_action="habit_nudge" if retention_state == "new_user" else "streak_push",
        lifecycle_stage="new_user" if retention_state == "active" and primary_action == "conversation" else "at_risk" if retention_state != "active" else "engaged",
        reason="Backend controls next step.",
    )
    onboarding = SimpleNamespace(
        stage=onboarding_stage,
        habit_hook={"show_streak_starting": onboarding_stage == "habit_hook", "show_progress_jump": onboarding_stage in {"wow_moment", "habit_hook"}},
    )
    return FrontendService(
        lambda: FakeUOW(),
        FakeLearningEngine(recommendation),
        FakeRoadmapService(),
        FakeRetentionEngine(retention),
        FakeSubscriptionService(features),
        FakePaywallService(paywall),
        FakeProgressService(progress),
        FakeGlobalDecisionEngine(decision),
        FakeOnboardingService(onboarding),
    )


def test_frontend_service_returns_activation_ui_signals_for_new_user():
    service = _frontend_service(
        retention_state="active",
        paywall_show=False,
        onboarding_stage="first_success",
        primary_action="conversation",
    )

    dashboard = run_async(service.dashboard(1))

    assert dashboard["ui"]["show_streak_animation"] is True
    assert dashboard["ui"]["show_progress_boost"] is True
    assert dashboard["ui"]["show_paywall"] is False
    assert dashboard["ui"]["show_celebration"] is True
    assert dashboard["session_config"]["session_length"] == 8
    assert dashboard["session_config"]["mode"] == "chat"
    assert dashboard["core_loop"]["focus_skill"] == "vocabulary"
    assert dashboard["core_loop"]["goal_label"]
    assert "first win" in dashboard["emotion_hooks"]["encouragement_message"].lower()


def test_frontend_service_returns_retention_and_paywall_signals_for_at_risk_user():
    service = _frontend_service(
        retention_state="at-risk",
        paywall_show=True,
        onboarding_stage="guided_learning",
        primary_action="review",
    )

    recommendations = run_async(service.recommendations(2))

    assert recommendations["ui"]["show_paywall"] is True
    assert recommendations["session_config"]["mode"] == "review"
    assert recommendations["session_config"]["difficulty"] == "easy"
    assert recommendations["core_loop"]["review_window_minutes"] == 30
    assert "first win" in recommendations["emotion_hooks"]["encouragement_message"].lower()
    assert "usage" in recommendations["emotion_hooks"]["urgency_message"].lower() or "streak" in recommendations["emotion_hooks"]["urgency_message"].lower()
    assert "progress step" in recommendations["emotion_hooks"]["reward_message"].lower()
