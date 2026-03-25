from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.exercise_template_registry_service import ExerciseTemplateRegistryService


class FakeExerciseTemplateRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_active(self, *, objectives=None, difficulty=None, limit: int = 20):
        rows = [row for row in self.rows if row.status == "active"]
        if objectives:
            rows = [row for row in rows if row.objective in objectives]
        if difficulty:
            rows = [row for row in rows if row.difficulty == difficulty]
        return rows[:limit]


class FakeUOW:
    def __init__(self, rows):
        self.exercise_templates = FakeExerciseTemplateRepo(rows)
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


def test_exercise_template_registry_service_returns_blueprint_and_rendered_exercises():
    rows = [
        SimpleNamespace(
            template_key="recall_fill_blank_v1",
            exercise_type="fill_blank",
            objective="recall",
            difficulty="medium",
            status="active",
            prompt_template="Fill the blank with {target}.",
            answer_source="target",
            choice_count=None,
            template_metadata={},
        ),
        SimpleNamespace(
            template_key="discrimination_choice_v1",
            exercise_type="multiple_choice",
            objective="discrimination",
            difficulty="medium",
            status="active",
            prompt_template="Choose the best match for {target}.",
            answer_source="target",
            choice_count=4,
            template_metadata={},
        ),
    ]
    service = ExerciseTemplateRegistryService(lambda: FakeUOW(rows))
    recommendation = SimpleNamespace(action="learn_new_word", target="travel", lesson_difficulty="medium")

    blueprint = run_async(service.get_lesson_blueprint(recommendation, ["travel", "airport", "hotel", "bread"]))
    exercises = service.render_exercises(
        blueprint=blueprint,
        recommendation=recommendation,
        vocab=["travel", "airport", "hotel", "bread"],
    )

    assert [item.template_key for item in blueprint] == ["discrimination_choice_v1", "recall_fill_blank_v1"]
    assert exercises[0]["template_key"] == "discrimination_choice_v1"
    assert exercises[0]["difficulty"] == "medium"
    assert "travel" in exercises[0]["choices"]
    assert exercises[1]["template_key"] == "recall_fill_blank_v1"
    assert exercises[1]["answer"] == "travel"
