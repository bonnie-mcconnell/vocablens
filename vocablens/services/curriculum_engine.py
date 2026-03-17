from typing import Dict, List
from datetime import datetime, timedelta

from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.knowledge_graph_service import KnowledgeGraphService
from vocablens.services.spaced_repetition_service import SpacedRepetitionService
from vocablens.infrastructure.postgres_vocabulary_repository import PostgresVocabularyRepository


class CurriculumEngine:
    """
    Generates a daily learning plan using skills, knowledge graph, and review schedule.
    """

    def __init__(
        self,
        skill_tracker: SkillTrackingService,
        kg_service: KnowledgeGraphService,
        vocab_repo: PostgresVocabularyRepository,
    ):
        self.skills = skill_tracker
        self.kg = kg_service
        self.vocab_repo = vocab_repo
        self.srs = SpacedRepetitionService()

    def daily_plan(self, user_id: int) -> Dict:
        skill_profile = self.skills.get_skill_profile(user_id)
        graph = self.kg.build_graph(user_id)

        items = self.vocab_repo.list_all_sync(user_id, limit=1000, offset=0)
        due = [
            i for i in items
            if i.next_review_due and i.next_review_due <= datetime.utcnow()
        ]

        review_words = [i.source_text for i in due[:15]]

        topic = self._select_topic(graph)
        grammar_focus = self._select_grammar(skill_profile)

        return {
            "review_words": review_words,
            "new_words": graph["topics"].get(topic, [])[:5] if graph else [],
            "grammar_focus": grammar_focus,
            "conversation_topic": topic or "general",
        }

    def _select_topic(self, graph):
        if not graph or not graph.get("topics"):
            return "general"
        # choose smallest cluster
        topics = graph["topics"]
        return min(topics.items(), key=lambda kv: len(kv[1]))[0]

    def _select_grammar(self, skills):
        g = skills.get("grammar", 0.5)
        if g < 0.4:
            return "basic sentence structure"
        if g < 0.7:
            return "past tense"
        return "complex sentences"
