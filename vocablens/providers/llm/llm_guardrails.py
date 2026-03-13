import json
import os
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None


class _LRUCache:
    def __init__(self, maxsize: int = 256):
        self.maxsize = maxsize
        self.store: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key in self.store:
            self.store.move_to_end(key)
            return self.store[key]
        return None

    def set(self, key: str, value: Any, ttl: int = 600) -> None:
        self.store[key] = value
        self.store.move_to_end(key)
        if len(self.store) > self.maxsize:
            self.store.popitem(last=False)


class _RedisCache:
    def __init__(self, url: str):
        self.client = redis.Redis.from_url(url)

    def get(self, key: str) -> Optional[Any]:
        val = self.client.get(key)
        if val is None:
            return None
        try:
            return json.loads(val)
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int = 600) -> None:
        try:
            self.client.setex(key, ttl, json.dumps(value))
        except Exception:
            pass


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

        redis_url = os.getenv("REDIS_URL")
        if redis and redis_url:
            self.cache = _RedisCache(redis_url)
        else:
            self.cache = _LRUCache(maxsize=cache_maxsize)

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

        key = cache_key or f"{model or self.default_model}:{version}:{prompt}"
        cached = self.cache.get(key)
        if cached:
            return cached

        response_text = self._with_retries(
            lambda: self._chat(prompt, model or self.default_model, timeout, **kwargs)
        )

        self.cache.set(key, response_text, ttl=self.cache_ttl)
        return response_text

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

    # -----------------------------
    # Internals
    # -----------------------------

    def _chat(self, prompt: str, model: str, timeout: Optional[float], **kwargs) -> str:
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout or self.default_timeout,
            **kwargs,
        )
        content = resp.choices[0].message.content
        return content.strip() if content else ""

    def _with_retries(self, func):
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                return func()
            except Exception as exc:  # pragma: no cover - network dependent
                last_exc = exc
                if attempt == self.max_retries - 1:
                    raise exc
                sleep_for = self.backoff_base * (2**attempt)
                time.sleep(sleep_for)
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
