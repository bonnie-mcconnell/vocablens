from fastapi import APIRouter, Depends

from vocablens.api.dependencies import get_current_user, get_onboarding_flow_service
from vocablens.api.schemas import APIResponse, OnboardingNextRequest, OnboardingStartRequest
from vocablens.domain.user import User
from vocablens.services.onboarding_flow_service import OnboardingFlowService


def create_onboarding_router() -> APIRouter:
    router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

    @router.post("/start", response_model=APIResponse)
    async def onboarding_start(
        _: OnboardingStartRequest,
        user: User = Depends(get_current_user),
        service: OnboardingFlowService = Depends(get_onboarding_flow_service),
    ):
        data = await service.start(user.id)
        return APIResponse(
            data=data,
            meta={"source": "onboarding.start", "current_step": data["current_step"]},
        )

    @router.post("/next", response_model=APIResponse)
    async def onboarding_next(
        request: OnboardingNextRequest,
        user: User = Depends(get_current_user),
        service: OnboardingFlowService = Depends(get_onboarding_flow_service),
    ):
        data = await service.next(user.id, request.model_dump(exclude_none=True))
        return APIResponse(
            data=data,
            meta={"source": "onboarding.next", "current_step": data["current_step"]},
        )

    return router
