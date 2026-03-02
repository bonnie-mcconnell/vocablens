from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class VocabularyItem:
    id: Optional[int]
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    created_at: datetime
    last_reviewed_at: Optional[datetime] = None
    review_count: int = 0
    retention_score: float = 2.5  # SM-2 starting ease factor
    next_review_due: Optional[datetime] = None