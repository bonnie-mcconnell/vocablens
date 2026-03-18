from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NotificationMessage:
    user_id: int
    category: str
    title: str
    body: str
    metadata: dict | None = None


class NotificationSink(Protocol):
    async def send(self, message: NotificationMessage) -> None:
        ...
