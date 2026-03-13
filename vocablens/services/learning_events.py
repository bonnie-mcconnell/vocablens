from pydantic import BaseModel, Field
from typing import List, Union, Optional, Dict, Any


class ConversationTurnEvent(BaseModel):
    event_type: str = Field("conversation_turn", const=True)
    message: str
    mistakes: Dict[str, Any] = {}
    new_words: List[str] = []


class WordLearnedEvent(BaseModel):
    event_type: str = Field("word_learned", const=True)
    words: List[str]
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None


class WordReviewedEvent(BaseModel):
    event_type: str = Field("word_reviewed", const=True)
    item_id: int
    quality: int


class MistakeDetectedEvent(BaseModel):
    event_type: str = Field("mistake_detected", const=True)
    mistakes: Dict[str, Any]


class SkillUpdateEvent(BaseModel):
    event_type: str = Field("skill_update", const=True)
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
