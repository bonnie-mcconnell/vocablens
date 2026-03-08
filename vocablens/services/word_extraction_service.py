import re

STOPWORDS = {
    "the","a","an","and","or","but",
    "is","are","was","were","be","been",
    "to","of","in","on","for","with"
}


class WordExtractionService:

    def extract_words(self, text: str) -> list[str]:

        text = text.lower()

        # remove punctuation
        text = re.sub(r"[^\w\s]", "", text)

        words = text.split()

        cleaned = []

        for word in words:

            if len(word) < 2:
                continue

            if word in STOPWORDS:
                continue

            cleaned.append(word)

        # remove duplicates while preserving order
        seen = set()
        unique = []

        for w in cleaned:
            if w not in seen:
                seen.add(w)
                unique.append(w)

        return unique