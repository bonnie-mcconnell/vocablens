from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.domain.errors import ConflictError
from vocablens.services.lesson_generation_service import LessonGenerationService


class FakeLLM:
    def __init__(self, content: dict):
        self.content = content
        self.prompts = []

    async def generate_json_with_usage(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=dict(self.content))


class FakeGraphService:
    async def build_graph(self, user_id: int):
        return {
            "travel": ["hola", "adios", "aeropuerto"],
            "food": ["pan", "agua"],
        }


class FakeLearningEngine:
    async def recommend(self, user_id: int):
        return SimpleNamespace(
            action="learn_new_word",
            target="travel",
            reason="Weak cluster needs reinforcement",
            lesson_difficulty="medium",
            content_type="mixed",
        )


class FakeTemplateRegistryService:
    async def get_lesson_blueprint(self, recommendation, vocab: list[str]):
        return [
            SimpleNamespace(
                template_key="discrimination_choice_v1",
                exercise_type="multiple_choice",
                objective="discrimination",
                difficulty="medium",
                prompt_template="Choose the option that best matches {target}.",
                answer_source="target",
                choice_count=4,
                metadata={},
            ),
            SimpleNamespace(
                template_key="recall_fill_blank_v1",
                exercise_type="fill_blank",
                objective="recall",
                difficulty="medium",
                prompt_template="Fill the blank with {target}.",
                answer_source="target",
                choice_count=None,
                metadata={},
            ),
        ]

    def render_exercises(self, *, blueprint, recommendation, vocab: list[str]):
        return [
            {
                "template_key": "discrimination_choice_v1",
                "type": "multiple_choice",
                "objective": "discrimination",
                "difficulty": "medium",
                "question": "Choose the option that best matches travel.",
                "choices": ["travel", "airport", "hotel", "bread"],
                "answer": "travel",
            },
            {
                "template_key": "recall_fill_blank_v1",
                "type": "fill_blank",
                "objective": "recall",
                "difficulty": "medium",
                "question": "Fill the blank with travel.",
                "answer": "travel",
            },
        ]

    def merge_generated_exercises(self, *, blueprint, fallback_exercises: list[dict], generated_exercises: list[dict]):
        return [
            {
                **fallback_exercises[0],
                **generated_exercises[0],
                "template_key": "discrimination_choice_v1",
                "objective": "discrimination",
                "difficulty": "medium",
            },
            dict(fallback_exercises[1]),
        ]


class FakeContentQualityGateService:
    def __init__(self, *, reject: bool = False):
        self.reject = reject
        self.calls = []

    async def validate_generated_lesson(self, *, user_id: int, reference_id: str, lesson: dict, source: str = "lesson_generation_service"):
        self.calls.append((user_id, reference_id, source, dict(lesson)))
        return {
            "status": "rejected" if self.reject else "passed",
            "score": 0.2 if self.reject else 0.96,
            "violations": [{"code": "weak_distractors", "severity": "warning"}] if self.reject else [],
            "artifact_summary": {"exercise_count": len(lesson.get("exercises") or [])},
        }

    def ensure_passed(self, report: dict):
        if report["status"] == "rejected":
            raise ConflictError("Session content failed quality validation")


def test_lesson_generation_service_runs_canonical_content_gate():
    llm = FakeLLM(
        {
            "exercises": [
                {"type": "fill_blank", "question": "Complete: I ___ home.", "answer": "go"},
                {
                    "type": "multiple_choice",
                    "question": "Choose the travel word.",
                    "choices": ["airport", "bread", "water"],
                    "answer": "airport",
                },
            ]
        }
    )
    content_gate = FakeContentQualityGateService()
    service = LessonGenerationService(
        llm,
        FakeGraphService(),
        FakeLearningEngine(),
        content_gate,
        FakeTemplateRegistryService(),
    )

    lesson = run_async(service.generate_lesson(1))

    assert lesson["next_action"]["target"] == "travel"
    assert lesson["exercises"][0]["template_key"] == "discrimination_choice_v1"
    assert lesson["exercises"][1]["template_key"] == "recall_fill_blank_v1"
    assert content_gate.calls
    assert content_gate.calls[0][2] == "lesson_generation_service"
    assert "Vocabulary:" in llm.prompts[0]


def test_lesson_generation_service_rejects_bad_generated_content():
    llm = FakeLLM(
        {
            "exercises": [
                {
                    "type": "multiple_choice",
                    "question": "Pick one.",
                    "choices": ["airport", "airport"],
                    "answer": "airport",
                }
            ]
        }
    )
    service = LessonGenerationService(
        llm,
        FakeGraphService(),
        FakeLearningEngine(),
        FakeContentQualityGateService(reject=True),
        FakeTemplateRegistryService(),
    )

    try:
        run_async(service.generate_lesson(1))
        assert False, "expected lesson generation content conflict"
    except ConflictError as exc:
        assert "quality validation" in str(exc)
