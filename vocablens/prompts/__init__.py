import io
from pathlib import Path

BASE_PATH = Path(__file__).parent


def load_prompt(name: str) -> str:
    path = BASE_PATH / f"{name}.txt"
    with path.open("r", encoding="utf-8") as f:
        return f.read()
