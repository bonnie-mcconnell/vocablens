from vocablens.services.event_consumer_contract import (
    ConsumedEvent,
    IdempotentConsumer,
    InMemoryConsumerDedupeStore,
)


def test_duplicate_publish_processed_once():
    handled: list[str] = []

    consumer = IdempotentConsumer(InMemoryConsumerDedupeStore())

    event = ConsumedEvent(
        dedupe_key="session:abc123",
        version=1,
        payload={"xp": 25},
    )

    first = consumer.consume_once(event, lambda e: handled.append(str(e.dedupe_key)))
    second = consumer.consume_once(event, lambda e: handled.append(str(e.dedupe_key)))

    assert first is True
    assert second is False
    assert handled == ["session:abc123"]
