from vocablens.infrastructure.jobs.celery_app import celery_app
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.infrastructure.db.session import AsyncSessionMaker
from vocablens.providers.llm.openai_provider import OpenAIProvider
from vocablens.services.example_sentence_service import ExampleSentenceService
from vocablens.services.grammar_service import GrammarExplanationService
from vocablens.services.semantic_cluster_service import SemanticClusterService
from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.token_tracker import start_request, get_tokens
import anyio


logger = get_logger("jobs.enrichment")


@celery_app.task(
    bind=True,
    name="jobs.enrich_vocabulary",
    soft_time_limit=30,
    time_limit=45,
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def enrich_vocabulary_item(
    self,
    user_id: int | None,
    item_id: int,
    source_text: str,
    source_lang: str,
    target_lang: str,
):

    start_request()

    llm = OpenAIProvider()

    sentence_service = ExampleSentenceService(llm)
    grammar_service = GrammarExplanationService(llm)
    cluster_service = SemanticClusterService(llm)

    example = sentence_service.generate_example(
        source_text,
        source_lang,
        target_lang,
    )

    grammar = grammar_service.explain(
        example.get("source_sentence", ""),
        source_lang,
        target_lang,
    )

    cluster = cluster_service.cluster_word(
        source_text,
        source_lang,
    )

    async def _persist():
        factory = UnitOfWorkFactory(AsyncSessionMaker)
        async with factory() as uow:
            await uow.vocab.update_enrichment(
                item_id,
                example.get("source_sentence"),
                example.get("translated_sentence"),
                grammar,
                cluster,
            )
            if user_id is not None:
                await uow.usage_logs.log(
                    user_id=user_id,
                    endpoint="job:enrich_vocabulary",
                    tokens=get_tokens(),
                    success=True,
                )
            await uow.commit()

    anyio.run(_persist)

    logger.info(
        "enrichment_completed",
        extra={
            "item_id": item_id,
            "source_text": source_text,
            "tokens_used": get_tokens(),
        },
    )
