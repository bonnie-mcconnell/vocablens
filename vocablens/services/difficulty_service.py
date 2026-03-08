class DifficultyService:

    def score(self, word: str) -> float:

        length = len(word)

        if length <= 4:
            return 0.2

        if length <= 7:
            return 0.5

        return 0.8