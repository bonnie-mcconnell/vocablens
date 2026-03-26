from __future__ import annotations

from typing import Any

from sqlalchemy import select

from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.infrastructure.db.models import (
    DailyMissionORM,
    DecisionTraceORM,
    LearningSessionAttemptORM,
    LearningSessionORM,
    RewardChestORM,
)
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.daily_loop_health_signal_service import DailyLoopHealthSignalService
from vocablens.services.lifecycle_health_signal_service import LifecycleHealthSignalService
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.lifecycle_state_service import LifecycleStateService
from vocablens.services.monetization_health_signal_service import MonetizationHealthSignalService
from vocablens.services.monetization_state_service import MonetizationStateService
from vocablens.services.notification_state_service import NotificationStateService
from vocablens.services.session_health_signal_service import SessionHealthSignalService


class OperatorRemediationService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        *,
        session_health_signal_service: SessionHealthSignalService,
        lifecycle_service: LifecycleService,
        lifecycle_state_service: LifecycleStateService,
        lifecycle_health_signal_service: LifecycleHealthSignalService,
        notification_state_service: NotificationStateService,
        monetization_state_service: MonetizationStateService,
        monetization_health_signal_service: MonetizationHealthSignalService,
        daily_loop_health_signal_service: DailyLoopHealthSignalService,
    ):
        self._uow_factory = uow_factory
        self._session_health = session_health_signal_service
        self._lifecycle = lifecycle_service
        self._lifecycle_states = lifecycle_state_service
        self._lifecycle_health = lifecycle_health_signal_service
        self._notification_states = notification_state_service
        self._monetization_states = monetization_state_service
        self._monetization_health = monetization_health_signal_service
        self._daily_loop_health = daily_loop_health_signal_service

    async def remediate_session_alert(
        self,
        *,
        alert_code: str,
        artifact_type: str | None,
        session_id: str | None,
        submission_id: str | None,
        trace_id: int | None,
    ) -> dict[str, Any]:
        if alert_code != "session_reference_drift_detected":
            raise ValidationError("Unsupported session health alert remediation")
        if artifact_type == "session_attempt":
            result = await self._repair_session_attempt_reference(
                session_id=session_id,
                submission_id=submission_id,
            )
        elif artifact_type == "session_evaluation_trace":
            result = await self._repair_session_trace_reference(trace_id=trace_id)
        elif artifact_type is None:
            result = {
                "action": "re_evaluate_session_health",
                "status": "re_evaluated",
                "repaired": False,
                "target": {"scope_key": "global"},
                "details": {},
            }
        else:
            raise ValidationError("Unsupported session remediation artifact type")
        await self._session_health.evaluate_scope("global")
        result["domain"] = "session"
        result["alert_code"] = alert_code
        result["reevaluated_scopes"] = ["global"]
        return result

    async def remediate_lifecycle_alert(
        self,
        *,
        alert_code: str,
        artifact_type: str | None,
        user_id: int | None,
    ) -> dict[str, Any]:
        if alert_code != "lifecycle_state_drift_detected":
            raise ValidationError("Unsupported lifecycle health alert remediation")
        if not user_id:
            raise ValidationError("Lifecycle remediation requires user_id")

        async with self._uow_factory() as uow:
            state = await uow.lifecycle_states.get(user_id)
            await uow.commit()
        if state is None:
            raise NotFoundError("Lifecycle state not found")
        current_stage = str(getattr(state, "current_stage", "") or "")
        if not current_stage:
            raise ValidationError("Lifecycle state is missing current_stage")

        if artifact_type in {None, "notification_state"}:
            await self._notification_states.apply_lifecycle_policy(
                user_id=user_id,
                lifecycle_stage=current_stage,
                source="operator_remediation_service.lifecycle_notification_sync",
                reference_id=f"health_remediation:lifecycle:{user_id}",
            )
            action = "sync_notification_lifecycle_stage"
        elif artifact_type == "lifecycle_transition":
            await self._lifecycle_states.repair_current_stage_transition(
                user_id=user_id,
                source="operator_remediation_service.lifecycle_transition_repair",
                reference_id=f"health_remediation:lifecycle:{user_id}",
            )
            action = "append_missing_lifecycle_transition"
        else:
            raise ValidationError("Unsupported lifecycle remediation artifact type")

        await self._lifecycle.evaluate(user_id)
        await self._lifecycle_health.evaluate_scope("global")
        await self._lifecycle_health.evaluate_scope(current_stage)
        return {
            "domain": "lifecycle",
            "alert_code": alert_code,
            "action": action,
            "status": "repaired",
            "repaired": True,
            "reevaluated_scopes": ["global", current_stage],
            "target": {
                "user_id": user_id,
                "artifact_type": artifact_type or "notification_state",
            },
            "details": {
                "current_stage": current_stage,
            },
        }

    async def remediate_monetization_alert(
        self,
        *,
        alert_code: str,
        user_id: int | None,
    ) -> dict[str, Any]:
        if alert_code != "monetization_lifecycle_stage_mismatch_detected":
            raise ValidationError("Unsupported monetization health alert remediation")
        if not user_id:
            raise ValidationError("Monetization remediation requires user_id")

        async with self._uow_factory() as uow:
            lifecycle_state = await uow.lifecycle_states.get(user_id)
            monetization_state = await uow.monetization_states.get_or_create(user_id)
            await uow.commit()
        if lifecycle_state is None:
            raise NotFoundError("Lifecycle state not found")
        lifecycle_stage = str(getattr(lifecycle_state, "current_stage", "") or "")
        geography = str(getattr(monetization_state, "current_geography", "") or "") or None
        await self._monetization_states.sync_lifecycle_stage(
            user_id=user_id,
            lifecycle_stage=lifecycle_stage,
        )
        await self._monetization_health.evaluate_scope("global")
        if geography:
            await self._monetization_health.evaluate_scope(geography)
        reevaluated_scopes = ["global"]
        if geography:
            reevaluated_scopes.append(geography)
        return {
            "domain": "monetization",
            "alert_code": alert_code,
            "action": "sync_monetization_lifecycle_stage",
            "status": "repaired",
            "repaired": True,
            "reevaluated_scopes": reevaluated_scopes,
            "target": {"user_id": user_id},
            "details": {
                "lifecycle_stage": lifecycle_stage,
                "geography": geography,
            },
        }

    async def remediate_daily_loop_alert(
        self,
        *,
        alert_code: str,
        reward_chest_id: int | None,
        mission_id: int | None,
    ) -> dict[str, Any]:
        if alert_code != "reward_mission_reference_mismatch_detected":
            raise ValidationError("Unsupported daily loop health alert remediation")
        result = await self._repair_reward_chest_owner(
            reward_chest_id=reward_chest_id,
            mission_id=mission_id,
        )
        await self._daily_loop_health.evaluate_scope("global")
        result["domain"] = "daily_loop"
        result["alert_code"] = alert_code
        result["reevaluated_scopes"] = ["global"]
        return result

    async def _repair_session_attempt_reference(
        self,
        *,
        session_id: str | None,
        submission_id: str | None,
    ) -> dict[str, Any]:
        if not session_id or not submission_id:
            raise ValidationError("Session attempt remediation requires session_id and submission_id")
        async with self._uow_factory() as uow:
            session = (
                await uow.session.execute(
                    select(LearningSessionORM).where(LearningSessionORM.session_id == session_id)
                )
            ).scalars().first()
            attempt = (
                await uow.session.execute(
                    select(LearningSessionAttemptORM).where(
                        LearningSessionAttemptORM.session_id == session_id,
                        LearningSessionAttemptORM.submission_id == submission_id,
                    )
                )
            ).scalars().first()
            if attempt is None:
                await uow.commit()
                raise NotFoundError("Session attempt not found")
            if session is None:
                await uow.commit()
                return {
                    "action": "repair_session_attempt_reference",
                    "status": "skipped",
                    "repaired": False,
                    "target": {
                        "artifact_type": "session_attempt",
                        "session_id": session_id,
                        "submission_id": submission_id,
                    },
                    "details": {"reason": "canonical_session_missing"},
                }
            expected_user_id = int(getattr(session, "user_id", 0) or 0)
            previous_user_id = int(getattr(attempt, "user_id", 0) or 0)
            if previous_user_id != expected_user_id:
                attempt.user_id = expected_user_id
                status = "repaired"
                repaired = True
            else:
                status = "skipped"
                repaired = False
            await uow.commit()
        return {
            "action": "repair_session_attempt_reference",
            "status": status,
            "repaired": repaired,
            "target": {
                "artifact_type": "session_attempt",
                "session_id": session_id,
                "submission_id": submission_id,
            },
            "details": {
                "previous_user_id": previous_user_id,
                "canonical_user_id": expected_user_id,
            },
        }

    async def _repair_session_trace_reference(self, *, trace_id: int | None) -> dict[str, Any]:
        if not trace_id:
            raise ValidationError("Session trace remediation requires trace_id")
        async with self._uow_factory() as uow:
            trace = (
                await uow.session.execute(
                    select(DecisionTraceORM).where(DecisionTraceORM.id == trace_id)
                )
            ).scalars().first()
            if trace is None:
                await uow.commit()
                raise NotFoundError("Decision trace not found")
            session = (
                await uow.session.execute(
                    select(LearningSessionORM).where(LearningSessionORM.session_id == trace.reference_id)
                )
            ).scalars().first()
            if session is None:
                await uow.commit()
                return {
                    "action": "repair_session_trace_reference",
                    "status": "skipped",
                    "repaired": False,
                    "target": {
                        "artifact_type": "session_evaluation_trace",
                        "trace_id": trace_id,
                    },
                    "details": {"reason": "canonical_session_missing"},
                }
            expected_user_id = int(getattr(session, "user_id", 0) or 0)
            previous_user_id = int(getattr(trace, "user_id", 0) or 0)
            if previous_user_id != expected_user_id:
                trace.user_id = expected_user_id
                status = "repaired"
                repaired = True
            else:
                status = "skipped"
                repaired = False
            await uow.commit()
        return {
            "action": "repair_session_trace_reference",
            "status": status,
            "repaired": repaired,
            "target": {
                "artifact_type": "session_evaluation_trace",
                "trace_id": trace_id,
                "reference_id": str(getattr(trace, "reference_id", "") or ""),
            },
            "details": {
                "previous_user_id": previous_user_id,
                "canonical_user_id": expected_user_id,
            },
        }

    async def _repair_reward_chest_owner(
        self,
        *,
        reward_chest_id: int | None,
        mission_id: int | None,
    ) -> dict[str, Any]:
        if not reward_chest_id and not mission_id:
            raise ValidationError("Daily loop remediation requires reward_chest_id or mission_id")
        async with self._uow_factory() as uow:
            chest = None
            if reward_chest_id:
                chest = (
                    await uow.session.execute(
                        select(RewardChestORM).where(RewardChestORM.id == reward_chest_id)
                    )
                ).scalars().first()
            elif mission_id:
                chest = (
                    await uow.session.execute(
                        select(RewardChestORM).where(RewardChestORM.mission_id == mission_id)
                    )
                ).scalars().first()
            if chest is None:
                await uow.commit()
                raise NotFoundError("Reward chest not found")
            mission = (
                await uow.session.execute(
                    select(DailyMissionORM).where(DailyMissionORM.id == chest.mission_id)
                )
            ).scalars().first()
            if mission is None:
                await uow.commit()
                return {
                    "action": "repair_reward_chest_owner",
                    "status": "skipped",
                    "repaired": False,
                    "target": {
                        "reward_chest_id": int(getattr(chest, "id", 0) or 0),
                        "mission_id": int(getattr(chest, "mission_id", 0) or 0),
                    },
                    "details": {"reason": "canonical_mission_missing"},
                }
            canonical_user_id = int(getattr(mission, "user_id", 0) or 0)
            previous_user_id = int(getattr(chest, "user_id", 0) or 0)
            if previous_user_id != canonical_user_id:
                chest.user_id = canonical_user_id
                status = "repaired"
                repaired = True
            else:
                status = "skipped"
                repaired = False
            await uow.commit()
        return {
            "action": "repair_reward_chest_owner",
            "status": status,
            "repaired": repaired,
            "target": {
                "reward_chest_id": int(getattr(chest, "id", 0) or 0),
                "mission_id": int(getattr(chest, "mission_id", 0) or 0),
            },
            "details": {
                "previous_user_id": previous_user_id,
                "canonical_user_id": canonical_user_id,
            },
        }
