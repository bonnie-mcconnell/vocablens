from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.domain.models import VocabularyItem
from vocablens.services.learning_engine import (
    LearningEngine,
    ReviewedKnowledge,
    SessionResult,
)
from vocablens.services.personalization_service import PersonalizationAdaptation
from vocablens.services.retention_engine import RetentionEngine


class FakeLearningEvents:
    def __init__(self):
        self.records = []

    async def list_since(self, user_id: int, since):
        return []

    async def record(self, user_id: int, event_type: str, payload_json: str):
        self.records.append((user_id, event_type, payload_json))


class FakeSkillTracking:
    def __init__(self, skills=None):
        self.skills = skills or {"grammar": 0.8, "vocabulary": 0.8, "fluency": 0.8}
        self.saved = []

    async def latest_scores(self, user_id: int):
        return self.skills

    async def record(self, user_id: int, skill: str, score: float, created_at=None):
        self.saved.append((user_id, skill, score))
        self.skills[skill] = score


class FakeMistakePatterns:
    def __init__(self, patterns=None, repeated=None):
        self._patterns = patterns or []
        self._repeated = repeated or []
        self.saved = []

    async def top_patterns(self, user_id: int, limit: int = 3):
        return self._patterns[:limit]

    async def repeated_patterns(self, user_id: int, threshold: int = 2, limit: int = 3):
        return self._repeated[:limit]

    async def record(self, user_id: int, category: str, pattern: str):
        self.saved.append((user_id, category, pattern))


class FakeProfiles:
    def __init__(self, profile=None):
        self._profile = profile or SimpleNamespace(
            difficulty_preference="medium",
            retention_rate=0.8,
            content_preference="mixed",
        )

    async def get_or_create(self, user_id: int):
        return self._profile


