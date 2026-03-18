from vocablens.infrastructure.jobs.celery_app import celery_app
from vocablens.infrastructure.db.session import AsyncSessionMaker
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.infrastructure.logging.logger import get_logger
import anyio

logger = get_logger("jobs.skills")


@celery_app.task(
    bind=True,
    name="jobs.skill_snapshot",
    soft_time_limit=15,
    time_limit=20,
    max_retries=2,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def skill_snapshot(self, user_id: int, profile: dict):
    async def _persist():
        factory = UnitOfWorkFactory(AsyncSessionMaker)
        service = SkillTrackingService(factory)
        service.skills[user_id] = profile
        await service._save_snapshot(user_id)

    anyio.run(_persist)
    logger.info("skill_snapshot_persisted", extra={"user_id": user_id})
