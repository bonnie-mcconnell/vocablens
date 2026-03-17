import asyncio

from vocablens.services.skill_tracking_service import SkillTrackingService


class SkillUpdateProcessor:
    """
    Updates skill tracking based on learning events.
    """

    SUPPORTED = {
        "conversation_turn",
        "mistake_detected",
        "skill_update",
    }

    def __init__(self, skill_service: SkillTrackingService):
        self._skills = skill_service

    def supports(self, event_type: str) -> bool:
        return event_type in self.SUPPORTED

    def handle(self, event_type: str, user_id: int, payload: dict) -> None:

        if event_type in {"conversation_turn", "mistake_detected"}:
            analysis = payload.get("mistakes", {})
            # fire-and-forget; run asynchronously if handler is invoked in async context
            result = self._skills.update_from_analysis(user_id, analysis)
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    asyncio.run(result)

        elif event_type == "skill_update":
            # direct skill update payload: {"grammar":0.6,"vocabulary":0.7,"fluency":0.8}
            profile = self._skills.skills[user_id]
            for key, value in payload.items():
                if key in profile:
                    profile[key] = max(0.0, min(1.0, float(value)))
            snapshot = self._skills._save_snapshot(user_id)  # reuse existing persistence hook
            if asyncio.iscoroutine(snapshot):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(snapshot)
                except RuntimeError:
                    asyncio.run(snapshot)
