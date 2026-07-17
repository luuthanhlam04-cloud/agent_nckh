"""
conversation_memory.py - Qu\u1ea3n l\u00fd B\u1ed9 nh\u1edb Ng\u1eafn h\u1ea1n H\u1ed9i tho\u1ea1i (Short-term Conversation Memory)
===========================================================================================
Cơ chế:
  - Sliding Window (C\u1eeda s\u1ed5 tr\u01b0\u1ee3t) l\u01b0u \u0111\u00fang N c\u1eb7p h\u1ecfi-\u0111\u00e1p g\u1ea7n nh\u1ea5t.
  - D\u00f9ng collections.deque(maxlen=N): t\u1ef1 \u0111\u1ed9ng pop ph\u1ea7n t\u1eed c\u0169 khi \u0111\u1ea7y, kh\u00f4ng c\u1ea7n logic x\u00f3a th\u1ee7 c\u00f4ng.
  - Thread-safe cho thao t\u00e1c append/pop \u0111\u01a1n.

Spec (agent.md B\u01b0\u1edbc 7.1):
  "Duy tr\u00ec m\u1ea3ng Dictionary ch\u1ee9a \u0111\u00fang l\u1ecbch s\u1eed 5 c\u1eb7p chat g\u1ea7n nh\u1ea5t.
   Khi xu\u1ea5t hi\u1ec7n c\u00e2u chat th\u1ee9 6, c\u00e2u th\u1ee9 1 t\u1ef1 \u0111\u1ed9ng b\u1ecb Pop/Delete kh\u1ecfi RAM."
"""

import logging
from collections import deque
from typing import Optional

logger = logging.getLogger("ConversationMemory")

SLIDING_WINDOW_SIZE = 5


class ConversationMemory:
    """
    Qu\u1ea3n l\u00fd b\u1ed9 nh\u1edb ng\u1eafn h\u1ea1n h\u1ed9i tho\u1ea1i tr\u00ean RAM b\u1eb1ng c\u01a1 ch\u1ebf C\u1eeda s\u1ed5 tr\u01b0\u1ee3t.

    Dependency Injection: \u0111\u01b0\u1ee3c kh\u1edfi t\u1ea1o v\u00e0 inject t\u1eeb main.py.
    Instance \u0111\u01b0\u1ee3c chia s\u1ebb gi\u1eefa ReActOrchestrator v\u00e0 MemoryConsolidator.
    """

    def __init__(self, max_size: int = SLIDING_WINDOW_SIZE) -> None:
        self._window: deque = deque(maxlen=max_size)
        self._last_response: str = ""   # Private; tr\u1ee3 l\u1eddi cu\u1ed1i cho l\u1ec7nh "copy c\u00e2u v\u1eeba r\u1ed3i"

    @property
    def last_response(self) -> str:
        """Tr\u00e2u c\u1ea7u cu\u1ed1i c\u00f9ng c\u1ee7a Agent (read-only t\u1eeb b\u00ean ngo\u00e0i)."""
        return self._last_response

    def add(self, user_input: str, agent_response: str) -> None:
        """Th\u00eam m\u1ed9t c\u1eb7p Q&A m\u1edbi v\u00e0o c\u1eeda s\u1ed5 tr\u01b0\u1ee3t."""
        self._window.append({
            "role_user": user_input,
            "role_agent": agent_response,
        })
        self._last_response = agent_response

    def get_context_string(self) -> str:
        """
        K\u1ebft xu\u1ea5t l\u1ecbch s\u1eed h\u1ed9i tho\u1ea1i th\u00e0nh chu\u1ed7i v\u0103n b\u1ea3n \u0111\u1ec3 nh\u00fang v\u00e0o prompt.

        Returns:
            Chu\u1ed7i l\u1ecbch s\u1eed \u0111\u1ecbnh d\u1ea1ng r\u00f5 r\u00e0ng, ho\u1eb7c chu\u1ed7i r\u1ed7ng n\u1ebfu ch\u01b0a c\u00f3 h\u1ed9i tho\u1ea1i.
        """
        if not self._window:
            return ""
        lines = ["=== L\u1ecbch s\u1eed h\u1ed9i tho\u1ea1i g\u1ea7n nh\u1ea5t ==="]
        for i, pair in enumerate(self._window, 1):
            lines.append(f"[{i}] Ng\u01b0\u1eddi d\u00f9ng: {pair['role_user']}")
            agent_text = pair["role_agent"]
            agent_preview = agent_text[:200]
            suffix = "..." if len(agent_text) > 200 else ""
            lines.append(f"    Tr\u1ee3 l\u00fd: {agent_preview}{suffix}")
        return "\n".join(lines)

    def clear(self) -> None:
        """X\u00f3a to\u00e0n b\u1ed9 b\u1ed9 nh\u1edb ng\u1eafn h\u1ea1n."""
        self._window.clear()
        self._last_response = ""

    def __len__(self) -> int:
        return len(self._window)
