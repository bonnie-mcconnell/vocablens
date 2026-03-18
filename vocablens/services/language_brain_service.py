from vocablens.services.mistake_engine import MistakeEngine
from vocablens.services.drill_generation_service import DrillGenerationService
from vocablens.services.explanation_service import ExplainMyThinkingService
from vocablens.services.skill_tracking_service import SkillTrackingService


class LanguageBrainService:
    """
    Central AI learning intelligence.

    Responsible for:
    - mistake detection
    - skill tracking
    - weakness analysis
    - drill generation
    """

    def __init__(
        self,
        mistake_engine: MistakeEngine,
        drill_generator: DrillGenerationService,
        explanation_service: ExplainMyThinkingService,
        skill_tracker: SkillTrackingService,
    ):
        self._mistake_engine = mistake_engine
        self._drill_generator = drill_generator
        self._explainer = explanation_service
        self._skill_tracker = skill_tracker

    async def process_message(self, user_id: int, message: str, language: str, explanation_quality: str = "premium"):

        # --------------------------------
        # Analyze mistakes
        # --------------------------------

        analysis = await self._mistake_engine.analyze(
            user_id,
            message,
            language,
        )

        # --------------------------------
        # Update adaptive skill model
        # --------------------------------

        await self._skill_tracker.update_from_analysis(
            user_id,
            analysis,
        )

        # --------------------------------
        # Generate targeted drills
        # --------------------------------

        drills = None

        if (
            analysis.get("grammar_mistakes")
            or analysis.get("vocab_misuse")
            or analysis.get("repeated_errors")
        ):

            drills = await self._drill_generator.generate_drills(
                analysis
            )

        explanation = await self._explainer.explain(message, analysis, quality=explanation_quality)

        return {
            "analysis": analysis,
            "drills": drills,
            "correction_feedback": analysis.get("correction_feedback", []),
            "thinking_explanation": explanation,
        }
