from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TutorModeContext:
    difficulty: str
    content_type: str
    recurring_mistakes: list[str]
    next_action: str | None = None
    next_action_reason: str | None = None


class TutorModeService:
    """
    Builds tutor-mode guidance and response metadata without changing the
    conversation API contract.
    """

    def build_context(self, profile: Any | None, patterns: list[Any], recommendation: Any | None) -> TutorModeContext:
        difficulty = (getattr(profile, "difficulty_preference", "medium") or "medium").lower()
        content_type = getattr(profile, "content_preference", "mixed") or "mixed"
        recurring_mistakes = [getattr(pattern, "pattern", str(pattern)) for pattern in patterns]
        return TutorModeContext(
            difficulty=difficulty,
            content_type=content_type,
            recurring_mistakes=recurring_mistakes,
            next_action=getattr(recommendation, "action", None),
            next_action_reason=getattr(recommendation, "reason", None),
        )

    def prompt_suffix(self, context: TutorModeContext, correction_feedback: list[str], tutor_depth: str = "deep") -> str:
        recurring_mistakes = context.recurring_mistakes if tutor_depth != "basic" else context.recurring_mistakes[:1]
        coaching_points = correction_feedback[: 1 if tutor_depth == "basic" else 3]
        return (
            "\nTutor mode ON. Act like a supportive human tutor in a live lesson. "
            f"Difficulty: {context.difficulty}. Preferred content type: {context.content_type}. "
            "Keep the conversation natural and responsive. "
            "After the learner message, give a short corrected version when needed, "
            "then continue the conversation. "
            "Include one brief explanation only when it helps the learner improve. "
            "Use the learner's skill level to adapt sentence length and complexity. "
            f"Known recurring mistakes: {recurring_mistakes}. "
            f"Priority coaching points: {coaching_points}. "
            f"Preferred next action: {context.next_action} ({context.next_action_reason}). "
            "Keep the tone encouraging and concise."
        )

    def response_payload(self, brain_output: dict, recommendation: Any | None, context: TutorModeContext, reply: str, tutor_depth: str = "deep") -> dict:
        correction_feedback = brain_output.get("correction_feedback", [])
        drills = brain_output.get("drills")
        thinking_explanation = brain_output.get("thinking_explanation")
        live_corrections = correction_feedback[:1] if tutor_depth == "basic" else correction_feedback[:3]
        mistake_memory = context.recurring_mistakes[:1] if tutor_depth == "basic" else context.recurring_mistakes
        return {
            "reply": reply,
            "analysis": brain_output["analysis"],
            "drills": drills,
            "correction_feedback": correction_feedback,
            "thinking_explanation": thinking_explanation,
            "live_corrections": live_corrections,
            "inline_explanations": self._inline_explanations(correction_feedback, drills, thinking_explanation, tutor_depth),
            "mistake_memory": mistake_memory,
            "next_action": recommendation.action if recommendation else None,
            "next_action_reason": recommendation.reason if recommendation else None,
            "lesson_difficulty": getattr(recommendation, "lesson_difficulty", context.difficulty),
            "content_type": getattr(recommendation, "content_type", context.content_type),
            "tutor_mode": True,
            "tutor_depth": tutor_depth,
        }

    def _inline_explanations(self, correction_feedback: list[str], drills: Any, thinking_explanation: dict | None, tutor_depth: str) -> list[str]:
        max_items = 1 if tutor_depth == "basic" else 3
        explanations = [str(item) for item in correction_feedback[: (1 if tutor_depth == "basic" else 2)]]
        if thinking_explanation:
            keys = ("grammar_mistake",) if tutor_depth == "basic" else ("grammar_mistake", "native_level_explanation")
            for key in keys:
                value = thinking_explanation.get(key)
                if value:
                    explanations.append(str(value))
                    if len(explanations) >= max_items:
                        return explanations[:max_items]
        if isinstance(drills, dict):
            for key in ("explanation", "instructions", "focus"):
                value = drills.get(key)
                if value:
                    explanations.append(str(value))
                    break
        elif isinstance(drills, list):
            for item in drills[:2]:
                if isinstance(item, dict):
                    value = item.get("explanation") or item.get("instructions") or item.get("focus")
                    if value:
                        explanations.append(str(value))
                elif item:
                    explanations.append(str(item))
        return explanations[:max_items]
