from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConsumedEvent:
    dedupe_key: str
    version: int
    payload: dict


class InMemoryConsumerDedupeStore:
    """Reference contract: consumers must enforce unique dedupe keys."""

    def __init__(self):
        self._seen: set[str] = set()

    def mark_once(self, dedupe_key: str) -> bool:
        key = str(dedupe_key)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


class IdempotentConsumer:
    def __init__(self, dedupe_store: InMemoryConsumerDedupeStore):
        self._dedupe_store = dedupe_store

    def consume_once(self, event: ConsumedEvent, handler) -> bool:
        if not self._dedupe_store.mark_once(event.dedupe_key):
            return False
        handler(event)
        return True
