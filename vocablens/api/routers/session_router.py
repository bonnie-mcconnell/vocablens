from fastapi import APIRouter, Depends

from vocablens.api.dependencies import get_current_user, get_session_engine
from vocablens.api.schemas import APIResponse, SessionEvaluateRequest, SessionStartRequest
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
        session = await service.build_session(user.id)
        data = service.to_payload(session)
        return APIResponse(
            data=data,
            meta={
                "source": "session.start",
                "mode": data["mode"],
                "weak_area": data["weak_area"],
            },
        )

    @router.post("/evaluate", response_model=APIResponse)
    async def evaluate_session(
        request: SessionEvaluateRequest,
        user: User = Depends(get_current_user),
        service: SessionEngine = Depends(get_session_engine),
    ):
        session = service.from_payload(request.session)
        feedback = await service.evaluate_response(user.id, session, request.learner_response)
        data = {
            "structured": feedback.structured,
            "targeted_weak_area": feedback.targeted_weak_area,
            "is_correct": feedback.is_correct,
            "improvement_score": feedback.improvement_score,
            "corrected_response": feedback.corrected_response,
            "highlighted_mistakes": feedback.highlighted_mistakes,
            "reinforcement_prompt": feedback.reinforcement_prompt,
            "variation_prompt": feedback.variation_prompt,
            "win_message": feedback.win_message,
            "wow_score": feedback.wow_score,
            "xp_preview": feedback.xp_preview,
            "badges_preview": feedback.badges_preview,
        }
        return APIResponse(
            data=data,
            meta={
                "source": "session.evaluate",
                "weak_area": data["targeted_weak_area"],
                "structured": data["structured"],
            },
        )

    return router
