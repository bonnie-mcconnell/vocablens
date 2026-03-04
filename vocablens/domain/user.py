from dataclasses import dataclass
from datetime import datetime


@dataclass
class User:
    id: int | None
    email: str
    password_hash: str
    created_at: datetime