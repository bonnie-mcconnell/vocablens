from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class LLMTextResult:
    content: str
    usage: LLMUsage


@dataclass(frozen=True)
class LLMJsonResult:
    content: dict
    usage: LLMUsage


class LLMProvider(ABC):

    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass

    @abstractmethod
    def generate_json(self, prompt: str) -> dict:
        pass

    @abstractmethod
    def generate_with_usage(self, prompt: str) -> LLMTextResult:
        pass

    @abstractmethod
    def generate_json_with_usage(self, prompt: str) -> LLMJsonResult:
        pass
