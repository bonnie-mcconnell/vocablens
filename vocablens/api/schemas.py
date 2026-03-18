from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from vocablens.core.constants import MAX_TEXT_LENGTH
from vocablens.domain.models import VocabularyItem


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    

class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    source_lang: str = Field(..., min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")
    target_lang: str = Field(..., min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")


class VocabularyResponse(BaseModel):
    id: int | None
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    created_at: datetime
    last_reviewed_at: datetime | None
    review_count: int
    ease_factor: float
    interval: int
    repetitions: int
    next_review_due: datetime | None

    @classmethod
    def from_domain(cls, item: VocabularyItem) -> "VocabularyResponse":
        return cls(
            id=item.id,
            source_text=item.source_text,
            translated_text=item.translated_text,
            source_lang=item.source_lang,
            target_lang=item.target_lang,
            created_at=item.created_at,
            last_reviewed_at=item.last_reviewed_at,
            review_count=item.review_count,
            ease_factor=item.ease_factor,
            interval=item.interval,
            repetitions=item.repetitions,
            next_review_due=item.next_review_due,
        )
    


class ReviewRequest(BaseModel):
    rating: Literal["again", "hard", "good", "easy"]
