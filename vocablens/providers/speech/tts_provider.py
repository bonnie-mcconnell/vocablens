import openai


class TextToSpeechProvider:
    """
    Converts AI responses to speech.
    """

    def synthesize(self, text: str, voice="alloy"):

        response = openai.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
        )

        return response