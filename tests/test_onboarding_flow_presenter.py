from vocablens.services.onboarding_flow_presenter import OnboardingFlowPresenter


def test_onboarding_flow_presenter_builds_step_specific_view():
    presenter = OnboardingFlowPresenter()
    state = {
        "current_step": "soft_paywall",
        "identity": {"motivation": "travel"},
        "personalization": {"learning_intent": "conversation"},
        "wow": {"understood_percent": 81.0},
        "progress_illusion": {"xp_gain": 49, "identity": {"message": "You are getting closer to becoming fluent."}},
        "paywall": {"show": True, "trial_recommended": True},
        "habit_lock_in": {},
    }

    view = presenter.build(state=state, lifecycle_stage="activating")

    assert view.current_step == "soft_paywall"
    assert view.ui_directives["show_paywall"] is True
    assert view.ui_directives["show_trial_offer"] is True
    assert view.messaging["urgency_message"].startswith("Lifecycle stage:")
    assert view.next_action["action"] == "offer_trial"
