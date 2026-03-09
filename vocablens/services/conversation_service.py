from typing import List

from vocablens.providers.llm.base import LLMProvider
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository


class ConversationService:
    """
    AI language tutor that adapts to the learner's vocabulary
    and conversation history.
    """

    def __init__(
        self,
        llm: LLMProvider,
        vocab_repo: SQLiteVocabularyRepository,
    ):
        self._llm = llm
        self._repo = vocab_repo

    # --------------------------------------------
    # Vocabulary retrieval
    # --------------------------------------------

    def _get_known_words(self, user_id: int) -> List[str]:

        items = self._repo.list_all(user_id, limit=500, offset=0)

        return [i.source_text for i in items][:200]

    # --------------------------------------------
    # Conversation reply
    # --------------------------------------------

    def generate_reply(
        self,
        user_id: int,
        user_message: str,
        source_lang: str,
        target_lang: str,
    ) -> str:

        known_words = self._get_known_words(user_id)

        vocab_list = ", ".join(known_words)

        prompt = f"""
You are an AI language tutor helping a student practice {source_lang}.

Student message:
{user_message}

Known vocabulary:
{vocab_list}

Rules:
- Use mostly known vocabulary
- Introduce at most 1–2 new words
- Keep sentences short
- If the student makes a mistake, gently correct them
- Encourage the learner

Respond in {source_lang}.
"""

        return self._llm.generate(prompt)