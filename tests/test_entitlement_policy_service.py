from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.entitlement_policy_service import EntitlementPolicyService


class _FakeUsageLogsRepo:
    def __init__(self, used_requests: int, used_tokens: int):
        self.used_requests = used_requests
        self.used_tokens = used_tokens

    async def totals_for_user_day(self, user_id: int):
        return self.used_requests, self.used_tokens


class _FakeSubscriptionsRepo:
    def __init__(self, subscription):
        self.subscription = subscription

    async def get_by_user(self, user_id: int):
        return self.subscription


class _FakeUOW:
    def __init__(self, subscription, used_requests: int, used_tokens: int):
        self.subscriptions = _FakeSubscriptionsRepo(subscription)
        self.usage_logs = _FakeUsageLogsRepo(used_requests, used_tokens)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _factory(subscription, *, used_requests: int, used_tokens: int):
    def _uow_factory():
        return _FakeUOW(subscription, used_requests=used_requests, used_tokens=used_tokens)

    return _uow_factory


def test_entitlement_policy_allows_when_under_limits():
    subscription = SimpleNamespace(request_limit=100, token_limit=50000)
    service = EntitlementPolicyService(_factory(subscription, used_requests=40, used_tokens=1200))

    decision = run_async(service.evaluate_request(1))

    assert decision.allowed is True
    assert decision.message is None


def test_entitlement_policy_blocks_on_request_limit():
    subscription = SimpleNamespace(request_limit=100, token_limit=50000)
    service = EntitlementPolicyService(_factory(subscription, used_requests=100, used_tokens=1200))

    decision = run_async(service.evaluate_request(1))

    assert decision.allowed is False
    assert decision.message == "Request limit exceeded for current period"


def test_entitlement_policy_blocks_on_token_limit():
    subscription = SimpleNamespace(request_limit=100, token_limit=50000)
    service = EntitlementPolicyService(_factory(subscription, used_requests=40, used_tokens=50000))

    decision = run_async(service.evaluate_request(1))

    assert decision.allowed is False
    assert decision.message == "Token quota exceeded for current period"


def test_entitlement_policy_uses_default_free_limits_without_subscription():
    service = EntitlementPolicyService(_factory(None, used_requests=99, used_tokens=49999))

    decision = run_async(service.evaluate_request(1))

    assert decision.allowed is True
    assert decision.request_limit == 100
    assert decision.token_limit == 50000
