import json
from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.providers.llm.base import LLMJsonResult, LLMUsage
from vocablens.services.mistake_engine import MistakeEngine
from vocablens.services.personalization_service import PersonalizationService
from vocablens.services.tutor_mode_service import TutorModeService


class FakeMistakePatternRepo:
    def __init__(self):
        self.records = {}

    async def record(self, user_id: int, category: str, pattern: str):
        key = (user_id, category, pattern)
        self.records[key] = self.records.get(key, 0) + 1

    async def repeated_patterns(self, user_id: int, threshold: int = 2, limit: int = 5):
        rows = []
        for (stored_user, category, pattern), count in self.records.items():
            if stored_user == user_id and count >= threshold:
                rows.append(SimpleNamespace(pattern=pattern, count=count, category=category))
        return rows[:limit]

    async def top_patterns(self, user_id: int, limit: int = 5):
        ranked = []
        for (stored_user, category, pattern), count in self.records.items():
            if stored_user == user_id:
                ranked.append(SimpleNamespace(pattern=pattern, count=count, category=category))
        ranked.sort(key=lambda item: item.count, reverse=True)
        return ranked[:limit]


class FakeProfileRepo:
    def __init__(self, profile=None):
        self.profile = profile or SimpleNamespace(
            user_id=1,
            learning_speed=1.0,
            retention_rate=0.8,
            difficulty_preference="medium",
            content_preference="mixed",
            updated_at=utc_now() - timedelta(days=1),
        )

    async def get_or_create(self, user_id: int):
        return self.profile

    async def update(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            if value is not None:
                setattr(self.profile, key, value)
        self.profile.updated_at = utc_now()


class FakeLearningEventsRepo:
    def __init__(self, events):
        self.events = events

    async def list_since(self, user_id: int, since):
        return self.events


class FakeUOW:
    def __init__(self, mistakes=None, profiles=None, learning_events=None):
        self.mistake_patterns = mistakes or FakeMistakePatternRepo()
        self.profiles = profiles or FakeProfileRepo()
        self.learning_events = learning_events or FakeLearningEventsRepo([])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeLLM:
    async def generate_json_with_usage(self, prompt: str):
        return LLMJsonResult(
            content={
                "grammar_mistakes": ["use past tense"],
                "vocab_misuse": ["wrong preposition"],
                "repeated_errors": ["use past tense"],
                "suggestions": ["Say 'I went' instead of 'I goed'"],
            },
            usage=LLMUsage(total_tokens=12),
        )


def test_mistake_engine_detects_and_stores_patterns():
    uow = FakeUOW()
    engine = MistakeEngine(FakeLLM(), lambda: uow)

    first = run_async(engine.analyze(1, "I goed there", "en"))
    second = run_async(engine.analyze(1, "I goed again", "en"))

    assert first["grammar_mistakes"] == ["use past tense"]
    assert first["vocab_misuse"] == ["wrong preposition"]
    assert "Grammar correction: use past tense" in first["correction_feedback"][0]
    assert second["repeated_errors"][0]["pattern"] == "use past tense"
    assert second["repeated_errors"][0]["count"] == 2


def test_personalization_updates_from_learning_signals():
    profile_repo = FakeProfileRepo()
    events = [
        SimpleNamespace(event_type="word_reviewed", payload_json=json.dumps({"quality": 1})),
        SimpleNamespace(event_type="word_reviewed", payload_json=json.dumps({"quality": 2})),
        SimpleNamespace(event_type="conversation_turn", payload_json="{}"),
        SimpleNamespace(event_type="conversation_turn", payload_json="{}"),
    ]
    mistakes = FakeMistakePatternRepo()
    run_async(mistakes.record(1, "grammar", "verb tense"))
    run_async(mistakes.record(1, "grammar", "verb tense"))
    uow = FakeUOW(
        mistakes=mistakes,
        profiles=profile_repo,
        learning_events=FakeLearningEventsRepo(events),
    )
    service = PersonalizationService(lambda: uow)

    run_async(service.update_from_learning_signals(1))
    adaptation = run_async(service.get_adaptation(1))

    assert profile_repo.profile.retention_rate < 0.5
    assert profile_repo.profile.difficulty_preference == "easy"
    assert profile_repo.profile.content_preference == "grammar"
    assert adaptation.lesson_difficulty == "easy"
    assert adaptation.review_frequency_multiplier < 1.0


def test_tutor_mode_service_returns_live_corrections_and_memory():
    service = TutorModeService()
    recommendation = SimpleNamespace(
        action="conversation_drill",
        reason="Address repeated errors",
        lesson_difficulty="hard",
        content_type="conversation",
    )
    context = service.build_context(
        profile=SimpleNamespace(difficulty_preference="hard", content_preference="conversation"),
        patterns=[SimpleNamespace(pattern="verb tense"), SimpleNamespace(pattern="article usage")],
        recommendation=recommendation,
    )

    payload = service.response_payload(
        brain_output={
            "analysis": {"grammar_mistakes": ["verb tense"]},
            "drills": {"focus": "Practice corrected sentences"},
            "correction_feedback": ["Use the past tense here.", "Drop the extra article."],
        },
        recommendation=recommendation,
        context=context,
        reply="Let's try that again.",
    )

    assert payload["tutor_mode"] is True
    assert payload["live_corrections"] == ["Use the past tense here.", "Drop the extra article."]
    assert payload["inline_explanations"][-1] == "Practice corrected sentences"
    assert payload["mistake_memory"] == ["verb tense", "article usage"]
