from uuid import uuid4

from vocablens.services.content_quality_gate_service import ContentQualityGateService
from vocablens.providers.llm.base import LLMProvider
from vocablens.services.exercise_template_registry_service import ExerciseTemplateRegistryService
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.learning_graph_service import LearningGraphService


class LessonGenerationService:

    def __init__(
        self,
        llm: LLMProvider,
        graph_service: LearningGraphService,
        learning_engine: LearningEngine | None = None,
        content_quality_gate_service: ContentQualityGateService | None = None,
        template_registry_service: ExerciseTemplateRegistryService | None = None,
    ):
        self.llm = llm
        self.graph_service = graph_service
        self.learning_engine = learning_engine
        self.content_quality_gate = content_quality_gate_service
        self.template_registry = template_registry_service

    async def generate_lesson(self, user_id: int):

        graph = await self.graph_service.build_graph(user_id)
        recommendation = None
        if self.learning_engine:
            recommendation = await self.learning_engine.recommend(user_id)

        vocab = []

        for cluster_words in graph.values():
            vocab.extend(cluster_words[:5])

        vocab = vocab[:20]

        blueprint = await self._template_blueprint(recommendation, vocab)
        fallback_exercises = self._fallback_exercises(blueprint, recommendation, vocab)

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

        Exercise templates:
        {[
            {
                "template_key": item["template_key"],
                "type": item["type"],
                "objective": item["objective"],
                "difficulty": item["difficulty"],
                "question_contract": item["question"],
                "answer_contract": item["answer"],
                "choices_contract": item.get("choices", []),
            }
            for item in fallback_exercises
        ]}

        Return JSON:

        {{
          "exercises":[
           {{
             "template_key":"",
             "type":"fill_blank",
             "question":"",
             "answer":""
            }},
            {{
             "template_key":"",
             "type":"multiple_choice",
             "question":"",
             "choices":[],
             "answer":""
   }}
  ]
}}
        """

        generated_lesson = (await self.llm.generate_json_with_usage(prompt)).content
        generated_exercises = list(dict(generated_lesson or {}).get("exercises") or [])
        lesson = {
            "exercises": self._merged_exercises(
                blueprint=blueprint,
                fallback_exercises=fallback_exercises,
                generated_exercises=generated_exercises,
            )
        }
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

    async def _template_blueprint(self, recommendation, vocab: list[str]):
        if self.template_registry is None:
            return []
        return await self.template_registry.get_lesson_blueprint(recommendation, vocab)

    def _fallback_exercises(self, blueprint, recommendation, vocab: list[str]) -> list[dict]:
        if self.template_registry is None:
            return []
        return self.template_registry.render_exercises(
            blueprint=blueprint,
            recommendation=recommendation,
            vocab=vocab,
        )

    def _merged_exercises(self, *, blueprint, fallback_exercises: list[dict], generated_exercises: list[dict]) -> list[dict]:
        if self.template_registry is None:
            return generated_exercises or fallback_exercises
        return self.template_registry.merge_generated_exercises(
            blueprint=blueprint,
            fallback_exercises=fallback_exercises,
            generated_exercises=generated_exercises,
        )
