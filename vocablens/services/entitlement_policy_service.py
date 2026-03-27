from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from vocablens.infrastructure.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class EntitlementDecision:
    allowed: bool
    message: str | None
    request_limit: int
    token_limit: int
    used_requests: int
    used_tokens: int


class EntitlementPolicyService:
    """Centralized request quota/entitlement checks.

    The service is intentionally read-only and relies on UoW-owned transaction
    boundaries for consistency with the rest of the service layer.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        default_request_limit: int = 100,
        default_token_limit: int = 50000,
    ):
        self._uow_factory = uow_factory
        self._default_request_limit = default_request_limit
        self._default_token_limit = default_token_limit

    async def evaluate_request(self, user_id: int) -> EntitlementDecision:
        async with self._uow_factory() as uow:
            subscription = await uow.subscriptions.get_by_user(user_id)
            request_limit = (
                int(getattr(subscription, "request_limit", self._default_request_limit))
                if subscription
                else self._default_request_limit
            )
            token_limit = (
                int(getattr(subscription, "token_limit", self._default_token_limit))
                if subscription
                else self._default_token_limit
            )
            used_requests, used_tokens = await uow.usage_logs.totals_for_user_day(user_id)

        if used_requests >= request_limit:
            return EntitlementDecision(
                allowed=False,
                message="Request limit exceeded for current period",
                request_limit=request_limit,
                token_limit=token_limit,
                used_requests=used_requests,
                used_tokens=used_tokens,
            )

        if used_tokens >= token_limit:
            return EntitlementDecision(
                allowed=False,
                message="Token quota exceeded for current period",
                request_limit=request_limit,
                token_limit=token_limit,
                used_requests=used_requests,
                used_tokens=used_tokens,
            )

        return EntitlementDecision(
            allowed=True,
            message=None,
            request_limit=request_limit,
            token_limit=token_limit,
            used_requests=used_requests,
            used_tokens=used_tokens,
        )
