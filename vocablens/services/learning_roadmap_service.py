from vocablens.services.learning_graph_service import LearningGraphService
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.spaced_repetition_service import SpacedRepetitionService


class LearningRoadmapService:
    """
    Generates a personalized daily learning plan.
    """

    def __init__(
        self,
        graph_service: LearningGraphService,
        skill_tracker: SkillTrackingService,
        retention_engine: RetentionEngine,
        uow_factory: type[UnitOfWork],
    ):
        self.graph = graph_service
        self.skills = skill_tracker
        self.retention = retention_engine
        self._uow_factory = uow_factory
        self.srs = SpacedRepetitionService()

    async def generate_today_plan(self, user_id: int):

        async with self._uow_factory() as uow:
            items = await uow.vocab.list_all(user_id, limit=1000, offset=0)

        due = [
            i for i in items
            if i.next_review_due and i.next_review_due <= self._today_cutoff()
        ]

        review_count = min(len(due), 25)

        next_cluster = self.graph.recommend_next_cluster(user_id)

        skill_profile = self.skills.get_skill_profile(user_id)

        grammar_focus = self._select_grammar_focus(skill_profile)

        return {
            "review_words": review_count,
            "conversation_topic": next_cluster,
            "grammar_focus": grammar_focus,
            "next_cluster": next_cluster,
        }

    def _today_cutoff(self):
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        return now + timedelta(days=1)

    def _select_grammar_focus(self, skill_profile):

        grammar = skill_profile.get("grammar", 0.5)

        if grammar < 0.4:
            return "basic sentence structure"

        if grammar < 0.7:
            return "past tense"

        return "complex sentences"
