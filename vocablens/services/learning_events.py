from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class ConversationTurnEvent(BaseModel):
    event_type: Literal["conversation_turn"] = "conversation_turn"
    message: str
    mistakes: Dict[str, Any] = Field(default_factory=dict)
    new_words: List[str] = Field(default_factory=list)


class WordLearnedEvent(BaseModel):
    event_type: Literal["word_learned"] = "word_learned"
    words: List[str]
    item_id: Optional[int] = None
    source_text: Optional[str] = None
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None


class WordReviewedEvent(BaseModel):
    event_type: Literal["word_reviewed"] = "word_reviewed"
    item_id: int
    quality: int
    response_accuracy: Optional[float] = None


class MistakeDetectedEvent(BaseModel):
    event_type: Literal["mistake_detected"] = "mistake_detected"
    mistakes: Dict[str, Any]


class SkillUpdateEvent(BaseModel):
    event_type: Literal["skill_update"] = "skill_update"
    grammar: Optional[float] = None
    vocabulary: Optional[float] = None
    fluency: Optional[float] = None


LearningEvent = Union[
    ConversationTurnEvent,
    WordLearnedEvent,
    WordReviewedEvent,
    MistakeDetectedEvent,
    SkillUpdateEvent,
]