class FakeLearningStates:
    def __init__(self, state=None):
        self.state = state or SimpleNamespace(
            skills={},
            weak_areas=[],
            mastery_percent=0.0,
            accuracy_rate=0.0,
            response_speed_seconds=0.0,
        )
        self.updated = []

    async def get_or_create(self, user_id: int):
        return self.state

    async def update(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            setattr(self.state, key, value)
        self.updated.append((user_id, kwargs))
        return self.state


class FakeEngagementStates:
    def __init__(self, state=None):
        self.state = state or SimpleNamespace(
            current_streak=0,
            longest_streak=0,
            momentum_score=0.0,
            total_sessions=0,
            sessions_last_3_days=0,
            last_session_at=None,
            shields_used_this_week=0,
            daily_mission_completed_at=None,
            interaction_stats={},
            updated_at=utc_now(),
        )
        self.updated = []

    async def get_or_create(self, user_id: int):
        return self.state

    async def update(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            setattr(self.state, key, value)
        self.updated.append((user_id, kwargs))
        return self.state


class FakeProgressStates:
    def __init__(self, state=None):
        self.state = state or SimpleNamespace(xp=0, level=1, milestones=[], updated_at=utc_now())
        self.updated = []

    async def get_or_create(self, user_id: int):
        return self.state

    async def update(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            setattr(self.state, key, value)
        self.updated.append((user_id, kwargs))
        return self.state


class FakeVocabularyRepo:
    def __init__(self, due_items=None, total_vocab=None):
        self.due_items = due_items or []
        self.total_vocab = total_vocab or []
        self.updated = []

    async def list_due(self, user_id: int):
        return self.due_items

    async def list_all(self, user_id: int, limit: int, offset: int):
        return self.total_vocab

    async def get(self, user_id: int, item_id: int):
        for item in self.due_items + self.total_vocab:
            if getattr(item, "id", None) == item_id:
                return item
        return None

    async def update(self, item):
        self.updated.append(item)
        for bucket in (self.due_items, self.total_vocab):
            for index, existing in enumerate(bucket):
                if getattr(existing, "id", None) == item.id:
                    bucket[index] = item
        return item


class FakeKnowledgeGraph:
    def __init__(self, clusters=None, weak_clusters=None):
        self._clusters = clusters or {}
        self._weak_clusters = weak_clusters or []

    async def list_clusters(self, user_id: int):
        return self._clusters

    async def get_weak_clusters(self, user_id: int, limit: int = 3):
        return self._weak_clusters[:limit]


class FakeLearningEngineUOW:
    def __init__(
        self,
        due_items=None,
        total_vocab=None,
        skills=None,
        clusters=None,
        weak_clusters=None,
        patterns=None,
        repeated_patterns=None,
        recent_events=None,
        profile=None,
    ):
        self.vocab = FakeVocabularyRepo(due_items=due_items, total_vocab=total_vocab)
        self.skill_tracking = FakeSkillTracking(skills)
        self.knowledge_graph = FakeKnowledgeGraph(clusters=clusters, weak_clusters=weak_clusters)
        self.mistake_patterns = FakeMistakePatterns(patterns=patterns, repeated=repeated_patterns)
        self.learning_events = FakeLearningEvents()
        self.events = SimpleNamespace(record=self._record_event, records=[])
        self.decision_traces = SimpleNamespace(create=self._create_trace, records=[])
        self.profiles = FakeProfiles(profile)
        self.learning_states = FakeLearningStates()
        self.engagement_states = FakeEngagementStates()
        self.progress_states = FakeProgressStates()
        self._recent_events = recent_events or []

    async def __aenter__(self):
        self.learning_events.list_since = self._list_since
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _list_since(self, user_id: int, since):
        return self._recent_events

    async def _record_event(self, *, user_id: int, event_type: str, payload: dict, created_at=None):
        self.events.records.append((user_id, event_type, payload))

    async def _create_trace(self, **kwargs):
        self.decision_traces.records.append(kwargs)
        return SimpleNamespace(id=len(self.decision_traces.records), created_at=utc_now(), **kwargs)


class FakeEventService:
    def __init__(self):
        self.events = []

    async def track_event(self, user_id: int, event_type: str, payload: dict | None = None):
        self.events.append((user_id, event_type, payload or {}))


class FakePersonalizationService:
    def __init__(self, adaptation: PersonalizationAdaptation):
        self._adaptation = adaptation

    async def get_adaptation(self, user_id: int) -> PersonalizationAdaptation:
        return self._adaptation


class FakeLearningHealthSignalService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str = "global"):
        self.calls.append(scope_key)
        return {"scope_key": scope_key, "health": {"status": "healthy", "metrics": {}, "alerts": []}}


def _factory_for(uow):
    return lambda: uow


def _vocab_item(
    *,
    item_id: int,
    source_text: str,
    review_count: int = 2,
    ease_factor: float = 2.1,
    repetitions: int = 1,
    interval: int = 2,
    success_rate: float = 0.5,
    decay_score: float = 0.0,
    next_review_due=None,
):
    return VocabularyItem(
        id=item_id,
        source_text=source_text,
        translated_text=f"{source_text}-translated",
        source_lang="es",
        target_lang="en",
        created_at=utc_now() - timedelta(days=10),
        last_reviewed_at=utc_now() - timedelta(days=interval),
        review_count=review_count,
        ease_factor=ease_factor,
        interval=interval,
        repetitions=repetitions,
        next_review_due=next_review_due,
        success_rate=success_rate,
        decay_score=decay_score,
    )


def test_learning_engine_prioritizes_high_decay_due_reviews():
    low_decay = _vocab_item(
        item_id=1,
        source_text="hola",
        success_rate=0.9,
        decay_score=0.2,
        next_review_due=utc_now() - timedelta(days=3),
    )
    high_decay = _vocab_item(
        item_id=2,
        source_text="adios",
        success_rate=0.35,
        decay_score=0.9,
        next_review_due=utc_now() - timedelta(days=1),
    )
    total_vocab = [object()] * 30
    uow = FakeLearningEngineUOW(
        due_items=[low_decay, high_decay],
        total_vocab=total_vocab,
        recent_events=[SimpleNamespace(event_type="word_learned") for _ in range(3)],
    )
    health_signals = FakeLearningHealthSignalService()
    engine = LearningEngine(_factory_for(uow), RetentionEngine(), health_signal_service=health_signals)

    recommendation = run_async(engine.get_next_lesson(1))

    assert recommendation.action == "review_word"
    assert recommendation.target == "adios"
    assert recommendation.due_items_count == 2
    assert recommendation.review_priority > 0.5
    assert recommendation.goal_label == "Bring a due word back into active memory"
    assert recommendation.review_window_minutes == 5
    assert health_signals.calls == ["global"]


def test_learning_engine_prioritizes_grammar_when_skill_is_weak():
    total_vocab = [object()] * 30
    uow = FakeLearningEngineUOW(
        total_vocab=total_vocab,
        skills={"grammar": 0.2, "vocabulary": 0.9, "fluency": 0.9},
    )
    engine = LearningEngine(_factory_for(uow), RetentionEngine())

    recommendation = run_async(engine.get_next_lesson(1))

    assert recommendation.action == "practice_grammar"
    assert recommendation.target == "grammar"
    assert recommendation.skill_focus == "grammar"
    assert "grammar pattern" in recommendation.goal_label.lower()


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

    recommendation = run_async(engine.get_next_lesson(1))

    assert recommendation.action == "conversation_drill"
    assert recommendation.target == "verb tense confusion"
    assert recommendation.lesson_difficulty == "hard"
    assert recommendation.review_window_minutes == 20


def test_learning_engine_prefers_weak_cluster_for_cluster_based_learning():
    total_vocab = [object()] * 30
    uow = FakeLearningEngineUOW(
        total_vocab=total_vocab,
        skills={"grammar": 0.9, "vocabulary": 0.7, "fluency": 0.8},
        clusters={
            "travel": {"words": ["bonjour", "salut"], "related_words": ["salut"], "grammar_links": ["greeting"]},
            "food": {"words": ["manger"], "related_words": [], "grammar_links": ["verb infinitive"]},
        },
        weak_clusters=[{"cluster": "travel", "weakness": 1.3, "words": ["bonjour", "salut", "aeroport"]}],
    )
    engine = LearningEngine(_factory_for(uow), RetentionEngine())

    recommendation = run_async(engine.get_next_lesson(1))

    assert recommendation.action == "learn_new_word"
    assert recommendation.target == "travel"
    assert "related words" in recommendation.reason


def test_learning_engine_uses_retention_state_to_prioritize_low_friction_review():
    due_item = _vocab_item(
        item_id=1,
        source_text="bonjour",
        next_review_due=utc_now() - timedelta(days=2),
        decay_score=0.6,
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

    recommendation = run_async(engine.get_next_lesson(1))

    assert recommendation.action == "review_word"
    assert recommendation.target == "bonjour"
    assert "Retention is slipping" in recommendation.reason


def test_update_knowledge_updates_decay_and_emits_event():
    item = _vocab_item(
        item_id=7,
        source_text="hola",
        review_count=1,
        repetitions=0,
        interval=1,
        success_rate=0.4,
        decay_score=0.8,
        next_review_due=utc_now() - timedelta(days=1),
    )
    uow = FakeLearningEngineUOW(
        due_items=[item],
        total_vocab=[item],
        skills={"grammar": 0.6, "vocabulary": 0.5, "fluency": 0.4},
    )
    event_service = FakeEventService()
    health_signals = FakeLearningHealthSignalService()
    engine = LearningEngine(
        _factory_for(uow),
        RetentionEngine(),
        event_service=event_service,
        health_signal_service=health_signals,
    )

    summary = run_async(
        engine.update_knowledge(
            1,
            SessionResult(
                reviewed_items=[ReviewedKnowledge(item_id=7, quality=5, response_accuracy=0.95)],
                skill_scores={"grammar": 0.72},
                mistakes=[{"category": "grammar", "pattern": "article omission"}],
                weak_areas=["articles"],
            ),
        )
    )

    assert summary.reviewed_count == 1
    assert summary.updated_item_ids == [7]
    updated = uow.vocab.updated[-1]
    assert updated.success_rate > 0.6
    assert updated.decay_score < 0.5
    assert updated.last_seen_at is not None
    assert uow.skill_tracking.saved[-1] == (1, "grammar", 0.72)
    assert uow.mistake_patterns.saved[-1] == (1, "grammar", "article omission")
    assert uow.learning_states.state.mastery_percent >= 0.0
    assert uow.engagement_states.state.total_sessions == 1
    assert uow.progress_states.state.xp > 0
    assert event_service.events[-1][1] == "knowledge_updated"
    assert uow.events.records[-1][1] == "knowledge_updated"
    assert uow.decision_traces.records[-1]["trace_type"] == "knowledge_update"
    assert health_signals.calls == ["global"]


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
