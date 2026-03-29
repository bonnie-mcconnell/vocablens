from __future__ import annotations

import hashlib


def deterministic_dedupe_key(*, user_id: int, source: str, reference_id: str | None) -> str:
    """Create a stable dedupe key that is safe across retries."""
    raw = f"{int(user_id)}:{source}:{reference_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
