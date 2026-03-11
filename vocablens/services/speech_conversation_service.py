from vocablens.providers.speech.whisper_provider import WhisperProvider
from vocablens.providers.speech.tts_provider import TextToSpeechProvider
from vocablens.services.conversation_service import ConversationService


class SpeechConversationService:
    """
    Handles full speech conversation loop.

    audio → text → AI conversation → speech response
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
        language: str,
    ):

        text = self.stt.transcribe(audio_path)

        reply = self.conversation.generate_reply(
            user_id,
            text,
            language,
        )

        speech = self.tts.synthesize(reply["reply"])

        return {
            "transcript": text,
            "reply": reply,
            "speech": speech,
        }