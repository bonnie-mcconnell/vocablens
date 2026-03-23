from fastapi.testclient import TestClient

from tests.conftest import make_user
from vocablens.api.dependencies import get_current_user, get_session_engine
from vocablens.main import create_app


class FakeSessionEngine:
    async def start_session(self, user_id: int):
        return {
            "session_id": "sess_12345678",
            "status": "active",
            "expires_at": "2026-03-23T12:15:00",
            "duration_seconds": 220,
            "mode": "game_round",
            "weak_area": "grammar",
            "lesson_target": "past tense",
            "goal_label": "Fix one grammar pattern cleanly",
            "success_criteria": "Use the corrected form without carrying the original mistake forward.",
            "review_window_minutes": 15,
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

    async def evaluate_session(self, user_id: int, session_id: str, learner_response: str):
        return type(
            "Feedback",
            (),
            {
                "structured": True,
                "targeted_weak_area": "grammar",
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
                "progress_summary": "Grammar improved to 74%, with one correction path to repeat next.",
                "recommended_next_step": "Repeat one more grammar round inside the next 15 minutes.",
                "review_window_minutes": 15,
            },
        )()

    def feedback_to_payload(self, feedback):
        return {
            "structured": feedback.structured,
            "targeted_weak_area": feedback.targeted_weak_area,
            "is_correct": feedback.is_correct,
            "improvement_score": feedback.improvement_score,
            "corrected_response": feedback.corrected_response,
            "highlighted_mistakes": feedback.highlighted_mistakes,
            "reinforcement_prompt": feedback.reinforcement_prompt,
            "variation_prompt": feedback.variation_prompt,
            "win_message": feedback.win_message,
            "wow_score": feedback.wow_score,
            "xp_preview": feedback.xp_preview,
            "badges_preview": feedback.badges_preview,
            "progress_summary": feedback.progress_summary,
            "recommended_next_step": feedback.recommended_next_step,
            "review_window_minutes": feedback.review_window_minutes,
        }


def test_session_endpoints_return_standardized_envelopes():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_session_engine] = lambda: FakeSessionEngine()
    client = TestClient(app)

    start = client.post("/session/start", json={}, headers={"Authorization": "Bearer ignored"})
    assert start.status_code == 200
    start_payload = start.json()
    assert start_payload["meta"]["source"] == "session.start"
    assert start_payload["data"]["session_id"] == "sess_12345678"
    assert start_payload["data"]["mode"] == "game_round"
    assert "goal_label" in start_payload["data"]
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
            "session_id": start_payload["data"]["session_id"],
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
    assert "progress_summary" in eval_payload["data"]
