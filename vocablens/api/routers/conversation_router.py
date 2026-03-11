from fastapi import APIRouter, Depends

from vocablens.api.dependencies import get_current_user
from vocablens.domain.user import User
from vocablens.services.conversation_service import ConversationService
from vocablens.services.speech_conversation_service import SpeechConversationService


def create_conversation_router(
    service: ConversationService,
    speech_service: SpeechConversationService,
) -> APIRouter:

    router = APIRouter(
        prefix="/conversation",
        tags=["Conversation"],
    )

    @router.post("/chat")
    def chat(
        message: str,
        source_lang: str,
        target_lang: str,
        user: User = Depends(get_current_user),
    ):

        reply = service.generate_reply(
            user.id,
            message,
            source_lang,
            target_lang,
        )

        return reply

    @router.post("/speech")
    def speech_conversation(
        audio_path: str,
        source_lang: str,
        target_lang: str,
        user: User = Depends(get_current_user),
    ):

        return speech_service.process_audio(
            user.id,
            audio_path,
            source_lang,
            target_lang,
        )

    return router