from __future__ import annotations

from dataclasses import replace

from vocablens.domain.models import UserCoreState


def apply_session_reward(state: UserCoreState, *, xp_delta: int = 25, momentum_delta: float = 0.1) -> UserCoreState:
    """Pure O(1) core-state mutation for session completion."""
    new_xp = int(state.xp) + int(xp_delta)
    new_level = max(1, (new_xp // 250) + 1)
    return replace(
        state,
        xp=new_xp,
        level=new_level,
        current_streak=int(state.current_streak) + 1,
        longest_streak=max(int(state.longest_streak), int(state.current_streak) + 1),
        momentum_score=min(1.0, float(state.momentum_score) + float(momentum_delta)),
        total_sessions=int(state.total_sessions) + 1,
    )


def apply_xp_delta(state: UserCoreState, *, xp_delta: int) -> UserCoreState:
    """Pure O(1) core-state mutation for generic XP increments."""
    new_xp = int(state.xp) + int(xp_delta)
    new_level = max(1, (new_xp // 250) + 1)
    return replace(state, xp=new_xp, level=new_level)
