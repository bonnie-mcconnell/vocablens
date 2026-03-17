from collections import defaultdict

from vocablens.infrastructure.postgres_skill_tracking_repository import PostgresSkillTrackingRepository


class SkillTrackingService:

    def __init__(self, uow_factory):

        self._uow_factory = uow_factory

        self.skills = defaultdict(
            lambda: {
                "grammar": 0.5,
                "vocabulary": 0.5,
                "fluency": 0.5,
            }
        )

    async def update_from_analysis(self, user_id: int, analysis: dict):

        profile = self.skills[user_id]

        if analysis.get("grammar_mistakes"):
            profile["grammar"] -= 0.02
        else:
            profile["grammar"] += 0.01

        if analysis.get("vocab_misuse"):
            profile["vocabulary"] -= 0.01
        else:
            profile["vocabulary"] += 0.01

        if analysis.get("repeated_errors"):
            profile["fluency"] -= 0.01
        else:
            profile["fluency"] += 0.005

        profile["grammar"] = min(max(profile["grammar"], 0), 1)
        profile["vocabulary"] = min(max(profile["vocabulary"], 0), 1)
        profile["fluency"] = min(max(profile["fluency"], 0), 1)

        await self._save_snapshot(user_id)

    def get_skill_profile(self, user_id: int):

        return self.skills[user_id]

    async def _save_snapshot(self, user_id):

        skill = self.skills[user_id]

        async with self._uow_factory() as uow:
            for name in ("grammar", "vocabulary", "fluency"):
                await uow.skill_tracking.record(user_id, name, skill[name])
            await uow.commit()
