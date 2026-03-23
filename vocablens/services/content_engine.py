from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass

from vocablens.services.business_metrics_service import BusinessMetricsService
from vocablens.services.conversion_funnel_service import ConversionFunnelService
from vocablens.services.gamification_service import GamificationService
from vocablens.services.progress_service import ProgressService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.virality_service import ViralityService


@dataclass(frozen=True)
class ContentIdea:
    angle: str
    format: str
    hook: str
    concept: str
    proof_points: list[str]
    cta: str
    source_signals: dict[str, object]


class ContentEngine:
    def __init__(
        self,
        progress_service: ProgressService,
        retention_engine: RetentionEngine,
        conversion_funnel_service: ConversionFunnelService | None = None,
        virality_service: ViralityService | None = None,
        gamification_service: GamificationService | None = None,
        business_metrics_service: BusinessMetricsService | None = None,
    ):
        self._progress = progress_service
        self._retention = retention_engine
        self._funnel = conversion_funnel_service
        self._virality = virality_service
        self._gamification = gamification_service
        self._business = business_metrics_service

    async def ideas_for_user(self, user_id: int, *, limit: int = 5) -> list[ContentIdea]:
        progress = await self._progress.build_dashboard(user_id)
        retention = await self._retention.assess_user(user_id)
        funnel = await self._funnel.state(user_id) if self._funnel else None
        virality = await self._virality.referral_summary(user_id) if self._virality else None
        gamification = await self._gamification.summary(user_id) if self._gamification else None

        metrics = progress.get("metrics", {})
        daily = progress.get("daily", {})
        weekly = progress.get("weekly", {})
        weak_skills = progress.get("skill_breakdown", {})

        ideas = [
            ContentIdea(
                angle="transformation",
                format="before_after_tutor_clip",
                hook=f"I fixed my speaking accuracy from awkward to {metrics.get('accuracy_rate', 0.0)}% with one tutor loop.",
                concept="Show a rough first attempt, then the corrected tutor response and the cleaned-up final answer.",
                proof_points=[
                    f"Accuracy rate: {metrics.get('accuracy_rate', 0.0)}%",
                    f"Fluency score: {metrics.get('fluency_score', 0.0)}",
                    f"Messages sent today: {daily.get('messages_sent', 0)}",
                ],
                cta="Try one corrected conversation and post your before/after.",
                source_signals={
                    "accuracy_rate": metrics.get("accuracy_rate", 0.0),
                    "fluency_score": metrics.get("fluency_score", 0.0),
                },
            ),
        ]

        if gamification is not None:
            ideas.append(
                ContentIdea(
                    angle="gamification",
                    format="level_up_recap",
                    hook=f"I just hit level {gamification.level} in language learning.",
                    concept="Show the level-up bar, earned badges, and the next streak milestone as the reason to come back tomorrow.",
                    proof_points=[
                        f"XP: {gamification.xp}",
                        f"Level: {gamification.level}",
                        f"Badges: {len(gamification.badges)}",
                    ],
                    cta="Ask viewers what badge or level they would grind for next.",
                    source_signals={
                        "xp": gamification.xp,
                        "level": gamification.level,
                        "badges": [badge.key for badge in gamification.badges],
                    },
                )
            )

        ideas.append(
            ContentIdea(
                angle="consistency",
                format="streak_progress_story",
                hook=f"This is what a {retention.current_streak}-day language streak actually looks like.",
                concept="Open on the streak, then reveal daily progress, review volume, and one small visible win.",
                proof_points=[
                    f"Current streak: {retention.current_streak}",
                    f"Words learned today: {daily.get('words_learned', 0)}",
                    f"Reviews completed this week: {weekly.get('reviews_completed', 0)}",
                ],
                cta="Show your streak dashboard and challenge a friend to beat it.",
                source_signals={
                    "current_streak": retention.current_streak,
                    "weekly_reviews_completed": weekly.get("reviews_completed", 0),
                },
            )
        )

        if funnel is not None:
            ideas.append(
                ContentIdea(
                    angle="wow_moment",
                    format="product_reveal_story",
                    hook=f"The moment a learner hits '{funnel.stage}' is where the product starts feeling addictive.",
                    concept="Frame the content around the moment the learner sees real value, then connect that to the next action in the funnel.",
                    proof_points=[
                        f"Current funnel stage: {funnel.stage}",
                        f"Suggested next action: {funnel.next_action}",
                        f"Nudges: {', '.join(funnel.nudges[:2]) or 'none'}",
                    ],
                    cta="Make the first wow moment visible in the first 10 seconds.",
                    source_signals={
                        "funnel_stage": funnel.stage,
                        "next_action": funnel.next_action,
                    },
                )
            )

        if virality is not None:
            ideas.append(
                ContentIdea(
                    angle="social_proof",
                    format="challenge_invite_clip",
                    hook=f"{virality['referrals_count']} friends joined from one learning streak update.",
                    concept="Turn a personal progress share into a direct challenge clip with a referral reward angle.",
                    proof_points=[
                        f"Referrals: {virality['referrals_count']}",
                        f"Progress shares: {virality['progress_shares']}",
                        f"XP earned from referrals: {virality['total_xp_earned']}",
                    ],
                    cta="End with a challenge link and referral reward callout.",
                    source_signals=virality,
                )
            )

        ideas.append(
            ContentIdea(
                angle="teaching",
                format="micro_lesson_breakdown",
                hook=f"My weakest area was {self._weakest_skill(weak_skills)}. Here’s the 20-second fix.",
                concept="Teach one common mistake pattern or weak skill with a fast correction and a memorable example.",
                proof_points=[
                    f"Weakest skill: {self._weakest_skill(weak_skills)}",
                    f"Vocabulary mastery: {metrics.get('vocabulary_mastery_percent', 0.0)}%",
                    f"Response speed: {metrics.get('response_speed_seconds', 0.0)}s",
                ],
                cta="Turn your weakest skill into your next video topic.",
                source_signals={
                    "weakest_skill": self._weakest_skill(weak_skills),
                    "mastery_percent": metrics.get("vocabulary_mastery_percent", 0.0),
                },
            )
        )

        return ideas[: max(1, limit)]

    async def operator_ideas(self, *, limit: int = 5) -> list[ContentIdea]:
        if self._business is None:
            return []
        dashboard = await self._business.dashboard()
        if is_dataclass(dashboard):
            dashboard = asdict(dashboard)
        revenue = dashboard.get("revenue", {})
        stages = dashboard.get("funnel", {}).get("conversion_per_stage", [])
        retention_curves = dashboard.get("retention_visualization", {}).get("curves", [])
        bottleneck = max(stages, key=lambda row: row.get("drop_off_rate", 0.0), default=None)
        best_curve = retention_curves[0] if retention_curves else None

        ideas = [
            ContentIdea(
                angle="founder_build_in_public",
                format="metrics_recap",
                hook=f"We’re at ${revenue.get('mrr', 0.0)} MRR and here’s the product loop driving it.",
                concept="Break down the learning, retention, and monetization system behind current recurring revenue.",
                proof_points=[
                    f"MRR: ${revenue.get('mrr', 0.0)}",
                    f"ARPU: ${revenue.get('arpu', 0.0)}",
                    f"LTV: ${revenue.get('ltv', 0.0)}",
                ],
                cta="Close by inviting viewers to follow the next product iteration.",
                source_signals=revenue,
            )
        ]

        if bottleneck is not None:
            ideas.append(
                ContentIdea(
                    angle="funnel_breakdown",
                    format="whiteboard_explainer",
                    hook=f"Our biggest growth leak is at '{bottleneck.get('stage')}', and the drop-off is {bottleneck.get('drop_off_rate', 0.0)}%.",
                    concept="Walk through one funnel stage, show why users stall there, and reveal the experiment or content idea that should fix it.",
                    proof_points=[
                        f"Stage: {bottleneck.get('stage')}",
                        f"Users at stage: {bottleneck.get('users', 0)}",
                        f"Drop-off rate: {bottleneck.get('drop_off_rate', 0.0)}%",
                    ],
                    cta="Invite viewers to suggest the next experiment for that bottleneck.",
                    source_signals=bottleneck,
                )
            )

        if best_curve is not None:
            d7 = next((point.get("retention", 0.0) for point in best_curve.get("points", []) if point.get("day") == 7), 0.0)
            ideas.append(
                ContentIdea(
                    angle="retention_story",
                    format="chart_to_story",
                    hook=f"Our D7 retention for cohort {best_curve.get('cohort_date')} is {d7}%. Here’s what changed.",
                    concept="Start with the retention curve visual, then tell the product changes behind that curve movement.",
                    proof_points=[
                        f"Cohort: {best_curve.get('cohort_date')}",
                        f"Curve points: {best_curve.get('points')}",
                    ],
                    cta="Use the chart as the thumbnail and the change list as the payoff.",
                    source_signals=best_curve,
                )
            )

        return ideas[: max(1, limit)]

    def _weakest_skill(self, skill_breakdown: dict) -> str:
        if not skill_breakdown:
            return "fluency"
        return min(skill_breakdown.items(), key=lambda item: item[1])[0]
