import asyncio
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query

from vocablens.api.dependencies_core import get_uow_factory
from vocablens.api.dependencies_interaction_api import (
    get_current_user,
    get_hot_user_service,
    get_mutator,
)
from vocablens.api.schemas import APIResponse, ConsistencyMode, StateMutateRequest
from vocablens.core.runtime_metrics import runtime_metrics
from vocablens.domain.user import User
from vocablens.services.hot_user_service import HotUserService, MutationType
from vocablens.services.mutations import apply_xp_delta
from vocablens.services.mutator import Mutator


def _state_payload(state) -> dict:
    return {
        "user_id": int(state.user_id),
        "xp": int(state.xp),
        "level": int(state.level),
        "current_streak": int(state.current_streak),
        "longest_streak": int(state.longest_streak),
        "momentum_score": float(state.momentum_score),
        "total_sessions": int(state.total_sessions),
        "sessions_last_3_days": int(state.sessions_last_3_days),
        "version": int(state.version),
    }


def create_state_router() -> APIRouter:
    router = APIRouter(prefix="/state", tags=["State"])

    @router.post("/mutate-xp", response_model=APIResponse)
    async def mutate_xp(
        request: StateMutateRequest,
        user: User = Depends(get_current_user),
        mutator: Mutator = Depends(get_mutator),
        hot_service: HotUserService = Depends(get_hot_user_service),
        uow_factory=Depends(get_uow_factory),
    ):
        async with uow_factory() as uow:
            requested_mode = request.mode
            if requested_mode == "cold" and runtime_metrics().lock_wait_p95("mutator") > 150.0:
                requested_mode = "hot"
            await uow.execution_mode.set_mode(user_id=user.id, mode=requested_mode)
            mode = await uow.execution_mode.get_or_create(user.id)
            await uow.commit()

        if mode == "hot":
            queued = await hot_service.enqueue(
                user_id=user.id,
                payload={"mutation_type": MutationType.ADD_XP.value, "xp_delta": int(request.xp_delta)},
                idempotency_key=request.idempotency_key,
            )
            return APIResponse(
                data={
                    "command_id": str(queued["command_id"]),
                    "mode": str(queued["mode"]),
                    "command_seq": int(queued["command_seq"]),
                },
                meta={
                    "source": "state.mutate_xp",
                    "consistency_mode": ConsistencyMode.EVENTUAL.value,
                },
            )

        updated = await mutator.mutate(
            user_id=user.id,
            mutation_fn=lambda state: apply_xp_delta(state, xp_delta=int(request.xp_delta)),
            idempotency_key=request.idempotency_key,
            source="state.mutate_xp",
            reference_id=request.idempotency_key,
        )
        async with uow_factory() as uow:
            await uow.command_receipts.upsert(
                user_id=user.id,
                command_id=request.idempotency_key,
                command_seq=int(updated.version),
                mode="cold",
            )
            await uow.commit()
        return APIResponse(
            data={
                "command_id": request.idempotency_key,
                "mode": "cold",
                "command_seq": int(updated.version),
            },
            meta={"source": "state.mutate_xp", "consistency_mode": ConsistencyMode.STRONG.value},
        )

    @router.get("/core", response_model=APIResponse)
    async def read_core_state(
        after_command_id: str | None = Query(default=None),
        consistency_mode: ConsistencyMode = Query(default=ConsistencyMode.STRONG),
        max_wait_ms: int = Query(default=200, ge=0, le=2000),
        user: User = Depends(get_current_user),
        uow_factory=Depends(get_uow_factory),
    ):
        mode = "cold"
        consistent = True
        command_seq = None

        if after_command_id:
            consistency_mode = ConsistencyMode.SESSION

        if consistency_mode == ConsistencyMode.SESSION and after_command_id:
            async with uow_factory() as uow:
                receipt = await uow.command_receipts.get(user_id=user.id, command_id=after_command_id)
                mode = await uow.execution_mode.get_or_create(user.id)
                await uow.commit()
            mode = str(mode)
            if receipt is None:
                raise HTTPException(status_code=409, detail={"code": "not_ready", "reason": "unknown_command"})
            command_seq = int(receipt["command_seq"])
            if str(receipt["mode"]) == "hot":
                deadline = monotonic() + (float(max_wait_ms) / 1000.0)
                ready = False
                while monotonic() <= deadline:
                    async with uow_factory() as uow:
                        last_applied = await uow.mutation_queue.get_last_applied_seq(user.id)
                        await uow.commit()
                    if int(last_applied) >= int(command_seq):
                        ready = True
                        break
                    await asyncio.sleep(0.02)
                if not ready:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "not_ready",
                            "command_id": after_command_id,
                            "command_seq": int(command_seq),
                        },
                    )

        async with uow_factory() as uow:
            state = await uow.core_state.get_or_create(user.id)
            mode = await uow.execution_mode.get_or_create(user.id)
            await uow.commit()
        mode = str(mode)

        return APIResponse(
            data={"state": _state_payload(state)},
            meta={
                "source": "state.core",
                "mode": mode,
                "consistent": consistent,
                "after_command_id": after_command_id,
                "consistency_mode": consistency_mode.value,
                "command_seq": command_seq,
            },
        )

    return router
