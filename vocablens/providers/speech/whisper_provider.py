from openai import OpenAI

from vocablens.config.settings import settings
from vocablens.infrastructure.resilience import CircuitBreaker, sync_retry


class WhisperProvider:
    """
    Speech -> text transcription using Whisper with retries and a circuit breaker.
    """

    def __init__(self):
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY or None,
            timeout=settings.SPEECH_TIMEOUT,
            max_retries=0,
        )
        self._circuit = CircuitBreaker(
            name="whisper_transcribe",
            failure_threshold=settings.CIRCUIT_BREAKER_THRESHOLD,
            reset_timeout_seconds=settings.CIRCUIT_BREAKER_RESET_SECONDS,
        )

    def transcribe(self, audio_file_path: str) -> str:
        def _call():
            self._circuit.ensure_closed()
            try:
                with open(audio_file_path, "rb") as audio:
                    transcript = self._client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio,
                    )
            except Exception:
                self._circuit.record_failure()
                raise
            self._circuit.record_success()
            return transcript.text

        return sync_retry(
            name="whisper_transcribe",
            func=_call,
            attempts=settings.SPEECH_MAX_RETRIES,
            backoff_base=0.5,
        )
