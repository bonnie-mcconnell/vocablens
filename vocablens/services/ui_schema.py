from __future__ import annotations

from copy import deepcopy

ScreenSchema = dict[str, object]


home_screen_schema: ScreenSchema = {
    "screen": "home",
    "contract_version": "2026-03-21",
    "description": "Primary home experience driven by dashboard and recommendation payloads.",
    "data_sources": [
        {
            "name": "dashboard",
            "endpoint": "/frontend/dashboard",
            "required": True,
            "fields": [
                "progress",
                "subscription",
                "paywall",
                "next_action",
                "retention",
                "weak_areas",
                "ui",
                "session_config",
                "emotion_hooks",
                "roadmap",
            ],
        },
        {
            "name": "recommendations",
            "endpoint": "/frontend/recommendations",
            "required": False,
            "fields": [
                "next_action",
                "retention_actions",
                "paywall",
                "ui",
                "session_config",
                "emotion_hooks",
            ],
        },
    ],
    "layout": {
        "shell": "stack",
        "sections": [
            {"id": "hero", "purpose": "Anchor the next best action and current motivation."},
            {"id": "momentum", "purpose": "Show streak, progress, and urgency."},
            {"id": "focus", "purpose": "Expose roadmap and weak areas to guide action."},
            {"id": "monetization", "purpose": "Reserve space for soft paywall or trial offer."},
        ],
    },
    "components": [
        {
            "id": "hero_next_action",
            "type": "action_hero_card",
            "required": True,
            "bindings": {
                "title": "next_action.action",
                "subtitle": "emotion_hooks.encouragement_message",
                "reason": "next_action.reason",
                "cta_target": "next_action.target",
                "cta_mode": "session_config.mode",
                "difficulty": "session_config.difficulty",
                "duration_minutes": "session_config.session_length",
            },
        },
        {
            "id": "momentum_strip",
            "type": "momentum_strip",
            "required": True,
            "bindings": {
                "streak": "progress.streak",
                "usage_percent": "subscription.usage_percent",
                "reward_message": "emotion_hooks.reward_message",
                "urgency_message": "emotion_hooks.urgency_message",
            },
        },
        {
            "id": "progress_snapshot",
            "type": "progress_snapshot_card",
            "required": True,
            "bindings": {
                "mastery_percent": "progress.metrics.vocabulary_mastery_percent",
                "accuracy_rate": "progress.metrics.accuracy_rate",
                "response_speed_seconds": "progress.metrics.response_speed_seconds",
                "fluency_score": "progress.metrics.fluency_score",
                "daily": "progress.daily",
                "weekly": "progress.weekly",
            },
        },
        {
            "id": "weak_areas",
            "type": "weak_areas_panel",
            "required": False,
            "bindings": {
                "clusters": "weak_areas.clusters",
                "mistakes": "weak_areas.mistakes",
                "skill_breakdown": "progress.skill_breakdown",
            },
        },
        {
            "id": "roadmap",
            "type": "roadmap_list",
            "required": False,
            "bindings": {
                "items": "roadmap",
            },
        },
        {
            "id": "paywall_banner",
            "type": "paywall_banner",
            "required": False,
            "bindings": {
                "visible": "ui.show_paywall",
                "paywall_type": "paywall.type",
                "reason": "paywall.reason",
                "usage_percent": "paywall.usage_percent",
                "trial_active": "paywall.trial_active",
                "trial_ends_at": "paywall.trial_ends_at",
            },
        },
    ],
    "animations": [
        {
            "id": "streak_burst",
            "trigger": "ui.show_streak_animation == true",
            "effect": "streak flame pulse with count-up",
        },
        {
            "id": "progress_boost",
            "trigger": "ui.show_progress_boost == true",
            "effect": "metric cards lift and highlight updated values",
        },
        {
            "id": "celebration_confetti",
            "trigger": "ui.show_celebration == true",
            "effect": "brief success celebration over hero card",
        },
        {
            "id": "paywall_reveal",
            "trigger": "ui.show_paywall == true",
            "effect": "bottom-sheet reveal for monetization surface",
        },
    ],
    "triggers": [
        {
            "when": "paywall.show == true and paywall.allow_access == false",
            "action": "block_primary_cta_and_route_to_paywall",
        },
        {
            "when": "next_action.action == 'conversation'",
            "action": "route_primary_cta_to_tutor_screen",
        },
        {
            "when": "next_action.action in ['learn', 'review', 'nudge']",
            "action": "route_primary_cta_to_quick_session_screen",
        },
    ],
}


