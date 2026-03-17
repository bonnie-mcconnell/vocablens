from dataclasses import dataclass
from typing import Literal
from datetime import datetime, timedelta

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.retention_engine import RetentionEngine

NextAction = Literal["review_word", "learn_new_word", "practice_grammar", "conversation_drill"]


@dataclass
class LearningRecommendation:
    action: NextAction
    target: str | None
    reason: str


class LearningEngine:
    """
    Decides the next best learning action using vocabulary mastery, skills,
    recent learning events, and the knowledge graph.
    """

    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        retention_engine: RetentionEngine | None = None,
    ):
        self._uow_factory = uow_factory
        self._retention = retention_engine or RetentionEngine()

    async def recommend(self, user_id: int) -> LearningRecommendation:
        async with self._uow_factory() as uow:
            # 1) Vocabulary signals
            due_items = await uow.vocab.list_due(user_id)
            total_vocab = await uow.vocab.list_all(user_id, limit=200, offset=0)

            # 2) Skill signals
            skills = await uow.skill_tracking.latest_scores(user_id)
            grammar_score = skills.get("grammar", 0.5)
            vocab_score = skills.get("vocabulary", 0.5)
            fluency_score = skills.get("fluency", 0.5)

            # 3) Knowledge graph sparsity (find smallest cluster)
            kg = await uow.knowledge_graph.list_clusters() if hasattr(uow.knowledge_graph, "list_clusters") else None
            sparse_cluster = None
            if kg:
                sparse_cluster = min(kg, key=lambda k: len(kg[k])) if kg else None

            # 4) Mistake patterns
            patterns = await uow.mistake_patterns.top_patterns(user_id, limit=3)

            # 5) Recent learning events (last 24h)
            yesterday = datetime.utcnow() - timedelta(hours=24)
            recent_events = await uow.learning_events.list_since(user_id, since=yesterday) if hasattr(uow.learning_events, "list_since") else []

            await uow.commit()

        # Decide action
        if due_items:
            reason = f"{len(due_items)} items due for review"
            return LearningRecommendation("review_word", due_items[0].source_text, reason)

        if grammar_score < 0.45 or any(p.category == "grammar" for p in (patterns or [])):
            return LearningRecommendation("practice_grammar", "grammar", "Grammar skill below threshold")

        if vocab_score < 0.5 or sparse_cluster or any(p.category == "vocabulary" for p in (patterns or [])):
            target = sparse_cluster or "general"
            return LearningRecommendation("learn_new_word", target, "Vocabulary coverage low in cluster")

        if patterns:
            top = patterns[0]
            return LearningRecommendation("conversation_drill", top.pattern, "Address repeated errors")

        # default: conversation drill to improve fluency
        return LearningRecommendation("conversation_drill", None, "Balance with fluency practice")
