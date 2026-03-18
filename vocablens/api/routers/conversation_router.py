from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from vocablens.api.dependencies import get_current_user, get_conversation_service, get_speech_conversation_service
from vocablens.domain.user import User
from vocablens.services.conversation_service import ConversationService
from vocablens.services.speech_conversation_service import SpeechConversationService


def create_conversation_router() -> APIRouter:

    router = APIRouter(
        prefix="/conversation",
        tags=["Conversation"],
    )

    @router.post("/chat")
    async def chat(
        message: Annotated[str, Query(min_length=1, max_length=2000)],
        source_lang: Annotated[str, Query(min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")],
        target_lang: Annotated[str, Query(min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")],
        tutor_mode: bool = True,
        user: User = Depends(get_current_user),
        service: ConversationService = Depends(get_conversation_service),
    ):

        if not message or not message.strip():
            raise HTTPException(400, "Message cannot be empty")

        reply = await service.generate_reply(
            user.id,
            message,
            source_lang,
            target_lang,
            tutor_mode,
        )

        return reply

    @router.post("/speech")
    async def speech_conversation(
        audio_path: Annotated[str, Query(min_length=1, max_length=512)],
        source_lang: Annotated[str, Query(min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")],
        target_lang: Annotated[str, Query(min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")],
        tutor_mode: bool = True,
        user: User = Depends(get_current_user),
        speech_service: SpeechConversationService = Depends(get_speech_conversation_service),
    ):

        return await speech_service.process_audio(
            user.id,
            audio_path,
            source_lang,
            target_lang,
            tutor_mode,
        )

    return router
