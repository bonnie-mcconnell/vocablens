from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LifecycleStage = Literal["new_user", "activating", "engaged", "at_risk", "churned"]


@dataclass(frozen=True)
class LifecycleSnapshot:
    learning_state: object
    engagement_state: object
    retention: object


def classify_lifecycle_stage(*, snapshot: LifecycleSnapshot) -> tuple[LifecycleStage, list[str]]:
    reasons: list[str] = []
    retention = snapshot.retention
    learning_state = snapshot.learning_state
    sessions = int(getattr(snapshot.engagement_state, "total_sessions", 0) or 0)

    if retention.state == "churned":
        reasons.append("retention engine marked user as churned")
        return "churned", reasons
    if retention.state == "at-risk":
        reasons.append("retention engine marked user as at risk")
        return "at_risk", reasons
    if sessions <= 1:
        reasons.append("user has one or fewer sessions")
        return "new_user", reasons

    skills = dict(getattr(learning_state, "skills", {}) or {})
    grammar = float(skills.get("grammar", 0.0) or 0.0) * 100
    fluency = float(skills.get("fluency", 0.0) or 0.0) * 100
    mastery = float(getattr(learning_state, "mastery_percent", 0.0) or 0.0)

    if sessions < 5 or grammar < 70 or fluency < 60 or mastery < 40:
        reasons.append("user is building toward activation")
        return "activating", reasons

    if retention.is_high_engagement or (sessions >= 5 and mastery >= 40 and grammar >= 75 and fluency >= 65):
        reasons.append("user shows strong engagement and progress")
        return "engaged", reasons

    reasons.append("engagement is improving, but not yet stable enough for the engaged stage")
    return "activating", reasons
