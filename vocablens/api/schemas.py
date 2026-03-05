from pydantic import BaseModel, Field
from datetime import datetime
from vocablens.domain.models import VocabularyItem
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    

class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source_lang: str = Field(..., min_length=2, max_length=10)
    target_lang: str = Field(..., min_length=2, max_length=10)


class VocabularyResponse(BaseModel):
    id: int | None
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    created_at: datetime
    last_reviewed_at: datetime | None
    review_count: int
    retention_score: float
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
            retention_score=item.retention_score,
            next_review_due=item.next_review_due,
        )
    


class ReviewRequest(BaseModel):
    rating: str