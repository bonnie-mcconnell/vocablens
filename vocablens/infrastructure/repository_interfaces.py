from typing import Protocol, List, Optional, Any, Dict
from datetime import datetime

from vocablens.domain.models import VocabularyItem, UserLearningState, UserEngagementState, UserProgressState
from vocablens.domain.user import User


class VocabularyRepository(Protocol):
    async def add(self, user_id: int, item: VocabularyItem) -> VocabularyItem: ...
    async def list_all(self, user_id: int, limit: int, offset: int) -> List[VocabularyItem]: ...
    async def list_due(self, user_id: int) -> List[VocabularyItem]: ...
    async def get(self, user_id: int, item_id: int) -> Optional[VocabularyItem]: ...
    async def exists(self, user_id: int, source_text: str, source_lang: str, target_lang: str) -> bool: ...
    async def update(self, item: VocabularyItem) -> VocabularyItem: ...
    async def update_enrichment(
        self,
        item_id: int,
        example_source: str | None,
        example_translation: str | None,
        grammar: str | None,
        cluster: str | None,
    ) -> None: ...


class UserRepository(Protocol):
    async def create(self, email: str, password_hash: str) -> User: ...
    async def get_by_email(self, email: str) -> Optional[User]: ...
    async def get_by_id(self, user_id: int) -> Optional[User]: ...
    async def list_all(self) -> List[User]: ...


class TranslationCacheRepository(Protocol):
    async def get(self, text: str, source_lang: str, target_lang: str) -> Optional[str]: ...
    async def save(self, text: str, source_lang: str, target_lang: str, translation: str) -> None: ...


class ConversationRepository(Protocol):
    async def save_turn(self, user_id: int, role: str, message: str, created_at: datetime | None = None) -> None: ...


class LearningEventRepository(Protocol):
    async def record(self, user_id: int, event_type: str, payload_json: str) -> None: ...


class EventRepository(Protocol):
    async def record(
        self,
        *,
        user_id: int,
        event_type: str,
        payload: Dict[str, Any],
        created_at: datetime | None = None,
    ) -> None: ...
    async def list_by_user(self, user_id: int, limit: int = 1000) -> List[Any]: ...
    async def list_by_type(self, event_type: str, limit: int = 1000) -> List[Any]: ...
    async def list_since(self, since: datetime, event_types: List[str] | None = None, limit: int = 5000) -> List[Any]: ...


class SkillTrackingRepository(Protocol):
    async def record(self, user_id: int, skill: str, score: float, created_at: datetime | None = None) -> None: ...
    async def latest_scores(self, user_id: int) -> Dict[str, float]: ...


class KnowledgeGraphRepository(Protocol):
    async def add_edge(self, source_node: str, target_node: str, relation_type: str, weight: float = 1.0) -> None: ...
    async def list_edges(self) -> List[Dict]: ...


class EmbeddingRepository(Protocol):
    async def store(self, word: str, embedding: List[float]) -> None: ...
    async def get(self, word: str) -> Optional[List[float]]: ...


class ExperimentAssignmentRepository(Protocol):
    async def get(self, user_id: int, experiment_key: str) -> Optional[Any]: ...
    async def list_all(self, experiment_key: str | None = None) -> List[Any]: ...
    async def create(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        assigned_at: datetime | None = None,
    ) -> Any: ...


class UserLearningStateRepository(Protocol):
    async def get_or_create(self, user_id: int) -> UserLearningState: ...
    async def update(
        self,
        user_id: int,
        *,
        skills: Dict[str, float] | None = None,
        weak_areas: List[str] | None = None,
        mastery_percent: float | None = None,
        accuracy_rate: float | None = None,
        response_speed_seconds: float | None = None,
    ) -> UserLearningState: ...


class UserEngagementStateRepository(Protocol):
    async def get_or_create(self, user_id: int) -> UserEngagementState: ...
    async def update(
        self,
        user_id: int,
        *,
        current_streak: int | None = None,
        longest_streak: int | None = None,
        momentum_score: float | None = None,
        total_sessions: int | None = None,
        sessions_last_3_days: int | None = None,
        last_session_at: datetime | None = None,
        shields_used_this_week: int | None = None,
        daily_mission_completed_at: datetime | None = None,
        interaction_stats: Dict[str, int] | None = None,
    ) -> UserEngagementState: ...


class UserProgressStateRepository(Protocol):
    async def get_or_create(self, user_id: int) -> UserProgressState: ...
    async def update(
        self,
        user_id: int,
        *,
        xp: int | None = None,
        level: int | None = None,
        milestones: List[int] | None = None,
    ) -> UserProgressState: ...
