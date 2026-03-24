from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal
from uuid import uuid4

from vocablens.core.time import utc_now
from vocablens.domain.errors import ConflictError, NotFoundError
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.event_service import EventService
from vocablens.services.experiment_attribution_service import ExperimentAttributionService
from vocablens.services.gamification_service import GamificationService
from vocablens.services.learning_engine import LearningEngine, ReviewedKnowledge, SessionResult
from vocablens.services.wow_engine import WowEngine

SESSION_CONTRACT_VERSION = "v2"
SessionMode = Literal["review", "drill", "sentence", "rewrite"]
SessionPhaseName = Literal["warmup", "core_challenge", "correction_engine", "reinforcement", "win_moment"]


@dataclass(frozen=True)
class SessionPrompt:
    prompt: str
    expected_answer: str
    accepted_keywords: list[str]
    item_id: int | None = None
    skill_focus: str | None = None
    target: str | None = None
    mode: SessionMode = "drill"


@dataclass(frozen=True)
class SessionPhase:
    name: SessionPhaseName
    duration_seconds: int
    title: str
    directive: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class StructuredSession:
    duration_seconds: int
    mode: Literal["game_round"]
    weak_area: str
    lesson_target: str | None
    goal_label: str
    success_criteria: str
    review_window_minutes: int
    max_response_words: int
    phases: list[SessionPhase]


@dataclass(frozen=True)
class SessionFeedback:
    structured: bool
    targeted_weak_area: str
    is_correct: bool
    improvement_score: float
    corrected_response: str
    highlighted_mistakes: list[str]
    reinforcement_prompt: str
    variation_prompt: str
    win_message: str
    wow_score: float
    xp_preview: int
    badges_preview: list[str]
    progress_summary: str
    recommended_next_step: str
    review_window_minutes: int


@dataclass(frozen=True)
class SessionEvaluation:
    feedback: SessionFeedback
    session_result: SessionResult


