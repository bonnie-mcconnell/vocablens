from typing import Annotated

from fastapi import APIRouter, Depends, Query

from vocablens.api.dependencies import get_current_user, get_scenario_service
from vocablens.domain.user import User
from vocablens.services.scenario_service import ScenarioService


def create_scenario_router() -> APIRouter:

    router = APIRouter(
        prefix="/scenario",
        tags=["Immersion"],
    )

    @router.post("/start")
    def start_scenario(
        scenario: Annotated[str, Query(min_length=1, max_length=200)],
        language: Annotated[str, Query(min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")],
        user: User = Depends(get_current_user),
        service: ScenarioService = Depends(get_scenario_service),
    ):

        result = service.start_scenario(
            scenario,
            language,
        )

        return {"scenario": result}

    return router
