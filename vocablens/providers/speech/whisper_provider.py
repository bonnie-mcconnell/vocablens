import openai


class WhisperProvider:
    """
    Speech → text transcription using Whisper.
    """

    def transcribe(self, audio_file_path: str) -> str:

        with open(audio_file_path, "rb") as audio:

            transcript = openai.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
            )

        return transcript.text