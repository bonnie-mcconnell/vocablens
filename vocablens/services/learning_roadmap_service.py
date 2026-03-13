from vocablens.services.learning_graph_service import LearningGraphService
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository


class LearningRoadmapService:
    """
    Generates a personalized daily learning plan.
    """

    def __init__(
        self,
        graph_service: LearningGraphService,
        skill_tracker: SkillTrackingService,
        retention_engine: RetentionEngine,
        vocab_repo: SQLiteVocabularyRepository,
    ):
        self.graph = graph_service
        self.skills = skill_tracker
        self.retention = retention_engine
        self.repo = vocab_repo

    def generate_today_plan(self, user_id: int):

        items = self.repo.list_all(user_id, limit=1000, offset=0)

        review_count = self.retention.review_load(items)

        next_cluster = self.graph.recommend_next_cluster(user_id)

        skill_profile = self.skills.get_skill_profile(user_id)

        grammar_focus = self._select_grammar_focus(skill_profile)

        return {
            "review_words": review_count,
            "conversation_topic": next_cluster,
            "grammar_focus": grammar_focus,
            "next_cluster": next_cluster,
        }

    def _select_grammar_focus(self, skill_profile):

        grammar = skill_profile.get("grammar", 0.5)

        if grammar < 0.4:
            return "basic sentence structure"

        if grammar < 0.7:
            return "past tense"

        return "complex sentences"