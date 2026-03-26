from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.domain.errors import ConflictError
from vocablens.services.session_engine import SessionEngine


class FakeUOW:
    def __init__(self, due_items=None, skills=None, weak_clusters=None, mistakes=None):
        self.vocab = SimpleNamespace(list_due=self._list_due)
        self.skill_tracking = SimpleNamespace(latest_scores=self._latest_scores)
        self.knowledge_graph = SimpleNamespace(get_weak_clusters=self._get_weak_clusters)
        self.mistake_patterns = SimpleNamespace(top_patterns=self._top_patterns)
        self.learning_sessions = SimpleNamespace(
            create=self._create_session,
            get=self._get_session,
            get_attempt_by_submission=self._get_attempt_by_submission,
            create_attempt_once=self._create_attempt_once,
            update_attempt_feedback=self._update_attempt_feedback,
            mark_completed_once=self._mark_completed_once,
            mark_expired=self._mark_expired,
        )
        self.events = SimpleNamespace(record=self._record_event, records=[])
        self.decision_traces = SimpleNamespace(create=self._create_trace, records=[])
        self._due_items = due_items or []
        self._skills = skills or {"grammar": 0.4, "vocabulary": 0.7, "fluency": 0.8}
        self._weak_clusters = weak_clusters or []
        self._mistakes = mistakes or []
        self.created_sessions = {}
        self.attempts = []
        self.completed_sessions = []
        self.expired_sessions = []

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

    async def _create_session(self, **kwargs):
        record = SimpleNamespace(**kwargs, status="active", completed_at=None, last_evaluated_at=None, evaluation_count=0)
        self.created_sessions[kwargs["session_id"]] = record
        return record

    async def _get_session(self, *, user_id: int, session_id: str):
        session = self.created_sessions.get(session_id)
        if session is None or session.user_id != user_id:
            return None
        return session

    async def _create_attempt_once(self, **kwargs):
        existing = await self._get_attempt_by_submission(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            submission_id=kwargs["submission_id"],
        )
        if existing is not None:
            return existing, False
        attempt = {"id": len(self.attempts) + 1, **kwargs}
        self.attempts.append(attempt)
        return SimpleNamespace(created_at=None, **attempt), True

    async def _update_attempt_feedback(self, attempt_id: int, *, feedback_payload: dict):
        for attempt in self.attempts:
            if attempt["id"] == attempt_id:
                attempt["feedback_payload"] = dict(feedback_payload)
                return SimpleNamespace(created_at=None, **attempt)
        raise AssertionError(f"missing attempt {attempt_id}")

    async def _get_attempt_by_submission(self, *, session_id: str, user_id: int, submission_id: str):
        for attempt in self.attempts:
            if (
                attempt["session_id"] == session_id
                and attempt["user_id"] == user_id
                and attempt["submission_id"] == submission_id
            ):
                return SimpleNamespace(created_at=None, **attempt)
        return None

    async def _mark_completed_once(self, *, user_id: int, session_id: str, completed_at):
        session = self.created_sessions[session_id]
        if session.status != "active":
            return session, False
        session.status = "completed"
        session.completed_at = completed_at
        session.last_evaluated_at = completed_at
        session.evaluation_count += 1
        self.completed_sessions.append(session_id)
        return session, True

    async def _mark_expired(self, *, user_id: int, session_id: str, expired_at):
        session = self.created_sessions[session_id]
        session.status = "expired"
        session.last_evaluated_at = expired_at
        self.expired_sessions.append(session_id)
        return session

    async def _record_event(self, *, user_id: int, event_type: str, payload: dict, created_at=None):
        self.events.records.append((user_id, event_type, payload))

    async def _create_trace(self, **kwargs):
        self.decision_traces.records.append(kwargs)
        return SimpleNamespace(id=len(self.decision_traces.records), created_at=None, **kwargs)


class FakeLearningEngine:
    def __init__(self, recommendation):
        self.recommendation = recommendation
        self.update_calls = []

    async def get_next_lesson(self, user_id: int):
        return self.recommendation

    async def update_knowledge(self, user_id: int, session_result):
        self.update_calls.append((user_id, session_result))
        return SimpleNamespace(reviewed_count=1, learned_count=0, weak_areas=session_result.weak_areas, updated_item_ids=[])

    async def apply_session_result(self, user_id: int, session_result, *, source: str, uow=None, reference_id: str | None = None):
        self.update_calls.append((user_id, session_result, source, reference_id))
        return SimpleNamespace(
            reviewed_count=1,
            learned_count=0,
            weak_areas=session_result.weak_areas,
            updated_item_ids=[],
            interaction_stats={"lessons_completed": 1, "reviews_completed": 1},
        )


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


