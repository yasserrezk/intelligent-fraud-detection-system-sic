import threading
import time
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src import configure
from src.chat import chat
from src.session import Session

app = FastAPI(title="FraudLens AI")

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://localhost:3000",
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

SESSION_TTL_SECONDS = 30 * 60
MAX_SESSIONS = 1000

sessions: dict[str, Session] = {}
sessions_lock = threading.Lock()


def purge_old_sessions() -> None:
    now = time.time()

    for sid, s in list(sessions.items()):
        if now - s.last_active > SESSION_TTL_SECONDS:
            del sessions[sid]

    if len(sessions) > MAX_SESSIONS:
        by_age = sorted(sessions.items(), key=lambda item: item[1].last_active)
        for sid, _ in by_age[: len(sessions) - MAX_SESSIONS]:
            del sessions[sid]


def get_session(session_id: str) -> Session:
    """Return the same Session for a given session_id.

    Critical for OTP: the client must keep sending the same session_id
    from the first request that started the pending action until the
    code is confirmed. Creating a new session_id mid-flow looks like
    "the chat restarted".
    """
    with sessions_lock:
        purge_old_sessions()
        if session_id not in sessions:
            sessions[session_id] = Session(id=session_id)
        return sessions[session_id]


# --- Models ---------------------------------------------------------------
class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(max_length=configure.MAX_MESSAGE_CHARS)


class ResetRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    session = get_session(req.session_id)
    reply = chat(session, req.message)
    return asdict(reply)


@app.post("/api/reset")
def reset_endpoint(req: ResetRequest):
    with sessions_lock:
        sessions.pop(req.session_id, None)
    return {"status": "reset"}