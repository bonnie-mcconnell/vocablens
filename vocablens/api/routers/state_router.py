from fastapi import APIRouter, Depends, Query

from vocablens.api.dependencies_core import get_uow_factory
from vocablens.api.dependencies_interaction_api import (
    get_current_user,
    get_hot_user_service,
    get_mutator,
)
from vocablens.api.schemas import APIResponse, StateMutateRequest
from vocablens.domain.user import User
from vocablens.services.hot_user_service import HotUserService
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
            await uow.execution_mode.set_mode(user_id=user.id, mode=request.mode)
            mode = await uow.execution_mode.get_or_create(user.id)
            await uow.commit()

        if mode == "hot":
            queued = await hot_service.enqueue(
                user_id=user.id,
                payload={"xp_delta": int(request.xp_delta)},
                idempotency_key=request.idempotency_key,
            )
            return APIResponse(
                data={
                    "command_id": str(queued["command_id"]),
                    "mode": str(queued["mode"]),
                },
                meta={
                    "source": "state.mutate_xp",
                    "queue_seq": int(queued.get("seq", 0)),
                },
            )

        await mutator.mutate(
            user_id=user.id,
            mutation_fn=lambda state: apply_xp_delta(state, xp_delta=int(request.xp_delta)),
            idempotency_key=request.idempotency_key,
            source="state.mutate_xp",
            reference_id=request.idempotency_key,
        )
        return APIResponse(
            data={
                "command_id": request.idempotency_key,
                "mode": "cold",
            },
            meta={"source": "state.mutate_xp"},
        )

    @router.get("/core", response_model=APIResponse)
    async def read_core_state(
        after_command_id: str | None = Query(default=None),
        user: User = Depends(get_current_user),
        uow_factory=Depends(get_uow_factory),
        hot_service: HotUserService = Depends(get_hot_user_service),
    ):
        async with uow_factory() as uow:
            state = await uow.core_state.get_or_create(user.id)
            await uow.commit()

        mode = "cold"
        consistent = after_command_id is None
        if after_command_id:
            cached_state = hot_service.get_cached_command_state(user_id=user.id, command_id=after_command_id)
            if cached_state is not None:
                state = cached_state
                mode = "hot"
                consistent = True

        return APIResponse(
            data={"state": _state_payload(state)},
            meta={
                "source": "state.core",
                "mode": mode,
                "consistent": consistent,
                "after_command_id": after_command_id,
            },
        )

    return router
