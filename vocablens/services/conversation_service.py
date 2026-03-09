from typing import List

from vocablens.domain.models import VocabularyItem
from vocablens.providers.llm.base import LLMProvider
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository


class ConversationService:
    """
    AI tutor that chats with the learner using their known vocabulary.
    """

    def __init__(
        self,
        llm: LLMProvider,
        vocab_repo: SQLiteVocabularyRepository,
    ):
        self._llm = llm
        self._repo = vocab_repo

    def _get_known_words(self, user_id: int) -> List[str]:

        items = self._repo.list_all(user_id, limit=1000, offset=0)

        words = [i.source_text for i in items]

        return words[:200]

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
You are a language tutor.

Speak ONLY using words the learner already studied.

Known vocabulary:
{vocab_list}

User message:
{user_message}

Language:
{source_lang}

Respond naturally but keep sentences simple.
"""

        return self._llm.generate(prompt)