tutor_screen_schema: ScreenSchema = {
    "screen": "tutor",
    "contract_version": "2026-03-21",
    "description": "Real-time tutor experience for regular and streaming responses.",
    "data_sources": [
        {
            "name": "conversation_reply",
            "endpoint": "/conversation/chat",
            "required": False,
            "fields": ["reply", "corrections", "examples", "paywall", "wow"],
        },
        {
            "name": "conversation_stream",
            "endpoint": "/conversation/chat/stream",
            "required": False,
            "fields": [
                "stream_started",
                "correction",
                "token",
                "mid_sentence_feedback",
                "complete",
                "interrupted",
            ],
        },
    ],
    "layout": {
        "shell": "split_pane",
        "sections": [
            {"id": "conversation_thread", "purpose": "Render user and tutor turns."},
            {"id": "feedback_rail", "purpose": "Show live corrections and mid-sentence coaching."},
            {"id": "composer", "purpose": "Support interruption and follow-up input."},
            {"id": "conversion_drawer", "purpose": "Surface wow and paywall moments without breaking flow."},
        ],
    },
    "components": [
        {
            "id": "live_thread",
            "type": "streaming_message_thread",
            "required": True,
            "bindings": {
                "message_chunks": "conversation_stream.token",
                "final_reply": "conversation_reply.reply | conversation_stream.complete.response.reply",
            },
        },
        {
            "id": "correction_rail",
            "type": "live_correction_panel",
            "required": False,
            "bindings": {
                "corrections": "conversation_reply.corrections | conversation_stream.correction",
                "mid_sentence_feedback": "conversation_stream.mid_sentence_feedback.content",
            },
        },
        {
            "id": "wow_card",
            "type": "wow_moment_card",
            "required": False,
            "bindings": {
                "score": "conversation_reply.wow.score | conversation_stream.complete.response.wow.score",
                "qualifies": "conversation_reply.wow.qualifies | conversation_stream.complete.response.wow.qualifies",
            },
        },
        {
            "id": "paywall_drawer",
            "type": "contextual_paywall_drawer",
            "required": False,
            "bindings": {
                "visible": "conversation_reply.paywall.show | conversation_stream.complete.response.paywall.show",
                "type": "conversation_reply.paywall.type | conversation_stream.complete.response.paywall.type",
                "reason": "conversation_reply.paywall.reason | conversation_stream.complete.response.paywall.reason",
                "trial_recommended": "conversation_reply.paywall.trial_recommended | conversation_stream.complete.response.paywall.trial_recommended",
                "upsell_recommended": "conversation_reply.paywall.upsell_recommended | conversation_stream.complete.response.paywall.upsell_recommended",
            },
        },
        {
            "id": "composer",
            "type": "interruptible_composer",
            "required": True,
            "bindings": {
                "stream_id": "conversation_stream.stream_started.stream_id",
            },
        },
    ],
    "animations": [
        {
            "id": "token_stream",
            "trigger": "conversation_stream.token received",
            "effect": "type-on animation at token cadence",
        },
        {
            "id": "correction_flash",
            "trigger": "conversation_stream.correction received",
            "effect": "brief highlight in feedback rail",
        },
        {
            "id": "wow_pop",
            "trigger": "conversation_reply.wow.qualifies == true or conversation_stream.complete.response.wow.qualifies == true",
            "effect": "celebratory pulse around wow card",
        },
        {
            "id": "interrupt_settle",
            "trigger": "conversation_stream.interrupted received",
            "effect": "fade pending tokens and return control to composer",
        },
    ],
    "triggers": [
        {
            "when": "conversation_stream.stream_started received",
            "action": "lock_send_button_and_show_stop_button",
        },
        {
            "when": "user_taps_stop",
            "action": "POST /conversation/chat/stream/{stream_id}/interrupt",
        },
        {
            "when": "paywall.show == true and paywall.type == 'hard_paywall'",
            "action": "freeze_composer_and_open_paywall_drawer",
        },
    ],
}


