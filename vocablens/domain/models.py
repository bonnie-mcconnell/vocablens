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

    # AI enrichment
    example_source_sentence: Optional[str] = None
    example_translated_sentence: Optional[str] = None
    grammar_note: Optional[str] = None
    semantic_cluster: Optional[str] = None

    # spaced repetition (SM-2)
    last_reviewed_at: Optional[datetime] = None
    review_count: int = 0
    ease_factor: float = 2.5
    interval: int = 1
    repetitions: int = 0
    next_review_due: Optional[datetime] = None
