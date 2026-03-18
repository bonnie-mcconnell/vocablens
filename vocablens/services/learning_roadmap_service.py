from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.services.learning_graph_service import LearningGraphService
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.spaced_repetition_service import SpacedRepetitionService
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.personalization_service import PersonalizationService


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
        learning_engine: LearningEngine | None = None,
        personalization: PersonalizationService | None = None,
    ):
        self.graph = graph_service
        self.skills = skill_tracker
        self.retention = retention_engine
        self._uow_factory = uow_factory
        self.srs = SpacedRepetitionService()
        self._engine = learning_engine
        self._personalization = personalization

    async def generate_today_plan(self, user_id: int):

        async with self._uow_factory() as uow:
            items = await uow.vocab.list_all(user_id, limit=1000, offset=0)

        due = [
            i for i in items
            if i.next_review_due and i.next_review_due <= self._today_cutoff()
        ]

        review_count = min(len(due), 25)

        next_cluster = await self.graph.recommend_next_cluster(user_id)

        skill_profile = self.skills.get_skill_profile(user_id)

        grammar_focus = self._select_grammar_focus(skill_profile)
        next_action = None
        personalization = None
        retention = None
        if self._engine:
            rec = await self._engine.recommend(user_id)
            next_action = {
                "action": rec.action,
                "target": rec.target,
                "reason": rec.reason,
                "lesson_difficulty": rec.lesson_difficulty,
                "review_frequency_multiplier": rec.review_frequency_multiplier,
                "content_type": rec.content_type,
            }
        if self._personalization:
            profile = await self._personalization.get_profile(user_id)
            adaptation = await self._personalization.get_adaptation(user_id)
            personalization = {
                "learning_speed": profile.learning_speed,
                "retention_rate": profile.retention_rate,
                "difficulty_preference": profile.difficulty_preference,
                "content_preference": profile.content_preference,
                "lesson_difficulty": adaptation.lesson_difficulty,
                "review_frequency_multiplier": adaptation.review_frequency_multiplier,
                "content_type": adaptation.content_type,
            }
        if hasattr(self.retention, "assess_user"):
            assessment = await self.retention.assess_user(user_id)
            retention = {
                "state": assessment.state,
                "drop_off_risk": assessment.drop_off_risk,
                "session_frequency": assessment.session_frequency,
                "current_streak": assessment.current_streak,
                "longest_streak": assessment.longest_streak,
                "is_high_engagement": assessment.is_high_engagement,
                "actions": [
                    {
                        "kind": action.kind,
                        "reason": action.reason,
                        "target": action.target,
                    }
                    for action in assessment.suggested_actions
                ],
            }

        return {
            "review_words": review_count,
            "conversation_topic": next_cluster,
            "grammar_focus": grammar_focus,
            "next_cluster": next_cluster,
            "next_action": next_action,
            "personalization": personalization,
            "retention": retention,
        }

    def _today_cutoff(self):
        return utc_now() + timedelta(days=1)

    def _select_grammar_focus(self, skill_profile):

        grammar = skill_profile.get("grammar", 0.5)

        if grammar < 0.4:
            return "basic sentence structure"

        if grammar < 0.7:
            return "past tense"

        return "complex sentences"
