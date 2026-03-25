from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from vocablens.config.settings import settings
from vocablens.infrastructure.notifications.base import NotificationMessage, NotificationSink
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.notification_policy_service import NotificationPolicyService
from vocablens.services.notification_state_service import NotificationStateService


class DeliveryBackend(Protocol):
    channel: str

    async def send(self, message: NotificationMessage) -> None:
        ...


@dataclass(frozen=True)
class DeliveryResult:
    user_id: int
    channel: str
    success: bool
    attempts: int
    provider: str
    error: str | None = None


class InAppDeliveryBackend:
    channel = "in_app"

    async def send(self, message: NotificationMessage) -> None:
        return None


class PushDeliveryBackend:
    channel = "push"

    async def send(self, message: NotificationMessage) -> None:
        return None


class EmailDeliveryBackend:
    channel = "email"

    def __init__(self, provider: NotificationSink):
        self._provider = provider

    async def send(self, message: NotificationMessage) -> None:
        await self._provider.send(message)


class NotificationDeliveryService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        backends: dict[str, DeliveryBackend],
        *,
        max_attempts: int | None = None,
        backoff_base: float = 0.5,
        sleeper=None,
        batch_size: int = 25,
    ):
        self._uow_factory = uow_factory
        self._backends = dict(backends)
        self._max_attempts = max(1, int(max_attempts or settings.NOTIFICATION_MAX_RETRIES))
        self._backoff_base = backoff_base
        self._sleep = sleeper or asyncio.sleep
        self._batch_size = max(1, int(batch_size))
        self._policy_service = NotificationPolicyService(uow_factory)
        self._notification_states = NotificationStateService(uow_factory)

    async def send(self, message: NotificationMessage) -> DeliveryResult:
        channel = self._channel_for(message)
        backend = self._backend_for(channel)
        last_error: str | None = None
        runtime_policy = await self._policy_service.current_policy()
        source_context = str((message.metadata or {}).get("source_context") or "notification_delivery_service.send")
        reference_id = (message.metadata or {}).get("reference_id")

        for attempt in range(1, self._max_attempts + 1):
            delivery_id = await self._create_attempt(
                message,
                backend,
                attempt,
                policy_key=runtime_policy.policy_key,
                policy_version=runtime_policy.policy_version,
                source_context=source_context,
                reference_id=reference_id,
            )
            try:
                await backend.send(message)
            except Exception as exc:
                last_error = str(exc)
                await self._mark_status(delivery_id, "failed", error_message=last_error)
                await self._notification_states.record_delivery(
                    user_id=message.user_id,
                    category=message.category,
                    channel=channel,
                    status="failed",
                    policy_key=runtime_policy.policy_key,
                    policy_version=runtime_policy.policy_version,
                    reference_id=reference_id,
                )
                if attempt < self._max_attempts:
                    await self._sleep(self._backoff_base * (2 ** (attempt - 1)))
                    continue
                return DeliveryResult(
                    user_id=message.user_id,
                    channel=channel,
                    success=False,
                    attempts=attempt,
                    provider=self._provider_name(backend),
                    error=last_error,
                )

            await self._mark_status(delivery_id, "sent")
            await self._notification_states.record_delivery(
                user_id=message.user_id,
                category=message.category,
                channel=channel,
                status="sent",
                policy_key=runtime_policy.policy_key,
                policy_version=runtime_policy.policy_version,
                reference_id=reference_id,
            )
            return DeliveryResult(
                user_id=message.user_id,
                channel=channel,
                success=True,
                attempts=attempt,
                provider=self._provider_name(backend),
            )

        return DeliveryResult(
            user_id=message.user_id,
            channel=channel,
            success=False,
            attempts=self._max_attempts,
            provider=self._provider_name(backend),
            error=last_error or "delivery failed",
        )

    async def send_batch(self, messages: list[NotificationMessage]) -> list[DeliveryResult]:
        results: list[DeliveryResult] = []
        for channel, grouped in self._group_by_channel(messages).items():
            for start in range(0, len(grouped), self._batch_size):
                chunk = grouped[start:start + self._batch_size]
                chunk_results = await asyncio.gather(*(self.send(message) for message in chunk))
                results.extend(chunk_results)
        return results

    def _group_by_channel(self, messages: list[NotificationMessage]) -> dict[str, list[NotificationMessage]]:
        grouped: dict[str, list[NotificationMessage]] = {}
        for message in messages:
            grouped.setdefault(self._channel_for(message), []).append(message)
        return grouped

    def _channel_for(self, message: NotificationMessage) -> str:
        channel = (message.metadata or {}).get("channel", "in_app")
        return str(channel).lower()

    def _backend_for(self, channel: str) -> DeliveryBackend:
        try:
            return self._backends[channel]
        except KeyError as exc:
            raise ValueError(f"Unsupported notification channel '{channel}'") from exc

    async def _create_attempt(
        self,
        message: NotificationMessage,
        backend: DeliveryBackend,
        attempt: int,
        *,
        policy_key: str,
        policy_version: str,
        source_context: str,
        reference_id: str | None,
    ) -> int:
        async with self._uow_factory() as uow:
            delivery = await uow.notification_deliveries.create_attempt(
                user_id=message.user_id,
                category=message.category,
                provider=self._provider_name(backend),
                policy_key=policy_key,
                policy_version=policy_version,
                source_context=source_context,
                reference_id=reference_id,
                title=message.title,
                body=message.body,
                payload={
                    **(message.metadata or {}),
                    "channel": self._channel_for(message),
                    "attempt": attempt,
                },
            )
            await uow.commit()
        return delivery.id

    async def _mark_status(self, delivery_id: int, status: str, *, error_message: str | None = None) -> None:
        async with self._uow_factory() as uow:
            await uow.notification_deliveries.mark_status(
                delivery_id,
                status,
                error_message=error_message,
            )
            await uow.commit()

    def _provider_name(self, backend: DeliveryBackend) -> str:
        return backend.__class__.__name__.lower()


class NotificationDeliverySink:
    def __init__(self, delivery_service: NotificationDeliveryService):
        self._delivery_service = delivery_service

    async def send(self, message: NotificationMessage) -> None:
        result = await self._delivery_service.send(message)
        if not result.success:
            raise RuntimeError(result.error or "notification delivery failed")
