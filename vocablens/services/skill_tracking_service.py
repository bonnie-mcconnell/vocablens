from collections import defaultdict
import sqlite3


class SkillTrackingService:

    def __init__(self, db_path="vocablens.db"):

        self.db_path = db_path

        self.skills = defaultdict(
            lambda: {
                "grammar": 0.5,
                "vocabulary": 0.5,
                "fluency": 0.5,
            }
        )

    def update_from_analysis(self, user_id: int, analysis: dict):

        profile = self.skills[user_id]

        if analysis.get("grammar_mistakes"):
            profile["grammar"] -= 0.02
        else:
            profile["grammar"] += 0.01

        if analysis.get("unknown_words"):
            profile["vocabulary"] -= 0.01
        else:
            profile["vocabulary"] += 0.01

        profile["grammar"] = min(max(profile["grammar"], 0), 1)
        profile["vocabulary"] = min(max(profile["vocabulary"], 0), 1)
        profile["fluency"] = min(max(profile["fluency"], 0), 1)

        self._save_snapshot(user_id)

    def get_skill_profile(self, user_id: int):

        return self.skills[user_id]

    def _save_snapshot(self, user_id):

        skill = self.skills[user_id]

        with sqlite3.connect(self.db_path) as conn:

            for name in ("grammar", "vocabulary", "fluency"):

                conn.execute(
                    """
                    INSERT INTO skill_history (user_id, skill, score)
                    VALUES (?, ?, ?)
                    """,
                    (
                        user_id,
                        name,
                        skill[name],
                    ),
                )
