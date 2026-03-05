from fastapi.testclient import TestClient
from vocablens.main import app

client = TestClient(app)


def test_register_and_login():
    response = client.post(
        "/register",
        json={"email": "test@test.com", "password": "password123"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    login = client.post(
        "/login",
        json={"email": "test@test.com", "password": "password123"},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()