from vocablens.services.mistake_engine import MistakeEngine
from vocablens.services.drill_generation_service import DrillGenerationService
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
        skill_tracker: SkillTrackingService,
    ):

        self._mistake_engine = mistake_engine
        self._drill_generator = drill_generator
        self._skill_tracker = skill_tracker

    def process_message(self, user_id: int, message: str, language: str):

        # -----------------------------------
        # Analyze mistakes
        # -----------------------------------

        analysis = self._mistake_engine.analyze(message, language)

        grammar_errors = analysis.get("grammar_mistakes", [])
        vocab_errors = analysis.get("vocab_misuse", [])

        # -----------------------------------
        # Update skill model
        # -----------------------------------

        if grammar_errors:
            self._skill_tracker.record_grammar_error(user_id)

        if vocab_errors:
            self._skill_tracker.record_vocab_error(user_id)

        # -----------------------------------
        # Generate targeted drills
        # -----------------------------------

        drills = None

        if grammar_errors or vocab_errors:

            drills = self._drill_generator.generate_drills(
                analysis
            )

        return {
            "analysis": analysis,
            "drills": drills,
        }