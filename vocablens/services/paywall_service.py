from __future__ import annotations

from dataclasses import dataclass

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.event_service import EventService


@dataclass(frozen=True)
class PaywallDecision:
    show_paywall: bool
    paywall_type: str | None
    reason: str | None
    usage_percent: int
    request_usage_percent: int
    token_usage_percent: int
    usage_requests: int
    usage_tokens: int
    request_limit: int
    token_limit: int
    sessions_seen: int
    wow_moment_triggered: bool
    trial_active: bool
    trial_tier: str | None
    trial_ends_at: object | None
    allow_access: bool


class PaywallService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        event_service: EventService | None = None,
        *,
        session_trigger: int = 3,
        usage_soft_threshold: float = 0.8,
        usage_hard_threshold: float = 1.0,
    ):
        self._uow_factory = uow_factory
        self._events = event_service
        self._session_trigger = session_trigger
        self._usage_soft_threshold = usage_soft_threshold
        self._usage_hard_threshold = usage_hard_threshold

    async def evaluate(self, user_id: int, *, wow_moment: bool = False) -> PaywallDecision:
        async with self._uow_factory() as uow:
            subscription = await uow.subscriptions.get_by_user(user_id)
            events = await uow.events.list_by_user(user_id, limit=200)
            used_requests, used_tokens = await uow.usage_logs.totals_for_user_day(user_id)
            await uow.commit()

        tier = (subscription.tier if subscription else "free").lower()
        request_limit = int(getattr(subscription, "request_limit", 100) or 100)
        token_limit = int(getattr(subscription, "token_limit", 50000) or 50000)
        trial_tier = getattr(subscription, "trial_tier", None)
        trial_ends_at = getattr(subscription, "trial_ends_at", None)
        trial_active = bool(trial_tier and trial_ends_at and trial_ends_at > utc_now())
        if subscription and trial_tier and trial_ends_at and trial_ends_at <= utc_now():
            async with self._uow_factory() as uow:
                await uow.subscriptions.clear_trial(user_id)
                await uow.commit()
            trial_tier = None
            trial_ends_at = None
            trial_active = False

        if tier != "free" or trial_active:
            return self._decision(
                show_paywall=False,
                paywall_type=None,
                reason=None,
                used_requests=used_requests,
                used_tokens=used_tokens,
                request_limit=request_limit,
                token_limit=token_limit,
                sessions_seen=self._session_count(events),
                wow_moment_triggered=wow_moment,
                trial_active=trial_active,
                trial_tier=trial_tier,
                trial_ends_at=trial_ends_at,
                allow_access=True,
            )

        sessions_seen = self._session_count(events)
        usage_ratio = max(
            self._ratio(used_requests, request_limit),
            self._ratio(used_tokens, token_limit),
        )
        request_ratio = self._ratio(used_requests, request_limit)
        token_ratio = self._ratio(used_tokens, token_limit)

        if usage_ratio >= self._usage_hard_threshold:
            decision = self._decision(
                show_paywall=True,
                paywall_type="hard_paywall",
                reason="usage threshold reached",
                used_requests=used_requests,
                used_tokens=used_tokens,
                request_limit=request_limit,
                token_limit=token_limit,
                sessions_seen=sessions_seen,
                wow_moment_triggered=wow_moment,
                trial_active=False,
                trial_tier=None,
                trial_ends_at=None,
                allow_access=False,
            )
        elif wow_moment or sessions_seen >= self._session_trigger or usage_ratio >= self._usage_soft_threshold:
            reason = "wow moment reached" if wow_moment else "session trigger reached" if sessions_seen >= self._session_trigger else "usage pressure high"
            decision = self._decision(
                show_paywall=True,
                paywall_type="soft_paywall",
                reason=reason,
                used_requests=used_requests,
                used_tokens=used_tokens,
                request_limit=request_limit,
                token_limit=token_limit,
                sessions_seen=sessions_seen,
                wow_moment_triggered=wow_moment,
                trial_active=False,
                trial_tier=None,
                trial_ends_at=None,
                allow_access=True,
            )
        else:
            decision = self._decision(
                show_paywall=False,
                paywall_type=None,
                reason=None,
                used_requests=used_requests,
                used_tokens=used_tokens,
                request_limit=request_limit,
                token_limit=token_limit,
                sessions_seen=sessions_seen,
                wow_moment_triggered=wow_moment,
                trial_active=False,
                trial_tier=None,
                trial_ends_at=None,
                allow_access=True,
            )

        if decision.show_paywall and self._events:
            await self._events.track_event(
                user_id,
                "paywall_viewed",
                {
                    "source": "paywall_service",
                    "type": decision.paywall_type,
                    "reason": decision.reason,
                    "usage_percent": decision.usage_percent,
                },
            )
        return decision

    async def start_trial(self, user_id: int, duration_days: int | None = 3) -> None:
        duration_days = 3 if duration_days is None else duration_days
        duration_days = max(3, min(7, int(duration_days)))
        async with self._uow_factory() as uow:
            await uow.subscriptions.start_trial(
                user_id=user_id,
                tier="pro",
                request_limit=1000,
                token_limit=300000,
                duration_days=duration_days,
            )
            await uow.commit()

    async def register_upgrade_click(self, user_id: int, *, source: str) -> None:
        if self._events:
            await self._events.track_event(
                user_id,
                "upgrade_clicked",
                {"source": source},
            )

    async def register_upgrade_completed(self, user_id: int, *, tier: str, source: str) -> None:
        if self._events:
            await self._events.track_event(
                user_id,
                "upgrade_completed",
                {"source": source, "tier": tier},
            )

    def _session_count(self, events) -> int:
        return sum(1 for event in events if getattr(event, "event_type", None) == "session_started")

    def _ratio(self, used: int, limit: int) -> float:
        if limit <= 0:
            return 1.0
        return used / limit

    def _decision(
        self,
        *,
        show_paywall: bool,
        paywall_type: str | None,
        reason: str | None,
        used_requests: int,
        used_tokens: int,
        request_limit: int,
        token_limit: int,
        sessions_seen: int,
        wow_moment_triggered: bool,
        trial_active: bool,
        trial_tier: str | None,
        trial_ends_at,
        allow_access: bool,
    ) -> PaywallDecision:
        request_usage_percent = min(100, int(self._ratio(used_requests, request_limit) * 100)) if request_limit else 100
        token_usage_percent = min(100, int(self._ratio(used_tokens, token_limit) * 100)) if token_limit else 100
        return PaywallDecision(
            show_paywall=show_paywall,
            paywall_type=paywall_type,
            reason=reason,
            usage_percent=max(request_usage_percent, token_usage_percent),
            request_usage_percent=request_usage_percent,
            token_usage_percent=token_usage_percent,
            usage_requests=used_requests,
            usage_tokens=used_tokens,
            request_limit=request_limit,
            token_limit=token_limit,
            sessions_seen=sessions_seen,
            wow_moment_triggered=wow_moment_triggered,
            trial_active=trial_active,
            trial_tier=trial_tier,
            trial_ends_at=trial_ends_at,
            allow_access=allow_access,
        )