class FakeEventService:
    def __init__(self):
        self.events = []

    async def track_event(self, user_id: int, event_type: str, payload: dict | None = None):
        self.events.append((user_id, event_type, payload or {}))


class FakeSessionHealthSignalService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str = "global"):
        self.calls.append(scope_key)
        return {"scope_key": scope_key, "health": {"status": "healthy", "metrics": {}, "alerts": []}}


class FakeContentQualityGateService:
    def __init__(self, *, reject: bool = False):
        self.reject = reject
        self.calls = []

    async def validate_structured_session(self, *, user_id: int, reference_id: str, session, source: str = "session_engine"):
        self.calls.append((user_id, reference_id, source))
        return {
            "status": "rejected" if self.reject else "passed",
            "score": 0.2 if self.reject else 1.0,
            "violations": [{"code": "target_contract_invalid", "severity": "critical"}] if self.reject else [],
            "artifact_summary": {"mode": session.mode},
        }

    def ensure_passed(self, report: dict):
        if report["status"] == "rejected":
            raise ConflictError("Session content failed quality validation")


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
    assert session.goal_label
    assert session.success_criteria
    assert session.review_window_minutes == 15
    assert session.max_response_words == 12
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
    assert "improved" in feedback.progress_summary.lower()
    assert "next" in feedback.recommended_next_step.lower() or "repeat" in feedback.recommended_next_step.lower()
    assert feedback.xp_preview == 145
    assert learning_engine.update_calls == []


def test_session_engine_persists_server_owned_session_and_evaluates_by_session_id():
    due_item = SimpleNamespace(id=12, source_text="hola", translated_text="hello")
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar skill below threshold",
        skill_focus="grammar",
    )
    uow = FakeUOW(due_items=[due_item])
    learning_engine = FakeLearningEngine(recommendation)
    health_signals = FakeSessionHealthSignalService()
    engine = SessionEngine(
        _factory_for(uow),
        learning_engine,
        FakeWowEngine(),
        FakeGamificationService(),
        health_signal_service=health_signals,
    )

    started = run_async(engine.start_session(1))
    feedback = run_async(
        engine.evaluate_session(
            1,
            started["session_id"],
            "I goed there yesterday",
            submission_id="submit_12345678",
            contract_version=started["contract_version"],
        )
    )

    assert started["status"] == "active"
    assert started["contract_version"] == "v2"
    assert started["session_id"] in uow.created_sessions
    assert uow.created_sessions[started["session_id"]].contract_version == "v2"
    assert uow.attempts[0]["session_id"] == started["session_id"]
    assert uow.attempts[0]["submission_id"] == "submit_12345678"
    assert uow.attempts[0]["feedback_payload"]["knowledge_update"]["reviewed_count"] == 1
    assert started["session_id"] in uow.completed_sessions
    assert uow.events.records[-1][1] == "lesson_completed"
    assert uow.decision_traces.records[-1]["trace_type"] == "session_evaluation"
    assert feedback.corrected_response == "I went there yesterday."
    assert health_signals.calls == ["global", "global"]


def test_session_engine_replays_same_submission_idempotently():
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar skill below threshold",
        skill_focus="grammar",
    )
    uow = FakeUOW()
    engine = SessionEngine(
        _factory_for(uow),
        FakeLearningEngine(recommendation),
        FakeWowEngine(),
        FakeGamificationService(),
    )

    started = run_async(engine.start_session(2))
    first = run_async(
        engine.evaluate_session(
            2,
            started["session_id"],
            "I goed there yesterday",
            submission_id="submit_same_1",
            contract_version=started["contract_version"],
        )
    )
    second = run_async(
        engine.evaluate_session(
            2,
            started["session_id"],
            "I goed there yesterday",
            submission_id="submit_same_1",
            contract_version=started["contract_version"],
        )
    )

    assert len(uow.attempts) == 1
    assert first.corrected_response == second.corrected_response