quick_session_schema: ScreenSchema = {
    "screen": "quick_session",
    "contract_version": "2026-03-21",
    "description": "Low-friction 2-3 minute session contract for learn, review, or nudge flows.",
    "data_sources": [
        {
            "name": "recommendations",
            "endpoint": "/frontend/recommendations",
            "required": True,
            "fields": ["next_action", "retention_actions", "paywall", "ui", "session_config", "emotion_hooks"],
        },
        {
            "name": "dashboard",
            "endpoint": "/frontend/dashboard",
            "required": False,
            "fields": ["progress", "retention", "ui"],
        },
    ],
    "layout": {
        "shell": "focus_stack",
        "sections": [
            {"id": "session_header", "purpose": "Set timebox and emotional framing."},
            {"id": "session_task", "purpose": "Present the single highest-priority task."},
            {"id": "reward_footer", "purpose": "Make progress and streak reward visible."},
        ],
    },
    "components": [
        {
            "id": "countdown_header",
            "type": "session_header",
            "required": True,
            "bindings": {
                "length_minutes": "session_config.session_length",
                "difficulty": "session_config.difficulty",
                "mode": "session_config.mode",
                "encouragement_message": "emotion_hooks.encouragement_message",
            },
        },
        {
            "id": "primary_task_card",
            "type": "single_task_card",
            "required": True,
            "bindings": {
                "action": "next_action.action",
                "target": "next_action.target",
                "reason": "next_action.reason",
                "content_type": "next_action.content_type",
            },
        },
        {
            "id": "retention_prompt",
            "type": "retention_prompt_list",
            "required": False,
            "bindings": {
                "items": "retention_actions",
            },
        },
        {
            "id": "reward_footer",
            "type": "reward_footer",
            "required": True,
            "bindings": {
                "reward_message": "emotion_hooks.reward_message",
                "show_streak_animation": "ui.show_streak_animation",
                "show_progress_boost": "ui.show_progress_boost",
            },
        },
    ],
    "animations": [
        {
            "id": "session_entry",
            "trigger": "screen_loaded",
            "effect": "fast upward reveal of header and task card",
        },
        {
            "id": "reward_footer_glow",
            "trigger": "ui.show_progress_boost == true",
            "effect": "footer glow and numeric increment",
        },
        {
            "id": "streak_ping",
            "trigger": "ui.show_streak_animation == true",
            "effect": "streak badge bounce",
        },
    ],
    "triggers": [
        {
            "when": "paywall.show == true and paywall.allow_access != true",
            "action": "exit_to_paywall_screen",
        },
        {
            "when": "session_config.mode == 'chat'",
            "action": "promote_to_tutor_screen",
        },
        {
            "when": "session_completed",
            "action": "return_to_home_with_reward_state",
        },
    ],
}


progress_screen_schema: ScreenSchema = {
    "screen": "progress",
    "contract_version": "2026-03-21",
    "description": "Progress and retention screen focused on measurable improvement.",
    "data_sources": [
        {
            "name": "dashboard",
            "endpoint": "/frontend/dashboard",
            "required": True,
            "fields": ["progress", "retention", "skills", "weak_areas", "ui", "emotion_hooks"],
        }
    ],
    "layout": {
        "shell": "analytics_stack",
        "sections": [
            {"id": "headline_metrics", "purpose": "Show the four core improvement metrics."},
            {"id": "trend_charts", "purpose": "Expose daily and weekly movement."},
            {"id": "skill_breakdown", "purpose": "Show strengths, weaknesses, and retention state."},
        ],
    },
    "components": [
        {
            "id": "headline_metrics",
            "type": "metric_grid",
            "required": True,
            "bindings": {
                "mastery_percent": "progress.metrics.vocabulary_mastery_percent",
                "accuracy_rate": "progress.metrics.accuracy_rate",
                "response_speed_seconds": "progress.metrics.response_speed_seconds",
                "fluency_score": "progress.metrics.fluency_score",
            },
        },
        {
            "id": "daily_weekly_trends",
            "type": "trend_chart_group",
            "required": True,
            "bindings": {
                "daily": "progress.daily",
                "weekly": "progress.weekly",
                "trends": "progress.trends",
            },
        },
        {
            "id": "skill_breakdown",
            "type": "skill_breakdown_panel",
            "required": True,
            "bindings": {
                "skills": "skills",
                "breakdown": "progress.skill_breakdown",
                "weak_clusters": "weak_areas.clusters",
                "mistakes": "weak_areas.mistakes",
            },
        },
        {
            "id": "retention_badge",
            "type": "retention_badge",
            "required": True,
            "bindings": {
                "state": "retention.state",
                "drop_off_risk": "retention.drop_off_risk",
                "message": "emotion_hooks.encouragement_message",
            },
        },
    ],
    "animations": [
        {
            "id": "metric_count_up",
            "trigger": "screen_loaded",
            "effect": "count-up on headline metrics",
        },
        {
            "id": "chart_highlight",
            "trigger": "ui.show_progress_boost == true",
            "effect": "highlight latest point in trend charts",
        },
    ],
    "triggers": [
        {
            "when": "retention.state in ['at-risk', 'churned']",
            "action": "pin_recovery_cta_above_charts",
        },
        {
            "when": "ui.show_celebration == true",
            "action": "promote_shareable_progress_state",
        },
    ],
}


