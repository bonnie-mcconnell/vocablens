from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.session_engine import SessionEngine


class FakeUOW:
    def __init__(self, due_items=None, skills=None, weak_clusters=None, mistakes=None):
        self.vocab = SimpleNamespace(list_due=self._list_due)
        self.skill_tracking = SimpleNamespace(latest_scores=self._latest_scores)
        self.knowledge_graph = SimpleNamespace(get_weak_clusters=self._get_weak_clusters)
        self.mistake_patterns = SimpleNamespace(top_patterns=self._top_patterns)
        self._due_items = due_items or []
        self._skills = skills or {"grammar": 0.4, "vocabulary": 0.7, "fluency": 0.8}
        self._weak_clusters = weak_clusters or []
        self._mistakes = mistakes or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _list_due(self, user_id: int):
        return self._due_items

    async def _latest_scores(self, user_id: int):
        return self._skills

    async def _get_weak_clusters(self, user_id: int, limit: int = 3):
        return self._weak_clusters[:limit]

    async def _top_patterns(self, user_id: int, limit: int = 3):
        return self._mistakes[:limit]


class FakeLearningEngine:
    def __init__(self, recommendation):
        self.recommendation = recommendation
        self.update_calls = []

    async def get_next_lesson(self, user_id: int):
        return self.recommendation

    async def update_knowledge(self, user_id: int, session_result):
        self.update_calls.append((user_id, session_result))
        return SimpleNamespace(reviewed_count=1, learned_count=0, weak_areas=session_result.weak_areas, updated_item_ids=[])


class FakeWowEngine:
    async def score_session(
        self,
        user_id: int,
        *,
        tutor_mode: bool,
        correction_feedback_count: int,
        new_words_count: int,
        grammar_mistake_count: int,
        session_turn_count: int,
        reply_length: int,
    ):
        return SimpleNamespace(score=0.78, qualifies=True, triggers={"paywall": True, "trial": False, "upsell": True})


class FakeGamificationService:
    async def summary(self, user_id: int):
        return SimpleNamespace(
            xp=120,
            level=2,
            badges=[SimpleNamespace(label="First Session"), SimpleNamespace(label="Accuracy Ace")],
        )


def _factory_for(uow):
    return lambda: uow


def test_session_engine_always_builds_structured_five_phase_round():
    due_item = SimpleNamespace(id=9, source_text="hola", translated_text="hello")
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar skill below threshold",
        skill_focus="grammar",
    )
    engine = SessionEngine(
        _factory_for(FakeUOW(due_items=[due_item])),
        FakeLearningEngine(recommendation),
        FakeWowEngine(),
        FakeGamificationService(),
    )

    session = run_async(engine.build_session(1))

    assert session.mode == "game_round"
    assert session.duration_seconds == 220
    assert [phase.name for phase in session.phases] == [
        "warmup",
        "core_challenge",
        "correction_engine",
        "reinforcement",
        "win_moment",
    ]
    assert session.phases[0].duration_seconds == 30
    assert session.phases[1].duration_seconds == 120
    assert "No open chat" in session.phases[1].directive


def test_session_engine_targets_weak_areas_in_core_challenge():
    recommendation = SimpleNamespace(
        action="conversation_drill",
        target="travel",
        reason="Address repeated errors",
        skill_focus="fluency",
    )
    engine = SessionEngine(
        _factory_for(FakeUOW(skills={"grammar": 0.9, "vocabulary": 0.8, "fluency": 0.3})),
        FakeLearningEngine(recommendation),
        FakeWowEngine(),
        FakeGamificationService(),
    )

    session = run_async(engine.build_session(1))

    assert session.weak_area == "fluency"
    core = session.phases[1]
    assert core.payload["skill_focus"] == "fluency"
    assert core.payload["target"] == "travel"
    assert core.payload["mode"] in {"sentence", "rewrite", "drill", "review"}


def test_session_engine_feedback_loop_returns_correction_reinforcement_and_win():
    due_item = SimpleNamespace(id=7, source_text="bonjour", translated_text="hello")
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar skill below threshold",
        skill_focus="grammar",
    )
    learning_engine = FakeLearningEngine(recommendation)
    engine = SessionEngine(
        _factory_for(FakeUOW(due_items=[due_item])),
        learning_engine,
        FakeWowEngine(),
        FakeGamificationService(),
    )

    session = run_async(engine.build_session(1))
    feedback = run_async(engine.evaluate_response(1, session, "I goed there yesterday"))

    assert feedback.structured is True
    assert feedback.targeted_weak_area == "grammar"
    assert feedback.corrected_response == "I went there yesterday."
    assert any("went" in mistake for mistake in feedback.highlighted_mistakes)
    assert feedback.reinforcement_prompt.startswith("Repeat exactly:")
    assert "slight variation" in feedback.variation_prompt
    assert "Wow score" in feedback.win_message
    assert feedback.xp_preview == 145
    assert len(learning_engine.update_calls) == 1
