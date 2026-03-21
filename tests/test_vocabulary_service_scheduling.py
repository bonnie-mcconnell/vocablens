from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.domain.models import VocabularyItem
from vocablens.services.vocabulary_service import VocabularyService


class FakeTranslator:
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        return f"{text}-{target_lang}"

    async def translate_batch(self, words, source_lang: str, target_lang: str):
        return [f"{word}-{target_lang}" for word in words]


class FakeEvents:
    def __init__(self):
        self.calls = []

    async def record(self, event_type: str, user_id: int, payload: dict):
        self.calls.append((event_type, user_id, payload))


class FakeLearningEngine:
    def __init__(self):
        self.calls = []

    async def update_knowledge(self, user_id: int, session_result):
        self.calls.append((user_id, session_result))
        return SimpleNamespace(reviewed_count=1, learned_count=0, weak_areas=[], updated_item_ids=[1])


class FakeVocabRepo:
    def __init__(self):
        self.items = {
            1: VocabularyItem(
                id=1,
                source_text="hola",
                translated_text="hello",
                source_lang="es",
                target_lang="en",
                created_at=utc_now(),
                interval=1,
                repetitions=0,
                ease_factor=2.5,
            )
        }

    async def add(self, user_id: int, item: VocabularyItem):
        item.id = 2
        return item

    async def get(self, user_id: int, item_id: int):
        return self.items.get(item_id)

    async def update(self, item: VocabularyItem):
        self.items[item.id] = item
        return item

    async def exists(self, user_id: int, source_text: str, source_lang: str, target_lang: str):
        return False

    async def list_due(self, user_id: int):
        return []

    async def list_all(self, user_id: int, limit: int, offset: int):
        return list(self.items.values())


class FakeProfilesRepo:
    async def get_or_create(self, user_id: int):
        return SimpleNamespace(retention_rate=0.85, difficulty_preference="hard")


class FakeMistakeRepo:
    async def top_patterns(self, user_id: int, limit: int = 20):
        return [SimpleNamespace(pattern="hola article issue", count=3)]


class FakeUOW:
    def __init__(self):
        self.vocab = FakeVocabRepo()
        self.profiles = FakeProfilesRepo()
        self.mistake_patterns = FakeMistakeRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_vocabulary_service_emits_review_event_and_sets_next_review_due():
    events = FakeEvents()
    learning_engine = FakeLearningEngine()
    uow = FakeUOW()
    service = VocabularyService(
        FakeTranslator(),
        lambda: uow,
        extractor=SimpleNamespace(),
        events=events,
        learning_engine=learning_engine,
    )

    updated = run_async(service.review_item(1, 1, "good"))

    assert updated.next_review_due is not None
    assert updated.interval >= 1
    assert events.calls == [
        (
            "word_reviewed",
            1,
            {
                "item_id": 1,
                "quality": 4,
                "response_accuracy": 0.8,
            },
        )
    ]
    assert len(learning_engine.calls) == 1
    user_id, session_result = learning_engine.calls[0]
    assert user_id == 1
    assert session_result.reviewed_items[0].item_id == 1
    assert session_result.reviewed_items[0].quality == 4
