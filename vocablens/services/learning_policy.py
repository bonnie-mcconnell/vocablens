from __future__ import annotations

from dataclasses import dataclass

from vocablens.core.time import utc_now


@dataclass(frozen=True)
class LearningSnapshot:
    learning_state: object
    due_items: list
    total_vocab: list
    patterns: list
    repeated_patterns: list
    weak_clusters: list
    sparse_cluster: str | None
    recent_events: list
    profile: object
    retention: object | None
    feature_level: str
    learning_variant: str | None
    adaptation: object


class LearningRecommendationPolicy:
    def __init__(self, scheduler):
        self._scheduler = scheduler

    def choose(self, snapshot: LearningSnapshot, recommendation_type):
        profile = snapshot.profile
        difficulty_pref = (profile.difficulty_preference if profile else "medium").lower()
        retention_rate = profile.retention_rate if profile else 0.8
        grammar_thresh = 0.45 if difficulty_pref != "easy" else 0.55
        vocab_thresh = 0.5 if difficulty_pref != "easy" else 0.6

        due_pressure = self.review_pressure(
            snapshot.due_items,
            retention_rate,
            snapshot.adaptation.review_frequency_multiplier,
            snapshot.patterns,
        )
        review_vs_new_bias = self.review_vs_new_bias(snapshot.total_vocab, snapshot.recent_events, retention_rate)
        prioritized_due = self.prioritize_due_items(snapshot.due_items, retention_rate, snapshot.patterns)
        weak_areas = list(getattr(snapshot.learning_state, "weak_areas", []) or [])
        adaptation = snapshot.adaptation
        if snapshot.learning_variant == "review_heavy":
            review_vs_new_bias = max(review_vs_new_bias, 0.7)
        if snapshot.learning_variant == "vocab_focus":
            adaptation.content_type = "vocab"

        skills = dict(getattr(snapshot.learning_state, "skills", {}) or {})
        grammar_score = skills.get("grammar", 0.5)
        vocab_score = skills.get("vocabulary", 0.5)
        fluency_score = skills.get("fluency", 0.5)
        retention = snapshot.retention

        if retention and retention.state in {"at-risk", "churned"} and prioritized_due:
            return recommendation_type(
                "review_word",
                prioritized_due[0].source_text,
                f"Retention is slipping, so start with one due review that the learner can finish quickly",
                review_priority=due_pressure,
                due_items_count=len(prioritized_due),
            )

        if retention and retention.state in {"at-risk", "churned"} and snapshot.repeated_patterns:
            return recommendation_type(
                "conversation_drill",
                snapshot.repeated_patterns[0].pattern,
                "Retention is slipping, so use a short targeted drill instead of a heavier lesson",
                skill_focus="fluency",
            )

        if prioritized_due and (due_pressure >= 0.4 or review_vs_new_bias >= 0.5):
            top_due = prioritized_due[0]
            reason = (
                f"{len(prioritized_due)} review item(s) are due, and '{top_due.source_text}' is the one most likely to fade next"
            )
            return recommendation_type(
                "review_word",
                top_due.source_text,
                reason,
                review_priority=self.item_review_priority(top_due, retention_rate, snapshot.patterns),
                due_items_count=len(prioritized_due),
            )

        if grammar_score < grammar_thresh or "grammar" in weak_areas or any(p.category == "grammar" for p in (snapshot.patterns or [])):
            return recommendation_type(
                "practice_grammar",
                "grammar",
                "Grammar accuracy is the weakest part of the current learning state",
                skill_focus="grammar",
            )

        if (
            adaptation.content_type == "vocab"
            or vocab_score < vocab_thresh
            or (snapshot.feature_level != "basic" and weak_areas)
            or (snapshot.feature_level != "basic" and snapshot.weak_clusters)
            or snapshot.sparse_cluster
            or any(p.category == "vocabulary" for p in (snapshot.patterns or []))
        ):
            target = None
            reason = "Vocabulary coverage is thin in the next useful cluster"
            if snapshot.feature_level != "basic" and weak_areas:
                target = weak_areas[0]
                reason = f"'{target}' is still weak, so the next round should reinforce it directly"
            elif snapshot.feature_level != "basic" and snapshot.weak_clusters:
                target = snapshot.weak_clusters[0]["cluster"]
                related = ", ".join(snapshot.weak_clusters[0].get("words", [])[:3])
                reason = f"Cluster '{target}' is underperforming, so reinforce it with related words like {related or 'core examples'}"
            elif snapshot.sparse_cluster:
                target = snapshot.sparse_cluster
            else:
                target = "general"
            return recommendation_type(
                "learn_new_word",
                target,
                reason,
                skill_focus="vocabulary",
            )

        if snapshot.repeated_patterns:
            top = snapshot.repeated_patterns[0]
            return recommendation_type(
                "conversation_drill",
                top.pattern,
                "A repeated error pattern is stable enough to target directly in a short drill",
                skill_focus="fluency",
            )

        if snapshot.learning_variant == "conversation_focus" and fluency_score < 0.75:
            return recommendation_type(
                "conversation_drill",
                None,
                "This experiment variant is prioritizing guided fluency work",
                skill_focus="fluency",
            )

        if adaptation.content_type == "conversation" or fluency_score < 0.6:
            return recommendation_type(
                "conversation_drill",
                None,
                "Use a short guided drill to tighten fluency without opening full chat",
                skill_focus="fluency",
            )

        return recommendation_type(
            "learn_new_word",
            snapshot.sparse_cluster or "general",
            "Introduce one new item while review pressure is still under control",
            skill_focus="vocabulary",
        )

    def review_pressure(self, due_items, retention_rate: float, frequency_multiplier: float, patterns) -> float:
        if not due_items:
            return 0.0
        max_urgency = 0.0
        total_urgency = 0.0
        for item in due_items:
            urgency = self.item_review_priority(item, retention_rate, patterns)
            total_urgency += urgency
            max_urgency = max(max_urgency, urgency)
        average_urgency = total_urgency / max(1, len(due_items))
        due_load = min(1.0, len(due_items) / max(4, int(8 * max(frequency_multiplier, 0.6))))
        return max(max_urgency, average_urgency, due_load)

    def review_vs_new_bias(self, total_vocab, recent_events, retention_rate: float) -> float:
        total_count = len(total_vocab)
        recent_new = sum(1 for event in recent_events if event.event_type == "word_learned")
        recent_reviews = sum(1 for event in recent_events if event.event_type == "word_reviewed")
        if total_count < 20:
            return 0.25
        if recent_new > recent_reviews and retention_rate < 0.75:
            return 0.7
        if recent_reviews > recent_new:
            return 0.35
        return 0.5

    def prioritize_due_items(self, due_items, retention_rate: float, patterns):
        return sorted(
            due_items,
            key=lambda item: (
                -self.item_review_priority(item, retention_rate, patterns),
                getattr(item, "next_review_due", utc_now()),
            ),
        )

    def item_review_priority(self, item, retention_rate: float, patterns) -> float:
        difficulty_score = min(1.0, max(0.0, (len(getattr(item, "source_text", "") or "") / 12.0)))
        mistake_frequency = self.mistake_frequency(getattr(item, "source_text", None), patterns)
        stored_decay = float(getattr(item, "decay_score", 0.0) or 0.0)
        dynamic_decay = self._scheduler.decay_score(
            item,
            retention_rate=retention_rate,
            mistake_frequency=mistake_frequency,
            difficulty_score=difficulty_score,
        )
        success_penalty = max(0.0, 0.7 - float(getattr(item, "success_rate", 0.0) or 0.0))
        return max(stored_decay, dynamic_decay) + (success_penalty * 0.4)

    def mistake_frequency(self, source_text: str | None, patterns) -> int:
        if not source_text:
            return 0
        frequency = 0
        needle = source_text.lower()
        for pattern in patterns or []:
            if needle in str(getattr(pattern, "pattern", "")).lower():
                frequency += int(getattr(pattern, "count", 1) or 1)
        return frequency
