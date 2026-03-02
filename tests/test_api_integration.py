from pathlib import Path
from fastapi.testclient import TestClient

from vocablens.main import app
from vocablens.infrastructure.database import init_db
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository
from vocablens.services.vocabulary_service import VocabularyService


class DummyTranslator:
    def translate(self, text: str, target_lang: str) -> str:
        return f"{text}-{target_lang}"


def setup_test_app(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    repo = SQLiteVocabularyRepository(db_path)
    service = VocabularyService(DummyTranslator(), repo)

    from vocablens.api.routes import create_routes
    from vocablens.services.ocr_service import OCRService

    app.router.routes.clear()
    app.include_router(create_routes(service, OCRService(None)))

    return TestClient(app)


def test_create_and_review_flow(tmp_path):
    client = setup_test_app(tmp_path)

    response = client.post(
        "/translate",
        json={
            "text": "hello",
            "source_lang": "en",
            "target_lang": "es",
        },
    )

    assert response.status_code == 200
    item_id = response.json()["id"]

    list_response = client.get("/vocabulary")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    review_response = client.post(f"/vocabulary/{item_id}/review")
    assert review_response.status_code == 200
    assert review_response.json()["review_count"] == 1