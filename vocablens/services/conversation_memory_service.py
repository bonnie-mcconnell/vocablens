from collections import defaultdict
from typing import List, Dict


class ConversationMemoryService:
    """
    Stores short-term conversation history
    for each user.

    Maintains a rolling window of recent conversation turns.
    """

    def __init__(self):
        self.memory: Dict[int, List[str]] = defaultdict(list)

    # ---------------------------------------------------------
    # Add full conversation turn
    # ---------------------------------------------------------

    def store_turn(self, user_id: int, user_message: str, assistant_reply: str):

        self.memory[user_id].append(f"Student: {user_message}")
        self.memory[user_id].append(f"Tutor: {assistant_reply}")

        # keep memory small
        if len(self.memory[user_id]) > 12:
            self.memory[user_id] = self.memory[user_id][-12:]

    # ---------------------------------------------------------
    # Get conversation context
    # ---------------------------------------------------------

    def get_recent_context(self, user_id: int) -> str:

        history = self.memory[user_id]

        return "\n".join(history)