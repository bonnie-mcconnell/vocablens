from vocablens.providers.speech.whisper_provider import WhisperProvider
from vocablens.providers.speech.tts_provider import TextToSpeechProvider
from vocablens.services.conversation_service import ConversationService


class SpeechConversationService:
    """
    Handles voice conversation loop.

    audio -> speech-to-text -> AI conversation -> text-to-speech
    """

    def __init__(
        self,
        speech_provider: WhisperProvider,
        tts_provider: TextToSpeechProvider,
        conversation_service: ConversationService,
    ):
        self._speech = speech_provider
        self._tts = tts_provider
        self._conversation = conversation_service

    def process_audio(
        self,
        user_id: int,
        audio_path: str,
        source_lang: str,
        target_lang: str,
    ):
        # Convert speech to text
        transcript = self._speech.transcribe(audio_path)

        # Generate AI conversation reply
        response = self._conversation.generate_reply(
            user_id=user_id,
            user_message=transcript,
            source_lang=source_lang,
            target_lang=target_lang,
        )

        # Convert reply text to speech
        audio_reply = self._tts.synthesize(response["reply"])

        return {
            "transcript": transcript,
            "reply": response,
            "audio_reply": audio_reply,
        }