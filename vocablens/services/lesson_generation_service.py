from uuid import uuid4

from vocablens.services.content_quality_gate_service import ContentQualityGateService
from vocablens.providers.llm.base import LLMProvider
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.learning_graph_service import LearningGraphService


class LessonGenerationService:

    def __init__(
        self,
        llm: LLMProvider,
        graph_service: LearningGraphService,
        learning_engine: LearningEngine | None = None,
        content_quality_gate_service: ContentQualityGateService | None = None,
    ):
        self.llm = llm
        self.graph_service = graph_service
        self.learning_engine = learning_engine
        self.content_quality_gate = content_quality_gate_service

    async def generate_lesson(self, user_id: int):

        graph = await self.graph_service.build_graph(user_id)
        recommendation = None
        if self.learning_engine:
            recommendation = await self.learning_engine.recommend(user_id)

        vocab = []

        for cluster_words in graph.values():
            vocab.extend(cluster_words[:5])

        vocab = vocab[:20]

        prompt = f"""
Create a language learning lesson.

Vocabulary:
{vocab}

Priority:
{recommendation.action if recommendation else "balanced_practice"}

Target:
{recommendation.target if recommendation else "general"}

Lesson difficulty:
{recommendation.lesson_difficulty if recommendation else "medium"}

Preferred content type:
{recommendation.content_type if recommendation else "mixed"}

Return JSON:

{{
  "exercises":[
   {{
     "type":"fill_blank",
     "question":"",
     "answer":""
   }},
   {{
     "type":"multiple_choice",
     "question":"",
     "choices":[],
     "answer":""
   }}
  ]
}}
"""

        lesson = (await self.llm.generate_json_with_usage(prompt)).content
        if recommendation:
            lesson["next_action"] = {
                "action": recommendation.action,
                "target": recommendation.target,
                "reason": recommendation.reason,
                "lesson_difficulty": recommendation.lesson_difficulty,
                "content_type": recommendation.content_type,
            }
        if self.content_quality_gate is not None:
            report = await self.content_quality_gate.validate_generated_lesson(
                user_id=user_id,
                reference_id=uuid4().hex,
                lesson=lesson,
            )
            self.content_quality_gate.ensure_passed(report)
        return lesson
