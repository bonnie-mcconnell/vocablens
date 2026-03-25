from __future__ import annotations


PROMOTION_FIXTURES = {
    ("fill_blank", "recall"): [
        {"target": "travel", "vocab_word": "travel"},
        {"target": "airport", "vocab_word": "airport"},
    ],
    ("multiple_choice", "discrimination"): [
        {"target": "travel", "vocab_word": "travel"},
        {"target": "grammar", "vocab_word": "grammar"},
    ],
    ("fill_blank", "correction"): [
        {"target": "past tense", "vocab_word": "went"},
    ],
    ("multiple_choice", "reinforcement"): [
        {"target": "travel", "vocab_word": "travel"},
    ],
    ("fill_blank", "production"): [
        {"target": "travel", "vocab_word": "travel"},
    ],
}
