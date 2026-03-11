from vocablens.providers.speech.whisper_provider import WhisperProvider
from vocablens.providers.speech.tts_provider import TextToSpeechProvider
from vocablens.services.conversation_service import ConversationService


class SpeechConversationService:
    """
    Handles speech conversation loop.

    audio → text → conversation → speech
    """

    def __init__(
        self,
        speech_to_text: WhisperProvider,
        text_to_speech: TextToSpeechProvider,
        conversation_service: ConversationService,
    ):
        self.stt = speech_to_text
        self.tts = text_to_speech
        self.conversation = conversation_service

    def process_audio(
        self,
        user_id: int,
        audio_path: str,
        source_lang: str,
        target_lang: str,
    ):

        transcript = self.stt.transcribe(audio_path)

        response = self.conversation.generate_reply(
            user_id=user_id,
            user_message=transcript,
            source_lang=source_lang,
            target_lang=target_lang,
        )

        speech = self.tts.synthesize(response["reply"])

        return {
            "transcript": transcript,
            "reply": response,
            "speech": speech,
        }