class SessionEngine:
    """
    Builds a fixed five-step tutor round:
    warmup -> core challenge -> correction -> reinforcement -> win moment.
    """

    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        learning_engine: LearningEngine,
        wow_engine: WowEngine,
        gamification_service: GamificationService | None = None,
        event_service: EventService | None = None,
        experiment_attribution_service: ExperimentAttributionService | None = None,
    ):
        self._uow_factory = uow_factory
        self._learning_engine = learning_engine
        self._wow_engine = wow_engine
        self._gamification = gamification_service
        self._event_service = event_service
        self._attribution = experiment_attribution_service

    async def start_session(self, user_id: int) -> dict[str, Any]:
        session = await self.build_session(user_id)
        self._assert_session_quality(session)
        payload = self.to_payload(session)
        session_id = uuid4().hex
        created_at = utc_now()
        expires_at = created_at + timedelta(minutes=max(5, session.review_window_minutes))

        async with self._uow_factory() as uow:
            await uow.learning_sessions.create(
                session_id=session_id,
                user_id=user_id,
                contract_version=SESSION_CONTRACT_VERSION,
                duration_seconds=session.duration_seconds,
                mode=session.mode,
                weak_area=session.weak_area,
                lesson_target=session.lesson_target,
                goal_label=session.goal_label,
                success_criteria=session.success_criteria,
                review_window_minutes=session.review_window_minutes,
                max_response_words=session.max_response_words,
                session_payload=payload,
                expires_at=expires_at,
            )
            await uow.commit()

        if self._event_service:
            await self._event_service.track_event(
                user_id=user_id,
                event_type="session_started",
                payload={
                    "source": "session_engine",
                    "session_id": session_id,
                    "weak_area": session.weak_area,
                    "goal_label": session.goal_label,
                },
            )

        response = dict(payload)
        response["session_id"] = session_id
        response["status"] = "active"
        response["contract_version"] = SESSION_CONTRACT_VERSION
        response["expires_at"] = expires_at.isoformat()
        return response

    async def build_session(self, user_id: int) -> StructuredSession:
        recommendation = await self._learning_engine.get_next_lesson(user_id)
        async with self._uow_factory() as uow:
            due_items = await uow.vocab.list_due(user_id)
            weak_clusters = await uow.knowledge_graph.get_weak_clusters(user_id)
            skills = await uow.skill_tracking.latest_scores(user_id)
            mistakes = await uow.mistake_patterns.top_patterns(user_id, limit=3)
            await uow.commit()

        weak_area = self._target_weak_area(recommendation, skills, weak_clusters, mistakes)
        warmup_prompt = self._warmup_prompt(due_items, recommendation, weak_area)
        core_prompt = self._core_prompt(recommendation, weak_area, weak_clusters)
        correction_payload = self._correction_payload(core_prompt)
        reinforcement_payload = self._reinforcement_payload(core_prompt)
        win_payload = self._win_payload(weak_area)

        phases = [
            SessionPhase(
                name="warmup",
                duration_seconds=30,
                title="Warmup",
                directive="Quick recall only. One short answer.",
                payload={
                    "mode": warmup_prompt.mode,
                    "prompt": warmup_prompt.prompt,
                    "expected_answer": warmup_prompt.expected_answer,
                    "accepted_keywords": warmup_prompt.accepted_keywords,
                    "item_id": warmup_prompt.item_id,
                },
            ),
            SessionPhase(
                name="core_challenge",
                duration_seconds=120,
                title="Core Challenge",
                directive="Short constrained output. No open chat.",
                payload={
                    "mode": core_prompt.mode,
                    "prompt": core_prompt.prompt,
                    "expected_answer": core_prompt.expected_answer,
                    "accepted_keywords": core_prompt.accepted_keywords,
                    "skill_focus": core_prompt.skill_focus,
                    "target": core_prompt.target,
                },
            ),
            SessionPhase(
                name="correction_engine",
                duration_seconds=20,
                title="Correction",
                directive="Highlight exactly what changed.",
                payload=correction_payload,
            ),
            SessionPhase(
                name="reinforcement",
                duration_seconds=35,
                title="Reinforcement",
                directive="Repeat the corrected form, then one slight variation.",
                payload=reinforcement_payload,
            ),
            SessionPhase(
                name="win_moment",
                duration_seconds=15,
                title="Win",
                directive="Show visible progress before exit.",
                payload=win_payload,
            ),
        ]

        return StructuredSession(
            duration_seconds=220,
            mode="game_round",
            weak_area=weak_area,
            lesson_target=recommendation.target,
            goal_label=str(getattr(recommendation, "goal_label", None) or self._goal_label(weak_area)),
            success_criteria=self._success_criteria(core_prompt),
            review_window_minutes=int(getattr(recommendation, "review_window_minutes", None) or 15),
            max_response_words=12,
            phases=phases,
        )

    async def evaluate_session(
        self,
        user_id: int,
        session_id: str,
        learner_response: str,
        *,
        submission_id: str,
        contract_version: str,
    ) -> SessionFeedback:
        now = utc_now()
        async with self._uow_factory() as uow:
            stored_session = await uow.learning_sessions.get(user_id=user_id, session_id=session_id)
            if stored_session is None:
                raise NotFoundError("Session not found")
            prior_attempt = await uow.learning_sessions.get_attempt_by_submission(
                session_id=session_id,
                user_id=user_id,
                submission_id=submission_id,
            )
            if prior_attempt is not None:
                await uow.commit()
                return self.feedback_from_payload(prior_attempt.feedback_payload)
            if stored_session.contract_version != contract_version:
                raise ConflictError("Session contract is stale")
            if stored_session.status == "completed":
                raise ConflictError("Session already completed")
            if stored_session.expires_at <= now:
                await uow.learning_sessions.mark_expired(
                    user_id=user_id,
                    session_id=session_id,
                    expired_at=now,
                )
                await uow.commit()
                raise ConflictError("Session expired")

        session = self.from_payload(stored_session.session_payload)
        validation = self._validate_submission(session, learner_response, stored_session.max_response_words)
        evaluation = await self._evaluate_session(user_id, session, learner_response)
        feedback = evaluation.feedback
        feedback_payload = {
            **self.feedback_to_payload(feedback),
            "submission_id": submission_id,
            "contract_version": contract_version,
            "validation": validation,
        }

        async with self._uow_factory() as uow:
            summary = await self._learning_engine.apply_session_result(
                user_id,
                evaluation.session_result,
                source="session_engine",
                uow=uow,
                reference_id=session_id,
            )
            await uow.learning_sessions.record_attempt(
                session_id=session_id,
                user_id=user_id,
                submission_id=submission_id,
                learner_response=learner_response,
                response_word_count=validation["response_word_count"],
                response_char_count=validation["response_char_count"],
                is_correct=feedback.is_correct,
                improvement_score=feedback.improvement_score,
                validation_payload=validation,
                feedback_payload={
                    **feedback_payload,
                    "knowledge_update": {
                        "reviewed_count": summary.reviewed_count,
                        "learned_count": summary.learned_count,
                        "updated_item_ids": summary.updated_item_ids,
                    },
                },
            )
            await uow.learning_sessions.mark_completed(
                user_id=user_id,
                session_id=session_id,
                completed_at=utc_now(),
            )
            await uow.events.record(
                user_id=user_id,
                event_type="session_ended",
                payload={
                    "source": "session_engine",
                    "session_id": session_id,
                    "weak_area": feedback.targeted_weak_area,
                    "is_correct": feedback.is_correct,
                    "improvement_score": feedback.improvement_score,
                },
            )
            await uow.events.record(
                user_id=user_id,
                event_type="lesson_completed",
                payload={
                    "source": "session_engine",
                    "session_id": session_id,
                    "weak_area": feedback.targeted_weak_area,
                    "reviewed_count": summary.reviewed_count,
                    "learned_count": summary.learned_count,
                },
            )
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="session_evaluation",
                source="session_engine",
                reference_id=session_id,
                policy_version="v1",
                inputs={
                    "session_id": session_id,
                    "submission_id": submission_id,
                    "contract_version": contract_version,
                    "weak_area": session.weak_area,
                    "lesson_target": session.lesson_target,
                    "learner_response": learner_response,
                },
                outputs={
                    "is_correct": feedback.is_correct,
                    "improvement_score": feedback.improvement_score,
                    "highlighted_mistakes": list(feedback.highlighted_mistakes),
                    "recommended_next_step": feedback.recommended_next_step,
                },
                reason="Evaluated the stored structured session and completed canonical state projection.",
            )
            await uow.commit()

        if self._attribution is not None:
            await self._attribution.record_event(
                user_id=user_id,
                event_type="lesson_completed",
                occurred_at=now,
            )

        return feedback

    def to_payload(self, session: StructuredSession) -> dict[str, Any]:
        return asdict(session)

    def feedback_to_payload(self, feedback: SessionFeedback) -> dict[str, Any]:
        return asdict(feedback)

    def feedback_from_payload(self, payload: dict[str, Any]) -> SessionFeedback:
        return SessionFeedback(
            structured=bool(payload.get("structured", True)),
            targeted_weak_area=str(payload.get("targeted_weak_area") or ""),
            is_correct=bool(payload.get("is_correct", False)),
            improvement_score=float(payload.get("improvement_score", 0.0)),
            corrected_response=str(payload.get("corrected_response") or ""),
            highlighted_mistakes=[str(item) for item in payload.get("highlighted_mistakes", [])],
            reinforcement_prompt=str(payload.get("reinforcement_prompt") or ""),
            variation_prompt=str(payload.get("variation_prompt") or ""),
            win_message=str(payload.get("win_message") or ""),
            wow_score=float(payload.get("wow_score", 0.0)),
            xp_preview=int(payload.get("xp_preview", 0) or 0),
            badges_preview=[str(item) for item in payload.get("badges_preview", [])],
            progress_summary=str(payload.get("progress_summary") or ""),
            recommended_next_step=str(payload.get("recommended_next_step") or ""),
            review_window_minutes=int(payload.get("review_window_minutes", 0) or 0),
        )

    def from_payload(self, payload: dict[str, Any]) -> StructuredSession:
        phases = [
            SessionPhase(
                name=phase["name"],
                duration_seconds=int(phase["duration_seconds"]),
                title=str(phase["title"]),
                directive=str(phase["directive"]),
                payload=dict(phase.get("payload", {})),
            )
            for phase in payload.get("phases", [])
        ]
        return StructuredSession(
            duration_seconds=int(payload.get("duration_seconds", 0)),
            mode=str(payload.get("mode", "game_round")),
            weak_area=str(payload.get("weak_area", "vocabulary")),
            lesson_target=payload.get("lesson_target"),
            goal_label=str(payload.get("goal_label", self._goal_label(str(payload.get("weak_area", "vocabulary"))))),
            success_criteria=str(payload.get("success_criteria", "Hit the target once with a short correct answer.")),
            review_window_minutes=int(payload.get("review_window_minutes", 15)),
            max_response_words=int(payload.get("max_response_words", 12)),
            phases=phases,
        )

    async def evaluate_response(self, user_id: int, session: StructuredSession, learner_response: str) -> SessionFeedback:
        return (await self._evaluate_session(user_id, session, learner_response)).feedback

    async def _evaluate_session(self, user_id: int, session: StructuredSession, learner_response: str) -> SessionEvaluation:
        warmup = self._phase(session, "warmup")
        core = self._phase(session, "core_challenge")
        expected_answer = str(core.payload.get("expected_answer") or "")
        accepted_keywords = [str(item).lower() for item in core.payload.get("accepted_keywords", [])]
        response = (learner_response or "").strip()
        normalized_response = response.lower()

        highlighted_mistakes = self._highlighted_mistakes(normalized_response, accepted_keywords, core.payload)
        corrected_response = expected_answer or response
        is_correct = len(highlighted_mistakes) == 0 and bool(response)
        improvement_score = self._improvement_score(is_correct, accepted_keywords, normalized_response)
        progress_summary = self._progress_summary(improvement_score, session.weak_area, highlighted_mistakes)

        wow = await self._wow_engine.score_session(
            user_id,
            tutor_mode=True,
            correction_feedback_count=max(1, len(highlighted_mistakes)),
            new_words_count=len(core.payload.get("accepted_keywords", [])),
            grammar_mistake_count=len(highlighted_mistakes),
            session_turn_count=2,
            reply_length=len(corrected_response),
        )

        gamification = await self._gamification.summary(user_id) if self._gamification else None
        xp_preview = (gamification.xp if gamification else 0) + 25
        badges_preview = [badge.label for badge in (gamification.badges if gamification else [])[:2]]
        win_message = self._win_message(improvement_score, wow.score, session.weak_area)

        reviewed_items = []
        if warmup.payload.get("item_id") is not None:
            reviewed_items.append(
                ReviewedKnowledge(
                    item_id=int(warmup.payload["item_id"]),
                    quality=5 if is_correct else 2,
                    response_accuracy=improvement_score,
                    mistake_frequency=len(highlighted_mistakes),
                    difficulty_score=0.35 if session.weak_area == "vocabulary" else 0.5,
                )
            )

        skill_scores = {
            session.weak_area: min(1.0, 0.55 + (improvement_score * 0.35))
            if session.weak_area in {"grammar", "vocabulary", "fluency"}
            else 0.6 + (improvement_score * 0.25)
        }
        mistakes = [
            {"category": session.weak_area if session.weak_area in {"grammar", "vocabulary"} else "grammar", "pattern": item}
            for item in highlighted_mistakes
        ]
        return SessionEvaluation(
            feedback=SessionFeedback(
                structured=True,
                targeted_weak_area=session.weak_area,
                is_correct=is_correct,
                improvement_score=improvement_score,
                corrected_response=corrected_response,
                highlighted_mistakes=highlighted_mistakes,
                reinforcement_prompt=f"Repeat exactly: {corrected_response}",
                variation_prompt=self._variation_prompt(core.payload, corrected_response),
                win_message=win_message,
                wow_score=wow.score,
                xp_preview=xp_preview,
                badges_preview=badges_preview,
                progress_summary=progress_summary,
                recommended_next_step=self._recommended_next_step(improvement_score, session),
                review_window_minutes=session.review_window_minutes,
            ),
            session_result=SessionResult(
                reviewed_items=reviewed_items,
                skill_scores=skill_scores,
                mistakes=mistakes,
                weak_areas=[session.weak_area, str(core.payload.get("target") or session.lesson_target or "")],
            ),
        )

    def _target_weak_area(self, recommendation, skills: dict[str, float], weak_clusters, mistakes) -> str:
        if getattr(recommendation, "skill_focus", None):
            return str(recommendation.skill_focus)
        if skills:
            lowest_skill = min(skills.items(), key=lambda item: item[1])[0]
            return str(lowest_skill)
        if weak_clusters:
            return str(weak_clusters[0].get("cluster") or "vocabulary")
        if mistakes:
            return str(getattr(mistakes[0], "category", "grammar"))
        return "vocabulary"

    def _warmup_prompt(self, due_items, recommendation, weak_area: str) -> SessionPrompt:
        if due_items:
            item = due_items[0]
            return SessionPrompt(
                prompt=f"Warmup: translate '{item.source_text}' in one word.",
                expected_answer=getattr(item, "translated_text", "answer"),
                accepted_keywords=[getattr(item, "translated_text", "answer")],
                item_id=getattr(item, "id", None),
                skill_focus="vocabulary",
                target=getattr(item, "source_text", None),
                mode="review",
            )
        target = getattr(recommendation, "target", None) or weak_area
        return SessionPrompt(
            prompt=f"Warmup: say one correct answer for {target}.",
            expected_answer=str(target),
            accepted_keywords=[str(target)],
            skill_focus=weak_area,
            target=str(target),
            mode="drill",
        )

    def _core_prompt(self, recommendation, weak_area: str, weak_clusters) -> SessionPrompt:
        target = getattr(recommendation, "target", None) or weak_area
        if recommendation.action == "practice_grammar":
            return SessionPrompt(
                prompt="Core round: rewrite 'I goed there yesterday' correctly.",
                expected_answer="I went there yesterday.",
                accepted_keywords=["went", "yesterday"],
                skill_focus="grammar",
                target="past tense",
                mode="rewrite",
            )
        if recommendation.action == "review_word":
            return SessionPrompt(
                prompt=f"Core round: use '{target}' in one short sentence.",
                expected_answer=f"I use {target} correctly.",
                accepted_keywords=[str(target)],
                skill_focus="vocabulary",
                target=str(target),
                mode="sentence",
            )
        if recommendation.action == "conversation_drill":
            topic = str(target or (weak_clusters[0]["cluster"] if weak_clusters else "travel"))
            return SessionPrompt(
                prompt=f"Core round: answer in one sentence only about {topic}.",
                expected_answer=f"I am practicing {topic} today.",
                accepted_keywords=[topic.split()[0], "practice"],
                skill_focus="fluency",
                target=topic,
                mode="sentence",
            )
        cluster = str(target or "general")
        return SessionPrompt(
            prompt=f"Core round: complete the phrase with one {cluster} word only.",
            expected_answer=cluster,
            accepted_keywords=[cluster.split()[0]],
            skill_focus="vocabulary",
            target=cluster,
            mode="drill",
        )

    def _correction_payload(self, core_prompt: SessionPrompt) -> dict[str, Any]:
        return {
            "show_highlight_diff": True,
            "correction_label": "Fix",
            "example": core_prompt.expected_answer,
            "focus": core_prompt.skill_focus,
        }

    def _reinforcement_payload(self, core_prompt: SessionPrompt) -> dict[str, Any]:
        return {
            "repeat_prompt": f"Repeat: {core_prompt.expected_answer}",
            "variation_prompt": self._variation_prompt(
                {"target": core_prompt.target, "skill_focus": core_prompt.skill_focus},
                core_prompt.expected_answer,
            ),
        }

    def _win_payload(self, weak_area: str) -> dict[str, Any]:
        return {
            "headline": "Round complete",
            "improvement_label": "Improvement score",
            "focus": weak_area,
        }

    def _goal_label(self, weak_area: str) -> str:
        if weak_area == "grammar":
            return "Fix one grammar pattern cleanly"
        if weak_area == "fluency":
            return "Say one idea clearly without drifting"
        return "Bring one target back into active memory"

    def _success_criteria(self, prompt: SessionPrompt) -> str:
        if prompt.mode == "rewrite":
            return "Use the corrected form without carrying the original mistake forward."
        if prompt.mode == "sentence":
            return "Give one short sentence that uses the target naturally."
        if prompt.mode == "review":
            return "Recall the answer quickly without a full explanation."
        return "Give one short correct answer with the target keyword."

    def _assert_session_quality(self, session: StructuredSession) -> None:
        phase_names = [phase.name for phase in session.phases]
        if phase_names != ["warmup", "core_challenge", "correction_engine", "reinforcement", "win_moment"]:
            raise ConflictError("Session contract is invalid")
        core = self._phase(session, "core_challenge")
        if not str(core.payload.get("prompt") or "").strip():
            raise ConflictError("Session content failed quality validation")
        if not list(core.payload.get("accepted_keywords", []) or []):
            raise ConflictError("Session content failed quality validation")
        if session.max_response_words > 24:
            raise ConflictError("Session content failed quality validation")

    def _validate_submission(self, session: StructuredSession, learner_response: str, max_response_words: int) -> dict[str, Any]:
        response = (learner_response or "").strip()
        response_word_count = len([part for part in response.split() if part])
        response_char_count = len(response)
        if not response:
            raise ConflictError("Session answer is empty")
        if "\n" in response or "\r" in response:
            raise ConflictError("Session answer must be a single short response")
        if response_word_count > max_response_words:
            raise ConflictError("Session answer exceeds the allowed length")
        core = self._phase(session, "core_challenge")
        payload_mode = str(core.payload.get("mode") or "")
        if payload_mode in {"drill", "review"} and response_word_count > 4:
            raise ConflictError("Session answer does not match the round format")
        return {
            "response_word_count": response_word_count,
            "response_char_count": response_char_count,
            "max_response_words": max_response_words,
            "payload_mode": payload_mode,
        }

    def _highlighted_mistakes(self, response: str, accepted_keywords: list[str], payload: dict[str, Any]) -> list[str]:
        if not response:
            return ["No answer submitted"]
        mistakes = []
        for keyword in accepted_keywords:
            if keyword and keyword.lower() not in response:
                mistakes.append(f"Missing key target: {keyword}")
        if payload.get("mode") == "rewrite" and "goed" in response:
            mistakes.append("Use the past tense form 'went'")
        if len(response.split()) > 12:
            mistakes.append("Keep the answer short and constrained")
        return mistakes

    def _improvement_score(self, is_correct: bool, accepted_keywords: list[str], response: str) -> float:
        if not response:
            return 0.2
        coverage = 0.0
        if accepted_keywords:
            hits = sum(1 for keyword in accepted_keywords if keyword and keyword.lower() in response)
            coverage = hits / max(1, len(accepted_keywords))
        base = 0.55 if is_correct else 0.35
        return round(min(1.0, base + (coverage * 0.35)), 3)

    def _variation_prompt(self, payload: dict[str, Any], corrected_response: str) -> str:
        target = payload.get("target") or payload.get("skill_focus") or "the same idea"
        return f"Now say it again with a slight variation about {target}: {corrected_response}"

    def _win_message(self, improvement_score: float, wow_score: float, weak_area: str) -> str:
        percent = int(round(improvement_score * 100))
        wow_percent = int(round(wow_score * 100))
        return f"You brought {weak_area} to {percent}% for this round. Wow score: {wow_percent}%."

    def _progress_summary(self, improvement_score: float, weak_area: str, mistakes: list[str]) -> str:
        percent = int(round(improvement_score * 100))
        if not mistakes:
            return f"{weak_area.title()} landed cleanly at {percent}% for this round."
        return f"{weak_area.title()} improved to {percent}%, with one correction path to repeat next."

    def _recommended_next_step(self, improvement_score: float, session: StructuredSession) -> str:
        if improvement_score >= 0.8:
            return f"Move to the next {session.weak_area} target after a short review."
        return f"Repeat one more {session.weak_area} round inside the next {session.review_window_minutes} minutes."

    def _phase(self, session: StructuredSession, name: SessionPhaseName) -> SessionPhase:
        for phase in session.phases:
            if phase.name == name:
                return phase
        raise ValueError(f"Missing phase '{name}'")
