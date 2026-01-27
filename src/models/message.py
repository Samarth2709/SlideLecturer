"""Chat message data model."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MessageRole(Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class ChatMessage:
    """Represents a chat message in the conversation."""

    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    slide_index: Optional[int] = None  # Which slide this message relates to

    @property
    def is_user(self) -> bool:
        """Check if message is from user."""
        return self.role == MessageRole.USER

    @property
    def is_assistant(self) -> bool:
        """Check if message is from assistant."""
        return self.role == MessageRole.ASSISTANT
