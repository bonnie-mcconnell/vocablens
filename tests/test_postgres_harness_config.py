import os

import pytest

from tests import postgres_harness


def test_postgres_root_url_raises_when_required(monkeypatch):
    monkeypatch.delenv("VOCABLENS_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("VOCABLENS_REQUIRE_POSTGRES_TESTS", "true")

    with pytest.raises(RuntimeError):
        postgres_harness.postgres_root_url()


def test_postgres_root_url_returns_when_present(monkeypatch):
    value = "postgresql+asyncpg://postgres:postgres@localhost/testdb"
    monkeypatch.setenv("VOCABLENS_TEST_DATABASE_URL", value)
    monkeypatch.setenv("VOCABLENS_REQUIRE_POSTGRES_TESTS", "true")

    assert postgres_harness.postgres_root_url() == value


def test_postgres_root_url_skips_when_optional(monkeypatch):
    monkeypatch.delenv("VOCABLENS_TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("VOCABLENS_REQUIRE_POSTGRES_TESTS", raising=False)

    with pytest.raises(pytest.skip.Exception):
        postgres_harness.postgres_root_url()


def test_require_postgres_tests_parser(monkeypatch):
    monkeypatch.setenv("VOCABLENS_REQUIRE_POSTGRES_TESTS", "on")
    assert postgres_harness._require_postgres_tests() is True

    monkeypatch.setenv("VOCABLENS_REQUIRE_POSTGRES_TESTS", "0")
    assert postgres_harness._require_postgres_tests() is False

    monkeypatch.delenv("VOCABLENS_REQUIRE_POSTGRES_TESTS", raising=False)
    assert postgres_harness._require_postgres_tests() is False
