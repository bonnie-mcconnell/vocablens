from fastapi.testclient import TestClient

from tests.conftest import make_user
from vocablens.api.dependencies import get_current_user, get_lesson_generation_service
from vocablens.main import create_app


class FakeLessonGenerationService:
    async def generate_lesson(self, user_id: int):
        return {
            "exercises": [
                {"type": "fill_blank", "question": "Complete: I ___ home.", "answer": "go"},
            ],
            "next_action": {
                "action": "learn_new_word",
                "target": "travel",
                "reason": "Weak cluster needs reinforcement",
                "lesson_difficulty": "medium",
                "content_type": "mixed",
            },
        }


def test_lesson_generate_endpoint_returns_standardized_envelope():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_lesson_generation_service] = lambda: FakeLessonGenerationService()
    client = TestClient(app)

    response = client.get("/lesson/generate", headers={"Authorization": "Bearer ignored"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["source"] == "lesson.generate"
    assert payload["meta"]["difficulty"] == "medium"
    assert payload["meta"]["next_action"] == "learn_new_word"
    assert payload["data"]["next_action"]["target"] == "travel"
