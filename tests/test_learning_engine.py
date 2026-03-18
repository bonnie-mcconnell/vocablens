from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.personalization_service import PersonalizationAdaptation
from vocablens.services.retention_engine import RetentionEngine


class FakeLearningEngineUOW:
    def __init__(
        self,
        due_items=None,
        total_vocab=None,
        skills=None,
        clusters=None,
        patterns=None,
        repeated_patterns=None,
        recent_events=None,
        profile=None,
    ):
        self.vocab = SimpleNamespace(
            list_due=self._list_due,
            list_all=self._list_all,
        )
        self.skill_tracking = SimpleNamespace(latest_scores=self._latest_scores)
        self.knowledge_graph = SimpleNamespace(list_clusters=self._list_clusters)
        self.mistake_patterns = SimpleNamespace(
            top_patterns=self._top_patterns,
            repeated_patterns=self._repeated_patterns,
        )
        self.learning_events = SimpleNamespace(list_since=self._list_since)
        self.profiles = SimpleNamespace(get_or_create=self._get_or_create_profile)
        self._due_items = due_items or []
        self._total_vocab = total_vocab or []
        self._skills = skills or {"grammar": 0.8, "vocabulary": 0.8, "fluency": 0.8}
        self._clusters = clusters or {}
        self._patterns = patterns or []
        self._repeated = repeated_patterns or []
        self._recent_events = recent_events or []
        self._profile = profile or SimpleNamespace(
            difficulty_preference="medium",
            retention_rate=0.8,
            content_preference="mixed",
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _list_due(self, user_id: int):
        return self._due_items

    async def _list_all(self, user_id: int, limit: int, offset: int):
        return self._total_vocab

    async def _latest_scores(self, user_id: int):
        return self._skills

    async def _list_clusters(self):
        return self._clusters

    async def _top_patterns(self, user_id: int, limit: int = 3):
        return self._patterns

    async def _repeated_patterns(self, user_id: int, threshold: int = 2, limit: int = 3):
        return self._repeated

    async def _list_since(self, user_id: int, since):
        return self._recent_events

    async def _get_or_create_profile(self, user_id: int):
        return self._profile


class FakePersonalizationService:
    def __init__(self, adaptation: PersonalizationAdaptation):
        self._adaptation = adaptation

    async def get_adaptation(self, user_id: int) -> PersonalizationAdaptation:
        return self._adaptation


def _factory_for(uow):
    return lambda: uow


def test_learning_engine_prioritizes_due_reviews():
    due_item = SimpleNamespace(
        source_text="hola",
        next_review_due=utc_now() - timedelta(days=3),
        interval=1,
    )
    total_vocab = [object()] * 30
    uow = FakeLearningEngineUOW(
        due_items=[due_item],
        total_vocab=total_vocab,
        recent_events=[SimpleNamespace(event_type="word_learned") for _ in range(3)],
    )
    engine = LearningEngine(_factory_for(uow), RetentionEngine())

    recommendation = run_async(engine.recommend(1))

    assert recommendation.action == "review_word"
    assert recommendation.target == "hola"
    assert recommendation.reason.startswith("1 items due")


def test_learning_engine_prioritizes_grammar_when_skill_is_weak():
    total_vocab = [object()] * 30
    uow = FakeLearningEngineUOW(
        total_vocab=total_vocab,
        skills={"grammar": 0.2, "vocabulary": 0.9, "fluency": 0.9},
    )
    engine = LearningEngine(_factory_for(uow), RetentionEngine())

    recommendation = run_async(engine.recommend(1))

    assert recommendation.action == "practice_grammar"
    assert recommendation.target == "grammar"


def test_learning_engine_uses_repeated_errors_for_conversation_drill():
    total_vocab = [object()] * 30
    repeated = [SimpleNamespace(pattern="verb tense confusion", count=3, category="repetition")]
    adaptation = PersonalizationAdaptation(
        lesson_difficulty="hard",
        review_frequency_multiplier=1.0,
        content_type="mixed",
    )
    uow = FakeLearningEngineUOW(
        total_vocab=total_vocab,
        skills={"grammar": 0.9, "vocabulary": 0.9, "fluency": 0.8},
        repeated_patterns=repeated,
    )
    engine = LearningEngine(
        _factory_for(uow),
        RetentionEngine(),
        FakePersonalizationService(adaptation),
    )

    recommendation = run_async(engine.recommend(1))

    assert recommendation.action == "conversation_drill"
    assert recommendation.target == "verb tense confusion"
    assert recommendation.lesson_difficulty == "hard"


def test_learning_engine_uses_retention_state_to_prioritize_low_friction_review():
    due_item = SimpleNamespace(
        source_text="bonjour",
        next_review_due=utc_now() - timedelta(days=2),
        interval=2,
    )
    total_vocab = [object()] * 40
    retention = SimpleNamespace(
        assess_user=lambda user_id: _retention_assessment("at-risk"),
    )
    uow = FakeLearningEngineUOW(
        due_items=[due_item],
        total_vocab=total_vocab,
        skills={"grammar": 0.9, "vocabulary": 0.9, "fluency": 0.9},
    )
    engine = LearningEngine(_factory_for(uow), retention)

    recommendation = run_async(engine.recommend(1))

    assert recommendation.action == "review_word"
    assert recommendation.target == "bonjour"
    assert "Retention state is at-risk" in recommendation.reason


async def _retention_assessment(state: str):
    return SimpleNamespace(
        state=state,
        drop_off_risk=0.6,
        session_frequency=1.0,
        current_streak=1,
        longest_streak=2,
        last_active_at=utc_now() - timedelta(days=5),
        is_high_engagement=False,
        suggested_actions=[],
    )
