from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2s
from urllib.parse import quote

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.event_service import EventService
from vocablens.services.progress_service import ProgressService
from vocablens.services.subscription_service import SubscriptionService
from vocablens.services.viral_moment_service import ViralMomentService


@dataclass(frozen=True)
class ReferralInvite:
    code: str
    referrer_user_id: int
    share_url: str
    share_message: str
    rewards: dict[str, int]


@dataclass(frozen=True)
class ReferralRewardResult:
    referrer_user_id: int
    referred_user_id: int
    code: str
    awarded_xp: int
    awarded_premium_days_referrer: int
    awarded_premium_days_referred: int
    status: str


@dataclass(frozen=True)
class ProgressShare:
    user_id: int
    share_text: str
    share_url: str
    stats: dict[str, float | int]


@dataclass(frozen=True)
class MomentShare:
    user_id: int
    moment_type: str
    share_text: str
    share_url: str
    caption: str
    hook: str
    visual_payload: dict[str, object]


class ViralityService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        progress_service: ProgressService,
        subscription_service: SubscriptionService | None = None,
        event_service: EventService | None = None,
        viral_moment_service: ViralMomentService | None = None,
        *,
        share_base_url: str = "https://vocablens.app",
        referral_xp_reward: int = 250,
        referral_premium_days: int = 3,
    ):
        self._uow_factory = uow_factory
        self._progress = progress_service
        self._subscriptions = subscription_service
        self._events = event_service
        self._viral_moments = viral_moment_service
        self._share_base_url = share_base_url.rstrip("/")
        self._referral_xp_reward = int(referral_xp_reward)
        self._referral_premium_days = max(1, int(referral_premium_days))

    async def build_invite(self, user_id: int) -> ReferralInvite:
        user = await self._user(user_id)
        progress = await self._progress.build_dashboard(user_id)
        code = self._referral_code(user.id, user.email)
        mastery = round(float(progress.get("metrics", {}).get("vocabulary_mastery_percent", 0.0) or 0.0), 1)
        share_url = f"{self._share_base_url}/invite/{code}"
        share_message = (
            f"I've reached {mastery}% vocabulary mastery in VocabLens. "
            f"Join with my link for {self._referral_premium_days} free Pro day(s) "
            f"and {self._referral_xp_reward} bonus XP."
        )
        if self._events:
            await self._events.track_event(
                user_id,
                "referral_invite_created",
                {
                    "code": code,
                    "share_url": share_url,
                    "reward_xp": self._referral_xp_reward,
                    "reward_premium_days": self._referral_premium_days,
                },
            )
        return ReferralInvite(
            code=code,
            referrer_user_id=user.id,
            share_url=share_url,
            share_message=share_message,
            rewards={
                "xp": self._referral_xp_reward,
                "premium_days": self._referral_premium_days,
            },
        )

    async def redeem_invite(self, *, code: str, referred_user_id: int) -> ReferralRewardResult:
        referrer_user_id = await self._resolve_referrer_id(code)
        if referrer_user_id == referred_user_id:
            raise ValueError("Users cannot redeem their own referral code")
        await self._user(referred_user_id)
        if await self._has_existing_referral(referred_user_id):
            raise ValueError("User has already redeemed a referral code")

        referrer_premium_days = await self._grant_premium_days(referrer_user_id)
        referred_premium_days = await self._grant_premium_days(referred_user_id)
        reward_payload = {
            "referrer_user_id": referrer_user_id,
            "referred_user_id": referred_user_id,
            "code": code,
            "xp_reward": self._referral_xp_reward,
            "premium_days_referrer": referrer_premium_days,
            "premium_days_referred": referred_premium_days,
        }
        if self._events:
            await self._events.track_event(
                referred_user_id,
                "referral_redeemed",
                reward_payload,
            )
            await self._events.track_event(
                referrer_user_id,
                "referral_reward_granted",
                {**reward_payload, "beneficiary": "referrer"},
            )
            await self._events.track_event(
                referred_user_id,
                "referral_reward_granted",
                {**reward_payload, "beneficiary": "referred"},
            )
        return ReferralRewardResult(
            referrer_user_id=referrer_user_id,
            referred_user_id=referred_user_id,
            code=code,
            awarded_xp=self._referral_xp_reward,
            awarded_premium_days_referrer=referrer_premium_days,
            awarded_premium_days_referred=referred_premium_days,
            status="rewarded",
        )

    async def share_progress(self, user_id: int) -> ProgressShare:
        progress = await self._progress.build_dashboard(user_id)
        stats = {
            "mastery_percent": round(float(progress.get("metrics", {}).get("vocabulary_mastery_percent", 0.0) or 0.0), 1),
            "accuracy_rate": round(float(progress.get("metrics", {}).get("accuracy_rate", 0.0) or 0.0), 1),
            "fluency_score": round(float(progress.get("metrics", {}).get("fluency_score", 0.0) or 0.0), 1),
            "streak": int(progress.get("streak", 0) or 0),
        }
        share_text = (
            f"I'm on a {stats['streak']}-day VocabLens streak with "
            f"{stats['mastery_percent']}% mastery and {stats['accuracy_rate']}% accuracy."
        )
        share_url = (
            f"{self._share_base_url}/share/progress?"
            f"user_id={user_id}&mastery={quote(str(stats['mastery_percent']))}&"
            f"accuracy={quote(str(stats['accuracy_rate']))}&streak={quote(str(stats['streak']))}"
        )
        if self._events:
            await self._events.track_event(
                user_id,
                "progress_shared",
                {
                    "share_url": share_url,
                    "stats": stats,
                },
            )
        return ProgressShare(
            user_id=user_id,
            share_text=share_text,
            share_url=share_url,
            stats=stats,
        )

    async def share_moment(self, user_id: int, moment_type: str | None = None) -> MomentShare:
        if not self._viral_moments:
            progress = await self.share_progress(user_id)
            return MomentShare(
                user_id=user_id,
                moment_type="progress_share",
                share_text=progress.share_text,
                share_url=progress.share_url,
                caption=progress.share_text,
                hook="Share your progress",
                visual_payload=progress.stats,
            )

        moment = await self._viral_moments.best_share_moment(user_id, moment_type)
        if moment is None:
            progress = await self.share_progress(user_id)
            return MomentShare(
                user_id=user_id,
                moment_type="progress_share",
                share_text=progress.share_text,
                share_url=progress.share_url,
                caption=progress.share_text,
                hook="Share your progress",
                visual_payload=progress.stats,
            )

        share_url = (
            f"{self._share_base_url}/share/moment?"
            f"user_id={user_id}&type={quote(moment.type)}&priority={quote(str(moment.priority))}"
        )
        if self._events:
            await self._events.track_event(
                user_id,
                "progress_shared",
                {
                    "share_url": share_url,
                    "moment_type": moment.type,
                    "source_signals": moment.source_signals,
                },
            )
        return MomentShare(
            user_id=user_id,
            moment_type=moment.type,
            share_text=moment.share_text,
            share_url=share_url,
            caption=moment.caption,
            hook=moment.hook,
            visual_payload=moment.visual_payload,
        )

    async def referral_summary(self, user_id: int) -> dict:
        invite = await self.build_invite(user_id)
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_user(user_id, limit=500)
            await uow.commit()
        referred = {
            int(getattr(event, "payload", {}).get("referred_user_id"))
            for event in events
            if getattr(event, "event_type", None) == "referral_reward_granted"
            and getattr(event, "payload", {}).get("beneficiary") == "referrer"
            and getattr(event, "payload", {}).get("referred_user_id") is not None
        }
        shares = sum(1 for event in events if getattr(event, "event_type", None) == "progress_shared")
        return {
            "invite_code": invite.code,
            "share_url": invite.share_url,
            "referrals_count": len(referred),
            "total_xp_earned": len(referred) * self._referral_xp_reward,
            "progress_shares": shares,
        }

    async def _grant_premium_days(self, user_id: int) -> int:
        if not self._subscriptions:
            return 0
        features = await self._subscriptions.get_features(user_id)
        if features.tier != "free" or features.trial_active:
            return 0
        await self._subscriptions.start_trial(user_id, duration_days=self._referral_premium_days)
        return self._referral_premium_days

    async def _has_existing_referral(self, user_id: int) -> bool:
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_user(user_id, limit=200)
            await uow.commit()
        return any(getattr(event, "event_type", None) == "referral_redeemed" for event in events)

    async def _resolve_referrer_id(self, code: str) -> int:
        if not code.startswith("VL-"):
            raise ValueError("Invalid referral code")
        try:
            _, user_id_raw, digest = code.split("-", 2)
            user_id = int(user_id_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid referral code") from exc
        user = await self._user(user_id)
        expected = self._referral_code(user.id, user.email)
        if expected != code or not digest:
            raise ValueError("Invalid referral code")
        return user_id

    async def _user(self, user_id: int):
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_id(user_id)
            await uow.commit()
        if user is None:
            raise ValueError(f"Unknown user {user_id}")
        return user

    def _referral_code(self, user_id: int, email: str) -> str:
        digest = blake2s(f"{user_id}:{email.lower()}".encode("utf-8"), digest_size=4).hexdigest().upper()
        return f"VL-{user_id}-{digest}"