def test_session_engine_rejects_distinct_submission_after_completion():
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar skill below threshold",
        skill_focus="grammar",
    )
    uow = FakeUOW()
    event_service = FakeEventService()
    engine = SessionEngine(
        _factory_for(uow),
        FakeLearningEngine(recommendation),
        FakeWowEngine(),
        FakeGamificationService(),
        event_service=event_service,
    )

    started = run_async(engine.start_session(7))
    run_async(
        engine.evaluate_session(
            7,
            started["session_id"],
            "I goed there yesterday",
            submission_id="submit_original",
            contract_version=started["contract_version"],
        )
    )

    try:
        run_async(
            engine.evaluate_session(
                7,
                started["session_id"],
                "I went there yesterday",
                submission_id="submit_second",
                contract_version=started["contract_version"],
            )
        )
        assert False, "expected completed session conflict"
    except ConflictError as exc:
        assert "completed" in str(exc)

    assert len(uow.attempts) == 1
    assert event_service.events[-1][2]["reason"] == "already_completed"


def test_session_engine_rejects_stale_contract_and_long_submission():
    recommendation = SimpleNamespace(
        action="review_word",
        target="travel",
        reason="Review is due",
        skill_focus="vocabulary",
    )
    uow = FakeUOW()
    event_service = FakeEventService()
    engine = SessionEngine(
        _factory_for(uow),
        FakeLearningEngine(recommendation),
        FakeWowEngine(),
        FakeGamificationService(),
        event_service=event_service,
    )
    started = run_async(engine.start_session(3))

    from vocablens.domain.errors import ConflictError

    try:
        run_async(
            engine.evaluate_session(
                3,
                started["session_id"],
                "travel",
                submission_id="submit_bad_contract",
                contract_version="v1",
            )
        )
        assert False, "expected stale contract conflict"
    except ConflictError as exc:
        assert "stale" in str(exc)

    try:
        run_async(
            engine.evaluate_session(
                3,
                started["session_id"],
                "this answer is much too long for a one word review round today",
                submission_id="submit_too_long",
                contract_version=started["contract_version"],
            )
        )
        assert False, "expected format conflict"
    except ConflictError as exc:
        assert "format" in str(exc) or "allowed length" in str(exc)

    assert event_service.events[1][1] == "session_submission_rejected"
    assert event_service.events[1][2]["reason"] == "stale_contract"
    assert event_service.events[2][2]["reason"] == "response_too_long"


def test_session_engine_records_health_after_expired_submission():
    recommendation = SimpleNamespace(
        action="review_word",
        target="travel",
        reason="Review is due",
        skill_focus="vocabulary",
    )
    uow = FakeUOW()
    event_service = FakeEventService()
    health_signals = FakeSessionHealthSignalService()
    engine = SessionEngine(
        _factory_for(uow),
        FakeLearningEngine(recommendation),
        FakeWowEngine(),
        FakeGamificationService(),
        event_service=event_service,
        health_signal_service=health_signals,
    )
    started = run_async(engine.start_session(4))
    uow.created_sessions[started["session_id"]].expires_at = utc_now()

    from vocablens.domain.errors import ConflictError

    try:
        run_async(
            engine.evaluate_session(
                4,
                started["session_id"],
                "travel",
                submission_id="submit_expired",
                contract_version=started["contract_version"],
            )
        )
        assert False, "expected expired session conflict"
    except ConflictError as exc:
        assert "expired" in str(exc)

    assert started["session_id"] in uow.expired_sessions
    assert event_service.events[-1][2]["reason"] == "session_expired"
    assert health_signals.calls == ["global", "global"]


def test_session_engine_blocks_rejected_content_before_persisting_session():
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar skill below threshold",
        skill_focus="grammar",
    )
    uow = FakeUOW()
    event_service = FakeEventService()
    content_gate = FakeContentQualityGateService(reject=True)
    engine = SessionEngine(
        _factory_for(uow),
        FakeLearningEngine(recommendation),
        FakeWowEngine(),
        FakeGamificationService(),
        event_service=event_service,
        content_quality_gate_service=content_gate,
    )

    try:
        run_async(engine.start_session(5))
        assert False, "expected content quality conflict"
    except ConflictError as exc:
        assert "quality validation" in str(exc)

    assert content_gate.calls
    assert uow.created_sessions == {}
    assert event_service.events[0][1] == "session_generation_rejected"
    assert event_service.events[0][2]["reason"] == "quality_validation_failed"
