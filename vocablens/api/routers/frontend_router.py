from fastapi import APIRouter, Depends

from vocablens.api.dependencies_interaction_api import get_current_user, get_frontend_service
from vocablens.api.schemas import APIResponse
from vocablens.domain.user import User
from vocablens.services.frontend_service import FrontendService


def create_frontend_router() -> APIRouter:
    router = APIRouter(prefix="/frontend", tags=["Frontend"])

    @router.get("/dashboard", response_model=APIResponse)
    async def dashboard(
        user: User = Depends(get_current_user),
        service: FrontendService = Depends(get_frontend_service),
    ):
        data = await service.dashboard(user.id)
        meta = service.meta(
            source="frontend.dashboard",
            difficulty=data["next_action"]["difficulty"],
            next_action=data["next_action"]["action"],
        )
        return APIResponse(data=data, meta=meta)

    @router.get("/recommendations", response_model=APIResponse)
    async def recommendations(
        user: User = Depends(get_current_user),
        service: FrontendService = Depends(get_frontend_service),
    ):
        data = await service.recommendations(user.id)
        meta = service.meta(
            source="frontend.recommendations",
            difficulty=data["next_action"]["difficulty"],
            next_action=data["next_action"]["action"],
        )
        return APIResponse(data=data, meta=meta)

    @router.get("/weak-areas", response_model=APIResponse)
    async def weak_areas(
        user: User = Depends(get_current_user),
        service: FrontendService = Depends(get_frontend_service),
    ):
        data = await service.weak_areas(user.id)
        return APIResponse(
            data=data,
            meta=service.meta(source="frontend.weak_areas"),
        )

    @router.get("/paywall", response_model=APIResponse)
    async def paywall(
        user: User = Depends(get_current_user),
        service: FrontendService = Depends(get_frontend_service),
    ):
        data = await service.paywall(user.id)
        return APIResponse(
            data=data,
            meta=service.meta(source="frontend.paywall"),
        )

    return router
