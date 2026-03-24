from tests.conftest import run_async
from vocablens.services.decision_trace_service import DecisionTraceService


class StubDecisionTraceService(DecisionTraceService):
    def __init__(self):
        super().__init__(lambda: None)

    async def lifecycle_detail(self, user_id: int) -> dict:
        return {
            "lifecycle_transitions": [
                {
                    "id": 4,
                    "user_id": user_id,
                    "from_stage": "new_user",
                    "to_stage": "activating",
                    "reasons": ["user is building toward activation"],
                    "source": "lifecycle_service.evaluate",
                    "reference_id": f"lifecycle:{user_id}",
                    "payload": {},
                    "created_at": "2026-03-23T12:04:30",
                }
            ],
            "events": [
                {"id": 41, "event_type": "paywall_viewed", "payload": {}, "created_at": "2026-03-23T12:01:00"},
                {"id": 42, "event_type": "session_started", "payload": {}, "created_at": "2026-03-23T12:04:00"},
            ],
            "traces": [
                {
                    "id": 7,
                    "user_id": user_id,
                    "trace_type": "lifecycle_action_plan",
                    "source": "lifecycle_service.evaluate",
                    "reference_id": f"lifecycle:{user_id}",
                    "policy_version": "v1",
                    "inputs": {},
                    "outputs": {"action_types": ["wow_moment_push"]},
                    "reason": "Built the lifecycle action bundle before the final lifecycle decision.",
                    "created_at": "2026-03-23T12:04:20",
                },
                {
                    "id": 8,
                    "user_id": user_id,
                    "trace_type": "lifecycle_decision",
                    "source": "lifecycle_service.evaluate",
                    "reference_id": f"lifecycle:{user_id}",
                    "policy_version": "v1",
                    "inputs": {},
                    "outputs": {"stage": "activating"},
                    "reason": "user is building toward activation",
                    "created_at": "2026-03-23T12:04:30",
                },
            ],
        }

    async def monetization_detail(self, user_id: int, *, geography: str | None = None) -> dict:
        return {
            "monetization_events": [
                {
                    "id": 51,
                    "event_type": "decision_evaluated",
                    "offer_type": "trial",
                    "paywall_type": "soft_paywall",
                    "strategy": "high_intent:early:premium_anchor:trial:us",
                    "geography": geography or "global",
                    "payload": {},
                    "created_at": "2026-03-23T12:01:10",
                }
            ],
            "events": [
                {"id": 41, "event_type": "paywall_viewed", "payload": {}, "created_at": "2026-03-23T12:01:00"},
            ],
            "traces": [
                {
                    "id": 9,
                    "user_id": user_id,
                    "trace_type": "monetization_decision",
                    "source": "monetization_engine",
                    "reference_id": f"user:{user_id}",
                    "policy_version": "v1",
                    "inputs": {},
                    "outputs": {"offer_type": "trial"},
                    "reason": "Monetization shown after wow moment for a high-intent activating user.",
                    "created_at": "2026-03-23T12:01:10",
                }
            ],
        }


def test_lifecycle_report_promotes_latest_artifacts_and_summaries():
    service = StubDecisionTraceService()

    report = run_async(service.lifecycle_report(7))

    assert report["latest_decisions"]["lifecycle_decision"]["trace_type"] == "lifecycle_decision"
    assert report["latest_decisions"]["lifecycle_action_plan"]["trace_type"] == "lifecycle_action_plan"
    assert report["event_summary"]["counts_by_type"]["paywall_viewed"] == 1
    assert report["trace_summary"]["counts_by_type"]["lifecycle_decision"] == 1


def test_monetization_report_promotes_latest_artifacts_and_summaries():
    service = StubDecisionTraceService()

    report = run_async(service.monetization_report(9, geography="us"))

    assert report["latest_decisions"]["monetization_decision"]["trace_type"] == "monetization_decision"
    assert report["latest_decisions"]["latest_monetization_event"]["event_type"] == "decision_evaluated"
    assert report["monetization_event_summary"]["counts_by_type"]["decision_evaluated"] == 1
