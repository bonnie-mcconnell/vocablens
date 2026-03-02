from fastapi.testclient import TestClient
from vocablens.main import app


def test_create_and_review_flow():
    client = TestClient(app)

    # Create item (simulate simple text without image)
    response = client.post(
        "/vocabulary",
        json={
            "original_text": "hello",
            "target_language": "es"
        }
    )

    assert response.status_code == 200
    data = response.json()
    item_id = data["id"]

    # List
    list_response = client.get("/vocabulary")
    assert list_response.status_code == 200
    assert len(list_response.json()) >= 1

    # Review
    review_response = client.post(f"/vocabulary/{item_id}/review")
    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert reviewed["review_count"] == 1