paywall_screen_schema: ScreenSchema = {
    "screen": "paywall",
    "contract_version": "2026-03-21",
    "description": "Central monetization contract for soft and hard paywall states.",
    "data_sources": [
        {
            "name": "paywall",
            "endpoint": "/frontend/paywall",
            "required": True,
            "fields": [
                "show",
                "type",
                "reason",
                "usage_percent",
                "request_usage_percent",
                "token_usage_percent",
                "trial_active",
                "trial_tier",
                "trial_ends_at",
                "allow_access",
            ],
        },
        {
            "name": "dashboard",
            "endpoint": "/frontend/dashboard",
            "required": False,
            "fields": ["subscription", "emotion_hooks"],
        },
    ],
    "layout": {
        "shell": "modal_or_fullscreen",
        "sections": [
            {"id": "headline", "purpose": "Explain why the paywall is appearing."},
            {"id": "usage_pressure", "purpose": "Visualize usage and urgency."},
            {"id": "offer_stack", "purpose": "Present plan, trial, and upgrade CTA."},
            {"id": "exit_path", "purpose": "Allow continue or block based on access policy."},
        ],
    },
    "components": [
        {
            "id": "headline",
            "type": "paywall_headline",
            "required": True,
            "bindings": {
                "paywall_type": "paywall.type",
                "reason": "paywall.reason",
                "trial_active": "paywall.trial_active",
                "trial_ends_at": "paywall.trial_ends_at",
            },
        },
        {
            "id": "usage_meter",
            "type": "usage_meter",
            "required": True,
            "bindings": {
                "usage_percent": "paywall.usage_percent",
                "request_usage_percent": "paywall.request_usage_percent",
                "token_usage_percent": "paywall.token_usage_percent",
            },
        },
        {
            "id": "plan_comparison",
            "type": "plan_comparison_card",
            "required": True,
            "bindings": {
                "current_tier": "dashboard.subscription.tier",
                "trial_tier": "paywall.trial_tier",
            },
        },
        {
            "id": "upgrade_cta",
            "type": "upgrade_cta_group",
            "required": True,
            "bindings": {
                "allow_access": "paywall.allow_access",
                "reward_message": "dashboard.emotion_hooks.reward_message",
                "urgency_message": "dashboard.emotion_hooks.urgency_message",
            },
        },
    ],
    "animations": [
        {
            "id": "meter_fill",
            "trigger": "screen_loaded",
            "effect": "usage meter fills to current percentage",
        },
        {
            "id": "hard_block_shake",
            "trigger": "paywall.allow_access == false",
            "effect": "locked state emphasis on blocked action",
        },
        {
            "id": "trial_countdown",
            "trigger": "paywall.trial_active == true",
            "effect": "countdown pulse around trial end date",
        },
    ],
    "triggers": [
        {
            "when": "paywall.type == 'soft_paywall' and paywall.allow_access == true",
            "action": "show_continue_option_below_upgrade_cta",
        },
        {
            "when": "paywall.type == 'hard_paywall' or paywall.allow_access == false",
            "action": "require_upgrade_or_trial_before_returning_to_gated_flow",
        },
        {
            "when": "user_taps_upgrade",
            "action": "register_upgrade_click_then_route_to_checkout",
        },
    ],
}


UI_SCREEN_SCHEMAS: dict[str, ScreenSchema] = {
    "home_screen_schema": home_screen_schema,
    "tutor_screen_schema": tutor_screen_schema,
    "quick_session_schema": quick_session_schema,
    "progress_screen_schema": progress_screen_schema,
    "paywall_screen_schema": paywall_screen_schema,
}


def get_ui_schema(name: str) -> ScreenSchema:
    if name not in UI_SCREEN_SCHEMAS:
        raise KeyError(f"Unknown UI schema: {name}")
    return deepcopy(UI_SCREEN_SCHEMAS[name])
