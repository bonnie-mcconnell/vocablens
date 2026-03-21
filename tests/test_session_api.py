from fastapi.testclient import TestClient

from tests.conftest import make_user
from vocablens.api.dependencies import get_current_user, get_session_engine
from vocablens.main import create_app


class FakeSessionEngine:
    async def build_session(self, user_id: int):
        return self.from_payload(
            {
                "duration_seconds": 220,
                "mode": "game_round",
                "weak_area": "grammar",
                "lesson_target": "past tense",
                "phases": [
                    {
                        "name": "warmup",
                        "duration_seconds": 30,
                        "title": "Warmup",
                        "directive": "Quick recall only. One short answer.",
                        "payload": {"mode": "review", "prompt": "Translate 'hola'", "expected_answer": "hello", "accepted_keywords": ["hello"], "item_id": 1},
                    },
                    {
                        "name": "core_challenge",
                        "duration_seconds": 120,
                        "title": "Core Challenge",
                        "directive": "Short constrained output. No open chat.",
                        "payload": {"mode": "rewrite", "prompt": "Rewrite correctly", "expected_answer": "I went there yesterday.", "accepted_keywords": ["went", "yesterday"], "skill_focus": "grammar", "target": "past tense"},
                    },
                    {
                        "name": "correction_engine",
                        "duration_seconds": 20,
                        "title": "Correction",
                        "directive": "Highlight exactly what changed.",
                        "payload": {"show_highlight_diff": True},
                    },
                    {
                        "name": "reinforcement",
                        "duration_seconds": 35,
                        "title": "Reinforcement",
                        "directive": "Repeat the corrected form, then one slight variation.",
                        "payload": {"repeat_prompt": "Repeat: I went there yesterday."},
                    },
                    {
                        "name": "win_moment",
                        "duration_seconds": 15,
                        "title": "Win",
                        "directive": "Show visible progress before exit.",
                        "payload": {"headline": "Round complete"},
                    },
                ],
            }
        )

    async def evaluate_response(self, user_id: int, session, learner_response: str):
        return type(
            "Feedback",
            (),
            {
                "structured": True,
                "targeted_weak_area": session.weak_area,
                "is_correct": False,
                "improvement_score": 0.74,
                "corrected_response": "I went there yesterday.",
                "highlighted_mistakes": ["Use the past tense form 'went'"],
                "reinforcement_prompt": "Repeat exactly: I went there yesterday.",
                "variation_prompt": "Now say it again with a slight variation about past tense: I went there yesterday.",
                "win_message": "You improved your grammar round to 74% clarity. Wow score: 78%.",
                "wow_score": 0.78,
                "xp_preview": 145,
                "badges_preview": ["First Session"],
            },
        )()

    def to_payload(self, session):
        return {
            "duration_seconds": session.duration_seconds,
            "mode": session.mode,
            "weak_area": session.weak_area,
            "lesson_target": session.lesson_target,
            "phases": [
                {
                    "name": phase.name,
                    "duration_seconds": phase.duration_seconds,
                    "title": phase.title,
                    "directive": phase.directive,
                    "payload": phase.payload,
                }
                for phase in session.phases
            ],
        }

    def from_payload(self, payload):
        from vocablens.services.session_engine import SessionPhase, StructuredSession

        return StructuredSession(
            duration_seconds=payload["duration_seconds"],
            mode=payload["mode"],
            weak_area=payload["weak_area"],
            lesson_target=payload.get("lesson_target"),
            phases=[
                SessionPhase(
                    name=phase["name"],
                    duration_seconds=phase["duration_seconds"],
                    title=phase["title"],
                    directive=phase["directive"],
                    payload=phase["payload"],
                )
                for phase in payload["phases"]
            ],
        )


def test_session_endpoints_return_standardized_envelopes():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_session_engine] = lambda: FakeSessionEngine()
    client = TestClient(app)

    start = client.post("/session/start", json={}, headers={"Authorization": "Bearer ignored"})
    assert start.status_code == 200
    start_payload = start.json()
    assert start_payload["meta"]["source"] == "session.start"
    assert start_payload["data"]["mode"] == "game_round"
    assert [phase["name"] for phase in start_payload["data"]["phases"]] == [
        "warmup",
        "core_challenge",
        "correction_engine",
        "reinforcement",
        "win_moment",
    ]

    evaluate = client.post(
        "/session/evaluate",
        json={
            "session": start_payload["data"],
            "learner_response": "I goed there yesterday",
        },
        headers={"Authorization": "Bearer ignored"},
    )
    assert evaluate.status_code == 200
    eval_payload = evaluate.json()
    assert eval_payload["meta"]["source"] == "session.evaluate"
    assert eval_payload["data"]["structured"] is True
    assert eval_payload["data"]["targeted_weak_area"] == "grammar"
    assert "went" in eval_payload["data"]["corrected_response"]
