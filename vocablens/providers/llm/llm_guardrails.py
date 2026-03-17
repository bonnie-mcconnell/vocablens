import json
import time
import asyncio
from typing import Any, Dict, Optional

import anyio

from vocablens.config.settings import settings
from vocablens.infrastructure.cache.redis_cache import (
    get_cache_backend,
    LRUCacheBackend,
)
from vocablens.infrastructure.observability.metrics import (
    LLM_LATENCY,
    LLM_TOKENS,
    LLM_COST,
)


class LLMGuardrails:
    """
    Adds retries, timeouts, caching, and JSON validation around LLM calls.
    """

    def __init__(
        self,
        client,
        default_model: str = "gpt-4o-mini",
        default_timeout: float = 15.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        cache_ttl: int = 600,
        cache_maxsize: int = 256,
    ):
        self.client = client
        self.default_model = default_model
        self.default_timeout = default_timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.cache_ttl = cache_ttl
        if settings.ENABLE_REDIS_CACHE:
            self.cache = get_cache_backend()
        else:
            self.cache = LRUCacheBackend(maxsize=cache_maxsize)

    # -----------------------------
    # Public API
    # -----------------------------

    def generate_text(
        self,
        prompt: str,
        version: str = "v1",
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        cache_key: Optional[str] = None,
        **kwargs,
    ) -> str:

        return self._run_async(
            self._generate_text_async(
                prompt=prompt,
                version=version,
                model=model,
                timeout=timeout,
                cache_key=cache_key,
                **kwargs,
            )
        )

    def generate_json(
        self,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        version: str = "v1",
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        cache_key: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:

        text = self.generate_text(
            prompt,
            version=version,
            model=model,
            timeout=timeout,
            cache_key=cache_key,
            **kwargs,
        )

        try:
            data = json.loads(text)
        except Exception:
            return {}

        if schema:
            self._validate_schema(data, schema)

        return data

    def _run_async(self, coro):
        """
        Run an async coroutine from sync context without asyncio.run, safe for
        both threadpool and event-loop contexts.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return anyio.run(lambda: coro)

        if loop.is_running():
            return anyio.from_thread.run(lambda: coro)

        return loop.run_until_complete(coro)  # pragma: no cover (fallback)

    async def _generate_text_async(
        self,
        prompt: str,
        version: str,
        model: Optional[str],
        timeout: Optional[float],
        cache_key: Optional[str],
        **kwargs,
    ) -> str:

        key = cache_key or f"{model or self.default_model}:{version}:{prompt}"
        cached = await self.cache.get(key)
        if cached:
            return cached

        response_text = await self._with_retries_async(
            lambda: self._chat_async(prompt, model or self.default_model, timeout, **kwargs)
        )

        await self.cache.set(key, response_text, ttl=self.cache_ttl)
        return response_text

    # -----------------------------
    # Internals
    # -----------------------------

    async def _chat_async(self, prompt: str, model: str, timeout: Optional[float], **kwargs) -> str:
        start = time.perf_counter()
        resp = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout or self.default_timeout,
            **kwargs,
        )
        duration = time.perf_counter() - start
        LLM_LATENCY.labels(provider="openai", model=model).observe(duration)

        usage = getattr(resp, "usage", None)
        if usage:
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
            LLM_TOKENS.labels(provider="openai", model=model, type="prompt").inc(prompt_tokens)
            LLM_TOKENS.labels(provider="openai", model=model, type="completion").inc(completion_tokens)
            LLM_TOKENS.labels(provider="openai", model=model, type="total").inc(total_tokens)
            estimated_cost = total_tokens * 0.000002
            LLM_COST.labels(provider="openai", model=model).inc(estimated_cost)

        content = resp.choices[0].message.content
        return content.strip() if content else ""

    async def _with_retries_async(self, func):
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                return await func()
            except Exception as exc:  # pragma: no cover - network dependent
                last_exc = exc
                if attempt == self.max_retries - 1:
                    raise exc
                sleep_for = self.backoff_base * (2**attempt)
                await asyncio.sleep(sleep_for)
        if last_exc:
            raise last_exc

    def _validate_schema(self, data: Dict[str, Any], schema: Dict[str, Any]) -> None:
        """
        Lightweight validator to avoid hard dependency on jsonschema.
        Validates presence and types of top-level keys only.
        """
        required = schema.get("required", [])
        props = schema.get("properties", {})

        for key in required:
            if key not in data:
                raise ValueError(f"Missing required field: {key}")

        for key, rules in props.items():
            if key in data and "type" in rules:
                expected = rules["type"]
                if expected == "array" and not isinstance(data[key], list):
                    raise ValueError(f"Field {key} must be array")
                if expected == "object" and not isinstance(data[key], dict):
                    raise ValueError(f"Field {key} must be object")
                if expected == "string" and not isinstance(data[key], str):
                    raise ValueError(f"Field {key} must be string")
