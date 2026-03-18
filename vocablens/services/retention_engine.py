from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork

UserState = Literal["active", "at-risk", "churned"]


@dataclass(frozen=True)
class RetentionAction:
    kind: Literal["review_reminder", "quick_session", "resurface_weak_vocabulary", "streak_nudge"]
    reason: str
    target: str | None = None


@dataclass(frozen=True)
class RetentionAssessment:
    state: UserState
    drop_off_risk: float
    session_frequency: float
    current_streak: int
    longest_streak: int
    last_active_at: object | None
    is_high_engagement: bool
    suggested_actions: list[RetentionAction]


class RetentionEngine:
    """
    Tracks learner activity and classifies engagement risk.
    """

    def __init__(self, uow_factory: type[UnitOfWork] | None = None):
        self._uow_factory = uow_factory

    def needs_review(self, item):
        return bool(item.next_review_due and item.next_review_due <= utc_now())

    def review_load(self, items):
        return len([item for item in items if self.needs_review(item)])

    async def record_activity(self, user_id: int, occurred_at=None) -> None:
        if not self._uow_factory:
            return
        occurred_at = occurred_at or utc_now()
        async with self._uow_factory() as uow:
            profile = await uow.profiles.get_or_create(user_id)
            previous_last_active = getattr(profile, "last_active_at", None)
            session_frequency = self._session_frequency(profile, occurred_at, previous_last_active)
            current_streak, longest_streak = self._streaks(profile, occurred_at, previous_last_active)
            drop_off_risk = self._drop_off_risk(
                last_active_at=occurred_at,
                session_frequency=session_frequency,
                current_streak=current_streak,
                retention_rate=getattr(profile, "retention_rate", 0.8),
            )
            await uow.profiles.update(
                user_id=user_id,
                last_active_at=occurred_at,
                session_frequency=session_frequency,
                current_streak=current_streak,
                longest_streak=longest_streak,
                drop_off_risk=drop_off_risk,
            )
            await uow.commit()

    async def assess_user(self, user_id: int) -> RetentionAssessment:
        if not self._uow_factory:
            return RetentionAssessment(
                state="active",
                drop_off_risk=0.0,
                session_frequency=0.0,
                current_streak=0,
                longest_streak=0,
                last_active_at=None,
                is_high_engagement=False,
                suggested_actions=[],
            )

        async with self._uow_factory() as uow:
            profile = await uow.profiles.get_or_create(user_id)
            due_items = await uow.vocab.list_due(user_id)
            weak_items = await uow.vocab.list_all(user_id, limit=100, offset=0)
            await uow.commit()

        risk = self._drop_off_risk(
            last_active_at=profile.last_active_at,
            session_frequency=profile.session_frequency,
            current_streak=profile.current_streak,
            retention_rate=profile.retention_rate,
        )
        state = self._classify_state(risk, profile.last_active_at)
        high_engagement = self._is_high_engagement(profile, risk)
        actions = self._build_actions(profile, due_items, weak_items, state, risk)
        return RetentionAssessment(
            state=state,
            drop_off_risk=risk,
            session_frequency=profile.session_frequency,
            current_streak=profile.current_streak,
            longest_streak=profile.longest_streak,
            last_active_at=profile.last_active_at,
            is_high_engagement=high_engagement,
            suggested_actions=actions,
        )

    def _session_frequency(self, profile, occurred_at, previous_last_active) -> float:
        previous_frequency = float(getattr(profile, "session_frequency", 0.0) or 0.0)
        if not previous_last_active:
            return 1.0
        gap_days = max(0.0, (occurred_at - previous_last_active).total_seconds() / 86400)
        observed_frequency = 7.0 if gap_days < 1 else max(0.4, min(7.0, 7.0 / max(gap_days, 1.0)))
        return max(0.0, min(7.0, (previous_frequency * 0.7) + (observed_frequency * 0.3)))

    def _streaks(self, profile, occurred_at, previous_last_active) -> tuple[int, int]:
        current_streak = int(getattr(profile, "current_streak", 0) or 0)
        longest_streak = int(getattr(profile, "longest_streak", 0) or 0)
        if not previous_last_active:
            current_streak = 1
        else:
            day_gap = (occurred_at.date() - previous_last_active.date()).days
            if day_gap <= 0:
                current_streak = max(1, current_streak)
            elif day_gap == 1:
                current_streak += 1
            else:
                current_streak = 1
        longest_streak = max(longest_streak, current_streak)
        return current_streak, longest_streak

    def _drop_off_risk(
        self,
        *,
        last_active_at,
        session_frequency: float,
        current_streak: int,
        retention_rate: float,
    ) -> float:
        now = utc_now()
        inactive_days = 30.0 if not last_active_at else max(
            0.0,
            (now - last_active_at).total_seconds() / 86400,
        )
        inactivity_risk = min(1.0, inactive_days / 7.0)
        frequency_risk = max(0.0, 1.0 - min(session_frequency / 4.0, 1.0))
        streak_protection = min(current_streak / 14.0, 1.0) * 0.25
        retention_risk = max(0.0, 1.0 - retention_rate)
        score = (0.5 * inactivity_risk) + (0.25 * frequency_risk) + (0.25 * retention_risk) - streak_protection
        return max(0.0, min(1.0, score))

    def _classify_state(self, risk: float, last_active_at) -> UserState:
        if not last_active_at:
            return "at-risk"
        inactive_days = (utc_now() - last_active_at).days
        if inactive_days >= 14 or risk >= 0.75:
            return "churned"
        if inactive_days >= 4 or risk >= 0.45:
            return "at-risk"
        return "active"

    def _is_high_engagement(self, profile, risk: float) -> bool:
        return bool(
            getattr(profile, "session_frequency", 0.0) >= 4.0
            and getattr(profile, "current_streak", 0) >= 5
            and risk < 0.3
        )

    def _build_actions(self, profile, due_items, weak_items, state: UserState, risk: float) -> list[RetentionAction]:
        actions: list[RetentionAction] = []
        if due_items:
            actions.append(
                RetentionAction(
                    kind="review_reminder",
                    reason=f"{len(due_items)} review items are waiting",
                    target=getattr(due_items[0], "source_text", None),
                )
            )

        if state in {"at-risk", "churned"}:
            actions.append(
                RetentionAction(
                    kind="quick_session",
                    reason="Engagement is slipping; suggest a short, low-friction session",
                )
            )

        weak_vocab = [
            item for item in weak_items
            if getattr(item, "review_count", 0) > 0 and getattr(item, "ease_factor", 2.5) < 2.0
        ]
        if weak_vocab:
            actions.append(
                RetentionAction(
                    kind="resurface_weak_vocabulary",
                    reason="These words show weak retention",
                    target=getattr(weak_vocab[0], "source_text", None),
                )
            )

        if getattr(profile, "current_streak", 0) >= 1 and risk < 0.75:
            actions.append(
                RetentionAction(
                    kind="streak_nudge",
                    reason=f"Current streak is {profile.current_streak} day(s); keep it going",
                )
            )

        return actions[:4]
