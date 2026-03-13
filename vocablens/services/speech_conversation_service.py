from vocablens.providers.speech.whisper_provider import WhisperProvider
from vocablens.providers.speech.tts_provider import TextToSpeechProvider
from vocablens.services.conversation_service import ConversationService


class SpeechConversationService:
    """
    Voice conversation pipeline.

    audio -> STT -> conversation -> TTS
    """

    def __init__(
        self,
        speech_provider: WhisperProvider,
        tts_provider: TextToSpeechProvider,
        conversation_service: ConversationService,
    ):
        self.speech = speech_provider
        self.tts = tts_provider
        self.conversation = conversation_service

    def process_audio(
        self,
        user_id: int,
        audio_path: str,
        source_lang: str,
        target_lang: str,
    ):

        transcript = self.speech.transcribe(audio_path)

        reply = self.conversation.generate_reply(
            user_id=user_id,
            user_message=transcript,
            source_lang=source_lang,
            target_lang=target_lang,
        )

        audio_reply = self.tts.speak(
            reply["reply"],
            source_lang,
        )

        return {
            "transcript": transcript,
            "reply": reply,
            "audio_reply": audio_reply,
        }