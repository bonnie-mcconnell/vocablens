import json
from typing import Callable, List

from vocablens.providers.llm.base import LLMProvider

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.conversation_memory_service import ConversationMemoryService
from vocablens.services.conversation_learning_mapper import ConversationLearningMapper
from vocablens.services.conversation_response_builder import ConversationResponseBuilder
from vocablens.services.conversation_vocab_service import ConversationVocabularyService
from vocablens.services.language_brain_service import LanguageBrainService
from vocablens.services.learning_event_service import LearningEventService
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.event_service import EventService
from vocablens.services.paywall_service import PaywallService
from vocablens.services.subscription_service import SubscriptionService
from vocablens.services.subscription_service import SubscriptionFeatures
from vocablens.services.tutor_mode_service import TutorModeService
from vocablens.services.wow_engine import WowEngine
from vocablens.prompts import load_prompt


class ConversationService:
    """
    Generates AI tutor replies and records learning signals.
    """

    def __init__(
        self,
        llm: LLMProvider,
        uow_factory: Callable[[], UnitOfWork],
        brain: LanguageBrainService,
        memory: ConversationMemoryService,
        vocab_extractor: ConversationVocabularyService,
        skill_tracker: SkillTrackingService,
        learning_events: LearningEventService,
        learning_engine: LearningEngine | None = None,
        tutor_mode_service: TutorModeService | None = None,
        subscription_service: SubscriptionService | None = None,
        event_service: EventService | None = None,
        paywall_service: PaywallService | None = None,
        wow_engine: WowEngine | None = None,
    ):
        self._llm = llm
        self._uow_factory = uow_factory
        self._brain = brain
        self._memory = memory
        self._vocab_extractor = vocab_extractor
        self._skills = skill_tracker
        self._events = learning_events
        self._learning_engine = learning_engine
        self._tutor_mode = tutor_mode_service or TutorModeService()
        self._subscriptions = subscription_service
        self._event_service = event_service
        self._paywall_service = paywall_service
        self._wow_engine = wow_engine or WowEngine()
        self._template = load_prompt("conversation_prompt")
        self._learning_mapper = ConversationLearningMapper()
        self._responses = ConversationResponseBuilder()

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
        tutor_mode: bool = True,
    ) -> dict:
        if self._event_service:
            await self._event_service.track_event(
                user_id,
                "session_started",
                {"source": "conversation_service", "tutor_mode": tutor_mode},
            )
        features = await self._feature_access(user_id)

        vocab_result = await self._vocab_extractor.process_message_with_items(
            user_id,
            user_message,
            source_lang,
            target_lang,
        )
        new_words = vocab_result.new_words

        brain_output = await self._brain.process_message(
            user_id=user_id,
            message=user_message,
            language=source_lang,
            explanation_quality=features.explanation_quality,
        )
        analysis = brain_output["analysis"]

        skill_profile = self._skills.get_skill_profile(user_id)
        cefr = self._cefr_level(skill_profile)
        grammar_stage = self._grammar_stage(skill_profile)

        history = self._memory.get_recent_context(user_id)

        known_words = await self._get_known_words(user_id)

        vocab_list = ", ".join(known_words)
        recommendation = None
        if self._learning_engine:
            recommendation = await self._learning_engine.recommend(user_id)

        tutor_context = None
        tutor_instructions = ""
        if tutor_mode:
            async with self._uow_factory() as uow:
                profile = await uow.profiles.get_or_create(user_id) if hasattr(uow, "profiles") else None
                patterns = await uow.mistake_patterns.top_patterns(user_id, limit=5) if hasattr(uow, "mistake_patterns") else []
                await uow.commit()
            tutor_context = self._tutor_mode.build_context(profile, list(patterns), recommendation)
            tutor_instructions = self._tutor_mode.prompt_suffix(
                tutor_context,
                brain_output.get("correction_feedback", []),
                tutor_depth=features.tutor_depth,
            )

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
        ) + tutor_instructions

        reply_result = await self._llm.generate_with_usage(prompt)
        reply = reply_result.content

        self._memory.store_turn(user_id, user_message, reply)
        session_turn_count = len(self._memory.memory[user_id]) // 2
        grammar_mistake_count = len(analysis.get("grammar_mistakes", []))
        wow = await self._wow_engine.score_session(
            user_id,
            tutor_mode=tutor_mode,
            correction_feedback_count=len(brain_output.get("correction_feedback", [])),
            new_words_count=len(new_words),
            grammar_mistake_count=grammar_mistake_count,
            session_turn_count=session_turn_count,
            reply_length=len(reply),
        )
        paywall = await self._paywall_service.evaluate(
            user_id,
            wow_moment=wow.qualifies,
            wow_score=wow.score,
        ) if self._paywall_service else None

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
        if self._event_service:
            await self._event_service.track_event(
                user_id,
                "message_sent",
                {
                    "source": "conversation_service",
                    "message_length": len(user_message),
                    "new_words_count": len(new_words),
                    "tutor_mode": tutor_mode,
                    "wow_moment": wow.qualifies,
                    "wow_score": wow.score,
                },
            )
            if grammar_mistake_count:
                await self._event_service.track_event(
                    user_id,
                    "mistake_made",
                    {
                        "source": "conversation_service",
                        "mistake_count": grammar_mistake_count,
                    },
                )
            await self._event_service.track_event(
                user_id,
                "session_ended",
                {
                    "source": "conversation_service",
                    "reply_length": len(reply),
                    "tutor_mode": tutor_mode,
                },
            )

        if self._learning_engine:
            await self._learning_engine.update_knowledge(
                user_id,
                session_result=self._learning_mapper.build_session_result(
                    analysis=analysis,
                    recommendation=recommendation,
                    known_words=known_words,
                    skill_profile=self._skills.get_skill_profile(user_id),
                    learned_item_ids=vocab_result.learned_item_ids,
                ),
            )

        if tutor_mode and tutor_context:
            return self._responses.tutor_response(
                tutor_mode_service=self._tutor_mode,
                brain_output=brain_output,
                recommendation=recommendation,
                tutor_context=tutor_context,
                reply=reply,
                tutor_depth=features.tutor_depth,
                paywall=paywall,
                wow=wow,
            )

        return self._responses.standard_response(
            reply=reply,
            analysis=analysis,
            brain_output=brain_output,
            recommendation=recommendation,
            features=features,
            paywall=paywall,
            wow=wow,
        )

    async def _save_conversation(self, user_id, user_message, reply):

        async with self._uow_factory() as uow:
            await uow.conversation.save_turn(user_id, "student", user_message)
            await uow.conversation.save_turn(user_id, "tutor", reply)
            await uow.commit()

    async def _feature_access(self, user_id: int) -> SubscriptionFeatures:
        if not self._subscriptions:
            return SubscriptionFeatures(
                tier="premium",
                request_limit=10000,
                token_limit=1000000,
                tutor_depth="deep",
                explanation_quality="premium",
                personalization_level="premium",
            )
        features = await self._subscriptions.get_features(user_id)
        await self._subscriptions.record_feature_gate(
            user_id=user_id,
            feature_name="tutor_depth",
            allowed=True,
            current_tier=features.tier,
            required_tier=features.tier,
        )
        await self._subscriptions.record_feature_gate(
            user_id=user_id,
            feature_name="explanation_quality",
            allowed=True,
            current_tier=features.tier,
            required_tier=features.tier,
        )
        return features
