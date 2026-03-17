import json
from typing import List

from vocablens.providers.llm.base import LLMProvider

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.language_brain_service import LanguageBrainService
from vocablens.services.conversation_memory_service import ConversationMemoryService
from vocablens.services.conversation_vocab_service import ConversationVocabularyService
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.learning_event_service import LearningEventService
from vocablens.services.learning_engine import LearningEngine
from vocablens.prompts import load_prompt


class ConversationService:
    """
    Generates AI tutor replies and records learning signals.
    """

    def __init__(
        self,
        llm: LLMProvider,
        uow_factory: type[UnitOfWork],
        brain: LanguageBrainService,
        memory: ConversationMemoryService,
        vocab_extractor: ConversationVocabularyService,
        skill_tracker: SkillTrackingService,
        learning_events: LearningEventService,
        learning_engine: LearningEngine | None = None,
    ):
        self._llm = llm
        self._uow_factory = uow_factory
        self._brain = brain
        self._memory = memory
        self._vocab_extractor = vocab_extractor
        self._skills = skill_tracker
        self._events = learning_events
        self._learning_engine = learning_engine
        self._template = load_prompt("conversation_prompt")

    async def _get_known_words(self, user_id: int) -> List[str]:
        async with self._uow_factory() as uow:
            items = await uow.vocab.list_all(user_id, limit=500, offset=0)
        return [i.source_text for i in items][:200]

    def _cefr_level(self, skill_profile: dict) -> str:
        avg = (skill_profile.get("grammar", 0.5) + skill_profile.get("vocabulary", 0.5) + skill_profile.get("fluency", 0.5)) / 3
        if avg < 0.25:
            return "A1"
        if avg < 0.45:
            return "A2"
        if avg < 0.65:
            return "B1"
        if avg < 0.8:
            return "B2"
        if avg < 0.9:
            return "C1"
        return "C2"

    def _grammar_stage(self, skill_profile: dict) -> str:
        g = skill_profile.get("grammar", 0.5)
        if g < 0.4:
            return "basic"
        if g < 0.7:
            return "intermediate"
        return "advanced"

    async def generate_reply(
        self,
        user_id: int,
        user_message: str,
        source_lang: str,
        target_lang: str,
    ) -> dict:

        new_words = await self._vocab_extractor.process_message(
            user_id,
            user_message,
            source_lang,
            target_lang,
        )

        brain_output = await self._brain.process_message(
            user_id=user_id,
            message=user_message,
            language=source_lang,
        )

        analysis = brain_output["analysis"]

        await self._skills.update_from_analysis(user_id, analysis)

        skill_profile = self._skills.get_skill_profile(user_id)
        cefr = self._cefr_level(skill_profile)
        grammar_stage = self._grammar_stage(skill_profile)

        history = self._memory.get_recent_context(user_id)

        known_words = await self._get_known_words(user_id)

        vocab_list = ", ".join(known_words)
        recommendation = None
        if self._learning_engine:
            recommendation = await self._learning_engine.recommend(user_id)

        prompt = self._template.format(
            source_lang=source_lang,
            grammar=skill_profile["grammar"],
            vocabulary=skill_profile["vocabulary"],
            fluency=skill_profile["fluency"],
            cefr=cefr,
            grammar_stage=grammar_stage,
            history=history,
            user_message=user_message,
            vocab_list=vocab_list,
            mistakes=json.dumps(analysis.get("grammar_mistakes", [])),
        )

        reply = self._llm.generate(prompt)

        self._memory.store_turn(user_id, user_message, reply)

        await self._save_conversation(user_id, user_message, reply)

        await self._events.record(
            event_type="conversation_turn",
            user_id=user_id,
            payload={
                "message": user_message,
                "mistakes": analysis,
                "new_words": new_words,
            },
        )

        return {
            "reply": reply,
            "analysis": analysis,
            "drills": brain_output["drills"],
            "next_action": recommendation.action if recommendation else None,
            "next_action_reason": recommendation.reason if recommendation else None,
        }

    async def _save_conversation(self, user_id, user_message, reply):

        async with self._uow_factory() as uow:
            await uow.conversation.save_turn(user_id, "student", user_message)
            await uow.conversation.save_turn(user_id, "tutor", reply)
            await uow.commit()
