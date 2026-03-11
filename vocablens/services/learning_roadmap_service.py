from vocablens.services.learning_graph_service import LearningGraphService
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.retention_engine import RetentionEngine


class LearningRoadmapService:
    """
    Generates a daily learning roadmap.
    """

    def __init__(
        self,
        graph_service: LearningGraphService,
        skill_service: SkillTrackingService,
        retention_engine: RetentionEngine,
    ):
        self.graph = graph_service
        self.skills = skill_service
        self.retention = retention_engine

    def generate_today_plan(self, user_id: int):

        next_cluster = self.graph.recommend_next_cluster(user_id)

        skills = self.skills.get_skill_profile(user_id)

        grammar_focus = None

        if skills.get("grammar_accuracy", 1) < 0.8:
            grammar_focus = "grammar drills"

        return {
            "review_words": 15,
            "conversation_topic": next_cluster,
            "grammar_focus": grammar_focus or "conversation fluency",
            "next_cluster": next_cluster,
        }