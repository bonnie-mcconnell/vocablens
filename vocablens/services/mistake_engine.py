from vocablens.providers.llm.base import LLMProvider
from vocablens.prompts import load_prompt
from vocablens.infrastructure.unit_of_work import UnitOfWork


class MistakeEngine:
    """
    Analyzes learner messages for mistakes using LLM and records patterns.
    """

    def __init__(self, llm: LLMProvider, uow_factory: type[UnitOfWork] | None = None):
        self.llm = llm
        self.template = load_prompt("mistake_analysis_prompt")
        self._uow_factory = uow_factory

    async def analyze(self, user_id: int, message: str, language: str):
        prompt = self.template.format(
            message=message,
            language=language,
        )

        analysis = self.llm.generate_json(prompt)

        # store patterns if possible
        if self._uow_factory:
            grammar = analysis.get("grammar_mistakes", []) or []
            vocab = analysis.get("vocab_misuse", []) or []
            repeats = analysis.get("repeated_errors", []) or []
            async with self._uow_factory() as uow:
                for m in grammar:
                    await uow.mistake_patterns.record(user_id, "grammar", str(m))
                for m in vocab:
                    await uow.mistake_patterns.record(user_id, "vocabulary", str(m))
                for m in repeats:
                    await uow.mistake_patterns.record(user_id, "repetition", str(m))
                await uow.commit()

        return analysis
