from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


LifecycleStage = Literal["new_user", "activating", "engaged", "at_risk", "churned"]


@dataclass(frozen=True)
class UserExperienceState:
    lifecycle_stage: LifecycleStage
    retention_state: str
    drop_off_risk: float
    total_sessions: int
    momentum_score: float
    mastery_percent: float
    due_reviews: int
    subscription_tier: str
    paywall_visible: bool
    paywall_type: str | None
    paywall_allow_access: bool
