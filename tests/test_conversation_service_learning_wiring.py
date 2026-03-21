from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.providers.llm.base import LLMTextResult, LLMUsage
from vocablens.services.conversation_service import ConversationService


class FakeLLM:
    async def generate_with_usage(self, prompt: str):
        return LLMTextResult(content="Tutor reply", usage=LLMUsage(total_tokens=10))


class FakeUOW:
    def __init__(self):
        self.conversation = SimpleNamespace(save_turn=self._save_turn)
        self.profiles = SimpleNamespace(get_or_create=self._get_or_create)
        self.mistake_patterns = SimpleNamespace(top_patterns=self._top_patterns)
        self.vocab = SimpleNamespace(list_all=self._list_all)
        self.saved_turns = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _save_turn(self, user_id: int, role: str, message: str, created_at=None):
        self.saved_turns.append((user_id, role, message))

    async def _get_or_create(self, user_id: int):
        return SimpleNamespace(difficulty_preference="medium", content_preference="mixed")

    async def _top_patterns(self, user_id: int, limit: int = 5):
        return [SimpleNamespace(pattern="verb tense")]

    async def _list_all(self, user_id: int, limit: int, offset: int):
        return [
            SimpleNamespace(source_text="hello"),
            SimpleNamespace(source_text="goodbye"),
        ]


class FakeBrain:
    async def process_message(self, user_id: int, message: str, language: str, explanation_quality: str = "premium"):
        return {
            "analysis": {
                "grammar_mistakes": ["use past tense"],
                "vocab_misuse": ["wrong preposition"],
                "repeated_errors": [{"pattern": "use past tense", "category": "grammar"}],
            },
            "drills": [],
            "correction_feedback": ["Use the past tense here."],
            "thinking_explanation": None,
        }


class FakeMemory:
    def __init__(self):
        self.memory = {1: []}

    def get_recent_context(self, user_id: int):
        return []

    def store_turn(self, user_id: int, user_message: str, reply: str):
        self.memory.setdefault(user_id, []).extend([user_message, reply])


class FakeVocabExtractor:
    async def process_message(self, user_id: int, user_message: str, source_lang: str, target_lang: str):
        return ["hola"]


class FakeSkillTracker:
    def __init__(self):
        self.profile = {"grammar": 0.6, "vocabulary": 0.7, "fluency": 0.8}

    def get_skill_profile(self, user_id: int):
        return dict(self.profile)


class FakeLearningEvents:
    def __init__(self):
        self.calls = []

    async def record(self, event_type: str, user_id: int, payload: dict):
        self.calls.append((event_type, user_id, payload))


class FakeLearningEngine:
    def __init__(self):
        self.recommendation_calls = []
        self.update_calls = []

    async def recommend(self, user_id: int):
        self.recommendation_calls.append(user_id)
        return SimpleNamespace(
            action="conversation_drill",
            reason="Address repeated errors",
            lesson_difficulty="medium",
            content_type="conversation",
            target="travel",
            skill_focus="fluency",
        )

    async def update_knowledge(self, user_id: int, session_result):
        self.update_calls.append((user_id, session_result))
        return SimpleNamespace(reviewed_count=0, learned_count=0, weak_areas=session_result.weak_areas, updated_item_ids=[])


class FakeFeatures:
    tier = "pro"
    tutor_depth = "standard"
    explanation_quality = "standard"


class FakeSubscriptions:
    async def get_features(self, user_id: int):
        return FakeFeatures()

    async def record_feature_gate(self, **kwargs):
        return None


class FakeEventService:
    def __init__(self):
        self.calls = []

    async def track_event(self, user_id: int, event_type: str, payload: dict):
        self.calls.append((user_id, event_type, payload))


class FakePaywall:
    async def evaluate(self, user_id: int, wow_moment: bool = False, wow_score: float = 0.0):
        return None


class FakeWow:
    async def score_session(
        self,
        user_id: int,
        tutor_mode: bool,
        correction_feedback_count: int,
        new_words_count: int,
        grammar_mistake_count: int,
        session_turn_count: int,
        reply_length: int,
    ):
        return SimpleNamespace(
            score=0.8,
            qualifies=True,
            tutor_interaction_score=0.4,
            accuracy_improvement_score=0.2,
            engagement_score=0.2,
            trial_recommended=True,
            upsell_recommended=True,
        )


def test_conversation_service_updates_learning_engine_after_reply():
    uow = FakeUOW()
    learning_engine = FakeLearningEngine()
    service = ConversationService(
        llm=FakeLLM(),
        uow_factory=lambda: uow,
        brain=FakeBrain(),
        memory=FakeMemory(),
        vocab_extractor=FakeVocabExtractor(),
        skill_tracker=FakeSkillTracker(),
        learning_events=FakeLearningEvents(),
        learning_engine=learning_engine,
        tutor_mode_service=None,
        subscription_service=FakeSubscriptions(),
        event_service=FakeEventService(),
        paywall_service=FakePaywall(),
        wow_engine=FakeWow(),
    )

    payload = run_async(service.generate_reply(1, "I goed there", "en", "es", tutor_mode=True))

    assert payload["reply"] == "Tutor reply"
    assert len(learning_engine.update_calls) == 1
    user_id, session_result = learning_engine.update_calls[0]
    assert user_id == 1
    assert session_result.skill_scores["grammar"] == 0.6
    assert any(item["category"] == "grammar" for item in session_result.mistakes)
    assert "use past tense" in session_result.weak_areas
    assert "travel" in session_result.weak_areas
