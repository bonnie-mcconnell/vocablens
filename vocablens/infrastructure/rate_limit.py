import time
from typing import Optional

try:
    from redis import asyncio as aioredis  # type: ignore
except ImportError:  # pragma: no cover
    aioredis = None

from vocablens.config.settings import settings


class RateLimiter:
    def __init__(self, redis_url: Optional[str], limit: int, window_sec: int):
        self.limit = limit
        self.window = window_sec
        self.client = aioredis.from_url(redis_url) if (aioredis and redis_url) else None
        self.memory_bucket = {}

    async def allow(self, key: str) -> bool:
        if self.client:
            now_window = int(time.time() / self.window)
            redis_key = f"ratelimit:{key}:{now_window}"
            count = await self.client.incr(redis_key)
            if count == 1:
                await self.client.expire(redis_key, self.window)
            return count <= self.limit

        # fallback in-memory (best-effort)
        now_window = int(time.time() / self.window)
        bucket_key = f"{key}:{now_window}"
        self.memory_bucket[bucket_key] = self.memory_bucket.get(bucket_key, 0) + 1
        return self.memory_bucket[bucket_key] <= self.limit
