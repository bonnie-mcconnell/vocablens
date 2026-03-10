from collections import defaultdict
from typing import List, Dict


class ConversationMemoryService:
    """
    Stores short-term conversation history
    for each user.
    """

    def __init__(self):
        self.memory: Dict[int, List[str]] = defaultdict(list)

    def add_message(self, user_id: int, message: str):

        self.memory[user_id].append(message)

        # keep memory small
        if len(self.memory[user_id]) > 10:
            self.memory[user_id] = self.memory[user_id][-10:]

    def get_context(self, user_id: int) -> List[str]:

        return self.memory[user_id]