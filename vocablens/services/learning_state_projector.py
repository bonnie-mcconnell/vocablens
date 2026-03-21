from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


XP_PER_LEVEL = 250
PROGRESS_MILESTONES: tuple[int, ...] = (2, 3, 5, 10)


@dataclass(frozen=True)
class LearningProjection:
    skills: dict[str, float]
    weak_areas: list[str]
    mastery_percent: float
    accuracy_rate: float
    response_speed_seconds: float
    current_streak: int
    longest_streak: int
    momentum_score: float
    total_sessions: int
    sessions_last_3_days: int
    xp: int
    level: int
    milestones: list[int]


class LearningStateProjector:
    def project(
        self,
        *,
        learning_state,
        engagement_state,
        progress_state,
        profile,
        session_result,
        total_vocab,
        reviewed_count: int,
        learned_count: int,
        now,
    ) -> LearningProjection:
        skills = dict(getattr(learning_state, "skills", {}) or {})
        for skill, score in session_result.skill_scores.items():
            skills[skill] = max(0.0, min(1.0, float(score)))

        mastery_percent = self.mastery_percent(total_vocab)
        weak_areas = self.canonical_weak_areas(
            session_result=session_result,
            skills=skills,
            mastery_percent=mastery_percent,
        )
        accuracy_rate = self.canonical_accuracy_rate(
            existing=float(getattr(learning_state, "accuracy_rate", 0.0) or 0.0),
            session_result=session_result,
        )
        response_speed_seconds = self.canonical_response_speed(
            existing=float(getattr(learning_state, "response_speed_seconds", 0.0) or 0.0),
            session_result=session_result,
        )

        total_sessions = int(getattr(engagement_state, "total_sessions", 0) or 0) + 1
        sessions_last_3_days = self.sessions_last_3_days(engagement_state, now)
        current_streak, longest_streak = self.streaks_from_profile_and_state(profile, engagement_state, now)
        momentum_score = self.canonical_momentum_score(
            sessions_last_3_days=sessions_last_3_days,
            reviewed_count=reviewed_count,
            learned_count=learned_count,
        )

        xp = int(getattr(progress_state, "xp", 0) or 0) + self.xp_gain(
            reviewed_count=reviewed_count,
            learned_count=learned_count,
            skill_scores=session_result.skill_scores,
        )
        level = max(1, (xp // XP_PER_LEVEL) + 1)
        milestones = [milestone for milestone in PROGRESS_MILESTONES if level >= milestone]

        return LearningProjection(
            skills=skills,
            weak_areas=weak_areas,
            mastery_percent=mastery_percent,
            accuracy_rate=accuracy_rate,
            response_speed_seconds=response_speed_seconds,
            current_streak=current_streak,
            longest_streak=longest_streak,
            momentum_score=momentum_score,
            total_sessions=total_sessions,
            sessions_last_3_days=sessions_last_3_days,
            xp=xp,
            level=level,
            milestones=milestones,
        )

    def canonical_weak_areas(self, *, session_result, skills: dict[str, float], mastery_percent: float) -> list[str]:
        weak_areas: list[str] = []
        for area in session_result.weak_areas:
            normalized = str(area).strip().lower()
            if normalized and normalized not in weak_areas:
                weak_areas.append(normalized)
        for mistake in session_result.mistakes:
            category = str(mistake.get("category") or "").strip().lower()
            if category and category not in weak_areas:
                weak_areas.append(category)
        for skill, score in skills.items():
            if float(score) < 0.6 and skill not in weak_areas:
                weak_areas.append(skill)
        if mastery_percent < 40.0 and "vocabulary" not in weak_areas:
            weak_areas.append("vocabulary")
        return weak_areas[:5]

    def mastery_percent(self, total_vocab) -> float:
        total = len(total_vocab or [])
        if total <= 0:
            return 0.0
        mastered = sum(
            1 for item in total_vocab
            if float(getattr(item, "success_rate", 0.0) or 0.0) >= 0.85
            and int(getattr(item, "review_count", 0) or 0) >= 3
            and float(getattr(item, "decay_score", 1.0) or 1.0) <= 0.35
        )
        return round((mastered / total) * 100, 2)

    def sessions_last_3_days(self, engagement_state, now) -> int:
        last_session_at = getattr(engagement_state, "last_session_at", None)
        previous = int(getattr(engagement_state, "sessions_last_3_days", 0) or 0)
        if last_session_at and (now - last_session_at) <= timedelta(days=3):
            return previous + 1
        return 1

    def streaks_from_profile_and_state(self, profile, engagement_state, now) -> tuple[int, int]:
        profile_streak = int(getattr(profile, "current_streak", 0) or 0)
        profile_longest = int(getattr(profile, "longest_streak", 0) or 0)
        existing_streak = int(getattr(engagement_state, "current_streak", 0) or 0)
        existing_longest = int(getattr(engagement_state, "longest_streak", 0) or 0)
        last_session_at = getattr(engagement_state, "last_session_at", None)

        derived_streak = max(profile_streak, existing_streak)
        if last_session_at:
            days_since = (now.date() - last_session_at.date()).days
            if days_since == 1:
                derived_streak = max(derived_streak, existing_streak + 1)
            elif days_since > 1:
                derived_streak = max(profile_streak, 1)
        else:
            derived_streak = max(derived_streak, 1)
        longest = max(profile_longest, existing_longest, derived_streak)
        return derived_streak, longest

    def canonical_momentum_score(self, *, sessions_last_3_days: int, reviewed_count: int, learned_count: int) -> float:
        points = min(3.0, float(sessions_last_3_days))
        points += min(2.0, reviewed_count * 0.5)
        points += min(1.0, learned_count * 0.5)
        return round(min(1.0, points / 6.0), 3)

    def xp_gain(self, *, reviewed_count: int, learned_count: int, skill_scores: dict[str, float]) -> int:
        gain = (reviewed_count * 20) + (learned_count * 15)
        gain += min(20, len(skill_scores) * 5)
        return gain

    def canonical_accuracy_rate(self, *, existing: float, session_result) -> float:
        scores = [
            max(0.0, min(1.0, review.response_accuracy if review.response_accuracy is not None else review.quality / 5.0))
            for review in session_result.reviewed_items
        ]
        if not scores:
            return round(existing, 1)
        session_accuracy = (sum(scores) / len(scores)) * 100
        if existing <= 0:
            return round(session_accuracy, 1)
        return round((existing * 0.7) + (session_accuracy * 0.3), 1)

    def canonical_response_speed(self, *, existing: float, session_result) -> float:
        if "response_speed_seconds" in session_result.skill_scores:
            return round(float(session_result.skill_scores["response_speed_seconds"]), 1)
        return round(existing, 1)
