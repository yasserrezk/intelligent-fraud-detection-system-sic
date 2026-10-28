"""Per-user state. One Session per conversation: never share these between users."""
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Pending:
    """A risky action waiting for the user's OTP."""
    action: str            # "block" | "delete"
    card_id: str
    short_id: str
    otp: str
    count: Optional[int] = None
    attempts: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    id: str
    history: list = field(default_factory=list)     # [{"role", "content"}, ...]
    pending: Optional[Pending] = None
    last_active: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_active = time.time()

    def reset(self) -> None:
        """Clear conversation memory and any pending confirmation."""
        self.history.clear()
        self.pending = None
        self.touch()


@dataclass
class ChatReply:
    """What chat() returns. Easy to turn into JSON for the API (dataclasses.asdict).

    type:
      "text"         normal answer, errors, wrong-code messages, cancellations
      "otp_required" an action is waiting for the OTP (see data)
      "result"       an action was executed (data = the DB result)
    """
    type: str
    text: str
    data: Optional[dict] = None
