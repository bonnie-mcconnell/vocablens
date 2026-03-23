from fastapi import APIRouter, Depends, HTTPException

from vocablens.api.dependencies import get_current_user, get_session_engine
from vocablens.api.schemas import APIResponse, SessionEvaluateRequest, SessionStartRequest
from vocablens.domain.errors import ConflictError, NotFoundError
from vocablens.domain.user import User
from vocablens.services.session_engine import SessionEngine


def create_session_router() -> APIRouter:
    router = APIRouter(prefix="/session", tags=["Session"])

    @router.post("/start", response_model=APIResponse)
    async def start_session(
        _: SessionStartRequest,
        user: User = Depends(get_current_user),
        service: SessionEngine = Depends(get_session_engine),
    ):
        data = await service.start_session(user.id)
        return APIResponse(
            data=data,
            meta={
                "source": "session.start",
                "mode": data["mode"],
                "weak_area": data["weak_area"],
                "goal_label": data.get("goal_label"),
            },
        )

    @router.post("/evaluate", response_model=APIResponse)
    async def evaluate_session(
        request: SessionEvaluateRequest,
        user: User = Depends(get_current_user),
        service: SessionEngine = Depends(get_session_engine),
    ):
        try:
            feedback = await service.evaluate_session(user.id, request.session_id, request.learner_response)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

        data = service.feedback_to_payload(feedback)
        return APIResponse(
            data=data,
            meta={
                "source": "session.evaluate",
                "weak_area": data["targeted_weak_area"],
                "structured": data["structured"],
            },
        )

    return router
