from types import SimpleNamespace

from fastapi.testclient import TestClient

from tests.conftest import make_user
from vocablens.api.dependencies_interaction_api import (
    get_conversation_service,
    get_current_user,
    get_streaming_tutor_service,
)
from vocablens.auth.jwt import create_access_token
from vocablens.infrastructure.observability.token_tracker import add_tokens
from vocablens.main import create_app
import vocablens.main as main_module


class FakeUsageLogsRepo:
    def __init__(self, used_requests: int = 0, used_tokens: int = 0):
        self.used_requests = used_requests
        self.used_tokens = used_tokens
        self.logged = []

    async def totals_for_user_day(self, user_id: int):
        return self.used_requests, self.used_tokens

    async def log(self, user_id: int, endpoint: str, tokens: int, success: bool = True):
        self.logged.append(
            {
                "user_id": user_id,
                "endpoint": endpoint,
                "tokens": tokens,
                "success": success,
            }
        )


class FakeSubscriptionsRepo:
    def __init__(self, request_limit: int = 1000, token_limit: int = 100000):
        self.subscription = SimpleNamespace(
            tier="pro",
            request_limit=request_limit,
            token_limit=token_limit,
        )

    async def get_by_user(self, user_id: int):
        return self.subscription


class FakeUOW:
    def __init__(self, usage_logs: FakeUsageLogsRepo, subscriptions: FakeSubscriptionsRepo):
        self.usage_logs = usage_logs
        self.subscriptions = subscriptions

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeConversationService:
    def __init__(self, tokens_to_add: int = 0):
        self.tokens_to_add = tokens_to_add
        self.calls = []

    async def generate_reply(self, user_id: int, message: str, source_lang: str, target_lang: str, tutor_mode: bool = True):
        self.calls.append(
            {
                "user_id": user_id,
                "message": message,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "tutor_mode": tutor_mode,
            }
        )
        if self.tokens_to_add:
            add_tokens(self.tokens_to_add)
        return {
            "reply": "Tutor reply",
            "analysis": {"grammar_mistakes": []},
            "drills": [],
            "correction_feedback": ["Use the past tense here."],
            "live_corrections": ["I went to the store."],
            "inline_explanations": ["Past tense of go is went."],
            "mistake_memory": ["go -> went"],
            "next_action": "review_word",
            "next_action_reason": "Overdue review",
            "lesson_difficulty": "medium",
            "content_type": "conversation",
            "tutor_mode": tutor_mode,
        }


class FakeStreamingTutorService:
    async def sse_events(self, *, user_id: int, message: str, source_lang: str, target_lang: str, tutor_mode: bool = True):
        yield 'data: {"type":"stream_started","stream_id":"abc"}\n\n'
        yield 'data: {"type":"token","stream_id":"abc","content":"Tutor "}\n\n'
        yield 'data: {"type":"complete","stream_id":"abc","response":{"reply":"Tutor reply"}}\n\n'

    async def interrupt(self, stream_id: str) -> bool:
        return stream_id == "abc"


def _build_client(monkeypatch, usage_repo: FakeUsageLogsRepo, subscriptions_repo: FakeSubscriptionsRepo, conversation_service: FakeConversationService):
    def fake_uow_factory(_session_maker):
        def _factory():
            return FakeUOW(usage_repo, subscriptions_repo)
        return _factory

    monkeypatch.setattr(main_module, "UnitOfWorkFactory", fake_uow_factory)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_conversation_service] = lambda: conversation_service
    app.dependency_overrides[get_streaming_tutor_service] = lambda: FakeStreamingTutorService()
    return TestClient(app)


def test_conversation_flow_logs_accurate_tokens_and_request_metadata(monkeypatch):
    usage_repo = FakeUsageLogsRepo()
    subscriptions_repo = FakeSubscriptionsRepo()
    conversation_service = FakeConversationService(tokens_to_add=17)
    client = _build_client(monkeypatch, usage_repo, subscriptions_repo, conversation_service)
    token = create_access_token(1)

    response = client.post(
        "/conversation/chat",
        params={
            "message": "I goed to school",
            "source_lang": "en",
            "target_lang": "es",
            "tutor_mode": "true",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "Tutor reply"
    assert payload["tutor_mode"] is True
    assert payload["live_corrections"] == ["I went to the store."]
    assert conversation_service.calls[0]["message"] == "I goed to school"
    assert response.headers["X-Request-ID"]
    assert usage_repo.logged == [
        {
            "user_id": 1,
            "endpoint": "/conversation/chat",
            "tokens": 17,
            "success": True,
        }
    ]


def test_quota_middleware_blocks_over_limit_requests_before_handler(monkeypatch):
    usage_repo = FakeUsageLogsRepo(used_requests=100, used_tokens=0)
    subscriptions_repo = FakeSubscriptionsRepo(request_limit=100, token_limit=100000)
    conversation_service = FakeConversationService(tokens_to_add=99)
    client = _build_client(monkeypatch, usage_repo, subscriptions_repo, conversation_service)
    token = create_access_token(1)

    response = client.post(
        "/conversation/chat",
        params={
            "message": "Hola",
            "source_lang": "es",
            "target_lang": "en",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 429
    assert response.text == "Request limit exceeded for current period"
    assert conversation_service.calls == []
    assert usage_repo.logged == []


def test_streaming_chat_endpoint_and_interrupt(monkeypatch):
    usage_repo = FakeUsageLogsRepo()
    subscriptions_repo = FakeSubscriptionsRepo()
    conversation_service = FakeConversationService()
    client = _build_client(monkeypatch, usage_repo, subscriptions_repo, conversation_service)
    token = create_access_token(1)

    stream_response = client.get(
        "/conversation/chat/stream",
        params={
            "message": "hello",
            "source_lang": "en",
            "target_lang": "es",
            "tutor_mode": "true",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    interrupt_response = client.post(
        "/conversation/chat/stream/abc/interrupt",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert '"type":"stream_started"' in stream_response.text
    assert '"type":"complete"' in stream_response.text
    assert interrupt_response.status_code == 200
    assert interrupt_response.json()["interrupted"] is True
