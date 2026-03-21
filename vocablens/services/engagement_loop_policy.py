from __future__ import annotations

import hashlib
from dataclasses import dataclass

from vocablens.core.time import utc_now


@dataclass(frozen=True)
class EngagementLoopContext:
    retention: object
    progress: dict
    notification: object


class EngagementLoopPolicy:
    def build_trigger(self, retention, notification) -> dict:
        streak_action = next(
            (action for action in retention.suggested_actions if action.kind == "streak_nudge"),
            None,
        )
        if notification.should_send and notification.message is not None:
            return {
                "type": "notification",
                "channel": notification.channel,
                "send_at": notification.send_at.isoformat(),
                "category": notification.message.category,
                "reason": notification.reason,
                "streak_reminder": bool(streak_action or "streak_nudge" in notification.message.category),
            }
        if streak_action is not None:
            return {
                "type": "streak_reminder",
                "channel": None,
                "send_at": None,
                "category": streak_action.kind,
                "reason": streak_action.reason,
                "streak_reminder": True,
            }
        return {
            "type": "passive_reentry",
            "channel": None,
            "send_at": None,
            "category": "habit_reentry",
            "reason": "No outbound trigger available; surface the next habit action in-app.",
            "streak_reminder": False,
        }

    def build_action(self, retention, progress: dict) -> dict:
        quick_session = next(
            (action for action in retention.suggested_actions if action.kind == "quick_session"),
            None,
        )
        if quick_session is not None:
            return {
                "type": "quick_session",
                "duration_minutes": 3,
                "target": quick_session.target or "review",
                "reason": quick_session.reason,
            }
        due_reviews = int(progress.get("due_reviews", 0) or 0)
        focus_area = "review" if due_reviews > 0 else "conversation"
        return {
            "type": "quick_session",
            "duration_minutes": 2,
            "target": focus_area,
            "reason": "Keep the daily habit alive with a low-friction session.",
        }

    def build_reward(self, retention, progress: dict, action: dict) -> dict:
        daily = progress.get("daily", {})
        weekly = progress.get("weekly", {})
        trends = progress.get("trends", {})
        metrics = progress.get("metrics", {})
        progress_gain = max(
            int(daily.get("reviews_completed", 0) or 0),
            int(daily.get("words_learned", 0) or 0),
            1 if float(trends.get("weekly_accuracy_rate_delta", 0.0) or 0.0) > 0 else 0,
        )
        accuracy = float(metrics.get("accuracy_rate", 0.0) or 0.0)
        reviews = int(weekly.get("reviews_completed", 0) or 0)
        return {
            "progress_increase": progress_gain,
            "streak_boost": retention.current_streak + 1,
            "feedback": (
                f"A {action['duration_minutes']}-minute {action['target']} session can add "
                f"{progress_gain} visible progress step(s), move the streak to {retention.current_streak + 1}, "
                f"and build on {reviews} review(s) this week at {accuracy:.1f}% accuracy."
            ),
        }

    def build_repeat(self, retention, trigger: dict, reward: dict) -> dict:
        return {
            "should_repeat": retention.state in {"active", "at-risk"},
            "next_best_trigger": "streak_reminder" if reward["streak_boost"] >= 2 else trigger["type"],
            "cadence": "daily",
        }

    def build_variable_reward(self, *, user_id: int, retention, reward: dict) -> dict:
        progress_gain = int(reward.get("progress_increase", 0) or 0)
        ordinal = utc_now().date().toordinal()
        digest = hashlib.sha256(
            f"{user_id}:{ordinal}:{retention.current_streak}:{progress_gain}".encode("utf-8")
        ).digest()
        bucket = digest[0] % 3
        reward_type = ("bonus_xp", "surprise_streak_boost", "mystery_reward")[bucket]
        xp_bonus = (digest[1] % 11) + 5
        streak_bonus = 1 if reward_type == "surprise_streak_boost" else 0
        return {
            "type": reward_type,
            "bonus_xp": xp_bonus,
            "surprise_streak_boost": streak_bonus,
            "progress_increase": reward.get("progress_increase", 0),
            "feedback": reward.get("feedback"),
        }

    def build_loss_aversion(self, retention, progress: dict) -> dict:
        stale_hours = (
            (utc_now() - retention.last_active_at).total_seconds() / 3600
            if getattr(retention, "last_active_at", None) is not None
            else 999.0
        )
        risk = float(getattr(retention, "drop_off_risk", 0.0) or 0.0)
        trigger_warning = retention.current_streak > 0 and (risk >= 0.45 or stale_hours >= 20)
        progress_loss = max(
            int(progress.get("due_reviews", 0) or 0),
            int(progress.get("daily", {}).get("words_learned", 0) or 0),
        )
        return {
            "show_streak_decay_warning": trigger_warning,
            "will_lose_progress": trigger_warning and progress_loss > 0,
            "warning_message": (
                f"Come back today or you will lose progress on {progress_loss} learning step(s)."
                if trigger_warning
                else ""
            ),
        }

    def build_identity_reinforcement(self, progress: dict) -> dict:
        fluency = float(progress.get("metrics", {}).get("fluency_score", 0.0) or 0.0)
        accuracy = float(progress.get("metrics", {}).get("accuracy_rate", 0.0) or 0.0)
        message = (
            "You are getting closer to becoming fluent."
            if fluency >= 60 or accuracy >= 75
            else "You are building the habits that lead to fluency."
        )
        return {
            "message": message,
            "identity_state": "becoming_fluent",
        }

    def build_ritual_hook(self, notification, retention) -> dict:
        send_at = getattr(notification, "send_at", None)
        ritual_hour = send_at.hour if send_at is not None else 18
        return {
            "daily_ritual_hour": ritual_hour,
            "daily_ritual_message": f"Try to make {ritual_hour:02d}:00 your regular study window.",
            "streak_anchor": retention.current_streak + 1,
        }
