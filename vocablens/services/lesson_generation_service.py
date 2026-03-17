from vocablens.providers.llm.base import LLMProvider
from vocablens.services.learning_graph_service import LearningGraphService


class LessonGenerationService:

    def __init__(
        self,
        llm: LLMProvider,
        graph_service: LearningGraphService,
    ):
        self.llm = llm
        self.graph_service = graph_service

    def generate_lesson(self, user_id: int):

        graph = self.graph_service.build_graph(user_id)

        vocab = []

        for cluster_words in graph.values():
            vocab.extend(cluster_words[:5])

        vocab = vocab[:20]

        prompt = f"""
Create a language learning lesson.

Vocabulary:
{vocab}

Return JSON:

{{
 "exercises":[
   {{
     "type":"fill_blank",
     "question":"",
     "answer":""
   }},
   {{
     "type":"multiple_choice",
     "question":"",
     "choices":[],
     "answer":""
   }}
 ]
}}
"""

        return self.llm.generate_json_with_usage(prompt).content
