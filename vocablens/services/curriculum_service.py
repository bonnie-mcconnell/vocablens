from vocablens.services.learning_graph_service import LearningGraphService
from vocablens.services.skill_tracking_service import SkillTrackingService


class CurriculumService:
    """
    Generates a personalized learning plan
    based on vocabulary graph and skill model.
    """

    def __init__(
        self,
        graph_service: LearningGraphService,
        skill_service: SkillTrackingService,
    ):
        self.graph = graph_service
        self.skills = skill_service

    def generate_plan(self, user_id: int):

        vocab_graph = self.graph.build_graph(user_id)

        next_cluster = self.graph.recommend_next_cluster(user_id)

        skill_profile = self.skills.get_skill_profile(user_id)

        return {
            "focus_cluster": next_cluster,
            "vocabulary_clusters": vocab_graph,
            "skill_profile": skill_profile,
            "recommended_actions": [
                "conversation practice",
                "targeted drills",
                "review vocabulary",
            ],
        }