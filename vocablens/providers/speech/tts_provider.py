from openai import OpenAI

from vocablens.config.settings import settings
from vocablens.infrastructure.resilience import CircuitBreaker, sync_retry


class TextToSpeechProvider:
    """
    Converts AI responses to speech with retries and circuit breaking.
    """

    def __init__(self):
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY or None,
            timeout=settings.TTS_TIMEOUT,
            max_retries=0,
        )
        self._circuit = CircuitBreaker(
            name="openai_tts",
            failure_threshold=settings.CIRCUIT_BREAKER_THRESHOLD,
            reset_timeout_seconds=settings.CIRCUIT_BREAKER_RESET_SECONDS,
        )

    def synthesize(self, text: str, voice: str = "alloy"):
        def _call():
            self._circuit.ensure_closed()
            try:
                response = self._client.audio.speech.create(
                    model="gpt-4o-mini-tts",
                    voice=voice,
                    input=text,
                )
            except Exception:
                self._circuit.record_failure()
                raise
            self._circuit.record_success()
            return response

        return sync_retry(
            name="openai_tts",
            func=_call,
            attempts=settings.TTS_MAX_RETRIES,
            backoff_base=0.5,
        )
