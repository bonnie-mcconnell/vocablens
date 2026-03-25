from fastapi import Depends

from vocablens.api.dependencies_core import (
    get_cached_translator,
    get_llm_provider,
    get_personalization_service,
    get_tts_provider,
    get_tutor_mode_service,
    get_uow_factory,
    get_whisper_provider,
    get_word_extractor,
)
from vocablens.api.dependencies_product import (
    get_content_quality_gate_service,
    get_event_service,
    get_gamification_service,
    get_global_decision_engine,
    get_learning_engine,
    get_learning_event_service,
    get_onboarding_service,
    get_paywall_service,
    get_progress_service,
    get_retention_engine,
    get_skill_tracking_service,
    get_subscription_service,
    get_wow_engine,
)
from vocablens.infrastructure.db.session import AsyncSessionMaker
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.services.conversation_memory_service import ConversationMemoryService
from vocablens.services.conversation_service import ConversationService
from vocablens.services.conversation_vocab_service import ConversationVocabularyService
from vocablens.services.drill_generation_service import DrillGenerationService
from vocablens.services.explanation_service import ExplainMyThinkingService
from vocablens.services.frontend_service import FrontendService
from vocablens.services.knowledge_graph_service import KnowledgeGraphService
from vocablens.services.language_brain_service import LanguageBrainService
from vocablens.services.learning_graph_service import LearningGraphService
from vocablens.services.learning_roadmap_service import LearningRoadmapService
from vocablens.services.lesson_generation_service import LessonGenerationService
from vocablens.services.mistake_engine import MistakeEngine
from vocablens.services.scenario_service import ScenarioService
from vocablens.services.speech_conversation_service import SpeechConversationService
from vocablens.services.streaming_tutor_service import StreamingTutorService
from vocablens.services.vocabulary_service import VocabularyService


async def get_vocabulary_service(
    translator=Depends(get_cached_translator),
    learning_events=Depends(get_learning_event_service),
    event_service=Depends(get_event_service),
    learning_engine=Depends(get_learning_engine),
    extractor=Depends(get_word_extractor),
):
    uow_factory = UnitOfWorkFactory(AsyncSessionMaker)
    return VocabularyService(
        translator,
        uow_factory,
        extractor,
        events=learning_events,
        event_service=event_service,
        learning_engine=learning_engine,
    )


async def get_conversation_service(
    llm_provider=Depends(get_llm_provider),
    uow_factory=Depends(get_uow_factory),
    skill_tracker=Depends(get_skill_tracking_service),
    learning_events=Depends(get_learning_event_service),
    vocab_service=Depends(get_vocabulary_service),
    learning_engine=Depends(get_learning_engine),
    tutor_mode_service=Depends(get_tutor_mode_service),
    subscription_service=Depends(get_subscription_service),
    event_service=Depends(get_event_service),
    paywall_service=Depends(get_paywall_service),
    wow_engine=Depends(get_wow_engine),
    extractor=Depends(get_word_extractor),
):
    mistake_engine = MistakeEngine(llm_provider, uow_factory)
    drill_service = DrillGenerationService(llm_provider)
    explanation_service = ExplainMyThinkingService(llm_provider)
    brain = LanguageBrainService(mistake_engine, drill_service, explanation_service, skill_tracker)
    memory = ConversationMemoryService()
    vocab_extractor = ConversationVocabularyService(
        extractor,
        vocab_service,
        uow_factory,
    )
    return ConversationService(
        llm_provider,
        uow_factory,
        brain,
        memory,
        vocab_extractor,
        skill_tracker,
        learning_events,
        learning_engine,
        tutor_mode_service,
        subscription_service,
        event_service,
        paywall_service,
        wow_engine,
    )


async def get_streaming_tutor_service(
    conversation_service=Depends(get_conversation_service),
    tutor_mode_service=Depends(get_tutor_mode_service),
) -> StreamingTutorService:
    return StreamingTutorService(conversation_service, tutor_mode_service)


async def get_speech_conversation_service(
    speech_provider=Depends(get_whisper_provider),
    tts_provider=Depends(get_tts_provider),
    conversation_service=Depends(get_conversation_service),
) -> SpeechConversationService:
    return SpeechConversationService(
        speech_provider,
        tts_provider,
        conversation_service,
    )


def get_learning_graph_service(uow_factory=Depends(get_uow_factory)) -> LearningGraphService:
    return LearningGraphService(uow_factory)


def get_lesson_generation_service(
    llm_provider=Depends(get_llm_provider),
    graph_service=Depends(get_learning_graph_service),
    learning_engine=Depends(get_learning_engine),
    content_quality_gate_service=Depends(get_content_quality_gate_service),
) -> LessonGenerationService:
    return LessonGenerationService(llm_provider, graph_service, learning_engine, content_quality_gate_service)


def get_scenario_service(llm_provider=Depends(get_llm_provider)) -> ScenarioService:
    return ScenarioService(llm_provider)


def get_knowledge_graph_service(uow_factory=Depends(get_uow_factory)) -> KnowledgeGraphService:
    return KnowledgeGraphService(uow_factory)


def get_learning_roadmap_service(
    graph_service=Depends(get_learning_graph_service),
    skill_tracker=Depends(get_skill_tracking_service),
    retention_engine=Depends(get_retention_engine),
    uow_factory=Depends(get_uow_factory),
    learning_engine=Depends(get_learning_engine),
    personalization=Depends(get_personalization_service),
) -> LearningRoadmapService:
    return LearningRoadmapService(
        graph_service,
        skill_tracker,
        retention_engine,
        uow_factory,
        learning_engine,
        personalization,
    )


def get_frontend_service(
    uow_factory=Depends(get_uow_factory),
    learning_engine=Depends(get_learning_engine),
    roadmap_service=Depends(get_learning_roadmap_service),
    retention_engine=Depends(get_retention_engine),
    subscription_service=Depends(get_subscription_service),
    paywall_service=Depends(get_paywall_service),
    progress_service=Depends(get_progress_service),
    global_decision_engine=Depends(get_global_decision_engine),
    onboarding_service=Depends(get_onboarding_service),
) -> FrontendService:
    return FrontendService(
        uow_factory,
        learning_engine,
        roadmap_service,
        retention_engine,
        subscription_service,
        paywall_service,
        progress_service,
        global_decision_engine,
        onboarding_service,
    )
