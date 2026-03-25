from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.domain.errors import ConflictError
from vocablens.services.content_quality_gate_service import ContentQualityGateService
from vocablens.services.session_engine import SessionPhase, StructuredSession


class FakeContentQualityChecksRepo:
    def __init__(self):
        self.rows = []

    async def create(self, **kwargs):
        row = SimpleNamespace(id=len(self.rows) + 1, **kwargs)
        self.rows.append(row)
        return row


class FakeUOW:
    def __init__(self):
        self.content_quality_checks = FakeContentQualityChecksRepo()
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


class FakeContentQualityHealthSignalService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str = "global"):
        self.calls.append(scope_key)
        return {"scope_key": scope_key, "health": {"status": "healthy", "metrics": {}, "alerts": []}}


def _valid_session() -> StructuredSession:
    return StructuredSession(
        duration_seconds=220,
        mode="game_round",
        weak_area="grammar",
        lesson_target="past tense",
        goal_label="Fix one grammar pattern cleanly",
        success_criteria="Use the target cleanly in one short answer.",
        review_window_minutes=15,
        max_response_words=12,
        phases=[
            SessionPhase(
                name="warmup",
                duration_seconds=30,
                title="Warmup",
                directive="Quick recall only.",
                payload={
                    "mode": "review",
                    "prompt": "Warmup: translate 'hola' in one word.",
                    "expected_answer": "hello",
                    "accepted_keywords": ["hello"],
                    "target": "hola",
                },
            ),
            SessionPhase(
                name="core_challenge",
                duration_seconds=120,
                title="Core Challenge",
                directive="Rewrite the sentence correctly.",
                payload={
                    "mode": "rewrite",
                    "prompt": "Core round: rewrite 'I goed there yesterday' correctly.",
                    "expected_answer": "I went there yesterday.",
                    "accepted_keywords": ["went", "yesterday"],
                    "target": "past tense",
                },
            ),
            SessionPhase(
                name="correction_engine",
                duration_seconds=20,
                title="Correction",
                directive="Highlight exactly what changed.",
                payload={"accepted_keywords": ["went", "yesterday"]},
            ),
            SessionPhase(
                name="reinforcement",
                duration_seconds=35,
                title="Reinforcement",
                directive="Repeat the corrected form once.",
                payload={"corrected_answer": "I went there yesterday."},
            ),
            SessionPhase(
                name="win_moment",
                duration_seconds=15,
                title="Win",
                directive="Show visible progress before exit.",
                payload={},
            ),
        ],
    )


def test_content_quality_gate_persists_passed_check():
    uow = FakeUOW()
    health_signals = FakeContentQualityHealthSignalService()
    service = ContentQualityGateService(lambda: uow, health_signals)

    report = run_async(
        service.validate_structured_session(
            user_id=1,
            reference_id="sess_good",
            session=_valid_session(),
        )
    )

    assert report["status"] == "passed"
    assert uow.content_quality_checks.rows[0].status == "passed"
    assert health_signals.calls == ["global"]
    assert uow.commit_count == 1


def test_content_quality_gate_rejects_generic_target_contract():
    uow = FakeUOW()
    service = ContentQualityGateService(lambda: uow)
    session = _valid_session()
    session.phases[1].payload["target"] = "general"

    report = run_async(
        service.validate_structured_session(
            user_id=1,
            reference_id="sess_bad",
            session=session,
        )
    )

    assert report["status"] == "rejected"
    assert any(item["code"] == "target_contract_invalid" for item in report["violations"])
    assert uow.content_quality_checks.rows[0].status == "rejected"

    try:
        service.ensure_passed(report)
        assert False, "expected quality gate conflict"
    except ConflictError as exc:
        assert "quality validation" in str(exc)


def test_content_quality_gate_rejects_multiple_choice_answer_contract():
    uow = FakeUOW()
    service = ContentQualityGateService(lambda: uow)

    report = run_async(
        service.validate_generated_lesson(
            user_id=1,
            reference_id="lesson_bad",
            lesson={
                "exercises": [
                    {
                        "type": "multiple_choice",
                        "question": "Choose the travel word.",
                        "choices": ["bread", "water", "apple"],
                        "answer": "airport",
                    }
                ],
                "next_action": {"action": "learn_new_word", "target": "travel"},
            },
        )
    )

    assert report["status"] == "rejected"
    assert any(item["code"] == "answer_contract_invalid" for item in report["violations"])
    assert uow.content_quality_checks.rows[0].artifact_type == "generated_lesson"
