class LearningGraphService:

    def __init__(self, repository):
        self.repo = repository

    def build_user_graph(self, user_id):

        items = self.repo.list_all(user_id)

        graph = {}

        for item in items:

            cluster = item.semantic_cluster or "general"

            if cluster not in graph:
                graph[cluster] = []

            graph[cluster].append(item.source_text)

        return graph

    def recommend_next_cluster(self, user_id):

        graph = self.build_user_graph(user_id)

        smallest_cluster = None
        smallest_size = 9999

        for cluster, words in graph.items():

            if len(words) < smallest_size:
                smallest_size = len(words)
                smallest_cluster = cluster

        return smallest_cluster