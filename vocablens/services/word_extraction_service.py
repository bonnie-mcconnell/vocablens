import re

from vocablens.core.frequency_list import COMMON_WORDS


STOPWORDS = {
    "the","a","an","and","or","but",
    "is","are","was","were","be","been",
    "to","of","in","on","for","with"
}


class WordExtractionService:

    def extract_words(self, text: str) -> list[str]:

        text = text.lower()

        text = re.sub(r"[^\w\s]", "", text)

        words = text.split()

        cleaned = []

        for word in words:

            if len(word) < 2:
                continue

            if word in STOPWORDS:
                continue

            if word in COMMON_WORDS:
                continue

            cleaned.append(word)

        seen = set()
        unique = []

        for w in cleaned:
            if w not in seen:
                seen.add(w)
                unique.append(w)

        return unique