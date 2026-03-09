from abc import ABC, abstractmethod


class LLMProvider(ABC):

    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass

    @abstractmethod
    def generate_json(self, prompt: str) -> dict:
        pass