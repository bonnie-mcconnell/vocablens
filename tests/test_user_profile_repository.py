from types import SimpleNamespace
from typing import Any, cast

from tests.conftest import run_async
from vocablens.infrastructure.postgres_user_profile_repository import (
    PostgresUserProfileRepository,
)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        if self._value is None:
            raise RuntimeError("Expected row")
        return self._value


class _FakeSession:
    def __init__(self, profile):
        self._profile = profile
        self._calls = 0
        self.commit_calls = 0

    async def execute(self, _statement):
        self._calls += 1
        if self._calls == 1:
            return _FakeResult(None)
        if self._calls == 2:
            return _FakeResult(None)
        return _FakeResult(self._profile)

    async def commit(self):
        self.commit_calls += 1


def test_get_or_create_does_not_commit_session_directly():
    profile = SimpleNamespace(user_id=123)
    session = _FakeSession(profile)
    repo = PostgresUserProfileRepository(cast(Any, session))

    result = run_async(repo.get_or_create(123))

    assert int(getattr(result, "user_id")) == 123
    assert session.commit_calls == 0
