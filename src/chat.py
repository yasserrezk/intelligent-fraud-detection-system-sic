"""The chatbot brain: chat(session, message) -> ChatReply."""

import json

import requests

from . import configure
from .confirmation import confirm_pending
from .llm import (
    READ_ONLY_TOOLS,
    RISKY_TOOLS,
    SYSTEM_PROMPT,
    call_llm,
    run_read_only_tool,
)
from .session import ChatReply, Session


def _remember(session: Session, user_text: str, assistant_text: str) -> None:
    session.history.append({"role": "user", "content": user_text})
    session.history.append({"role": "assistant", "content": assistant_text})
    del session.history[: -configure.MAX_HISTORY_MESSAGES]


def _looks_like_otp(text: str) -> bool:
    t = text.strip()
    return t.isascii() and t.isdigit() and len(t) == configure.OTP_LENGTH


def chat(session: Session, user_question: str) -> ChatReply:
    session.touch()
    question = (user_question or "").strip()

    if not question:
        return ChatReply("text", "Please type a question.")
    if len(question) > configure.MAX_MESSAGE_CHARS:
        return ChatReply(
            "text", f"Message too long (max {configure.MAX_MESSAGE_CHARS} characters)."
        )

    # 1. A pending confirmation takes priority over everything else.
    #    The same session_id must be sent by the client for the OTP to work.
    #    (The code the user types is never stored in the history.)
    if session.pending is not None:
        reply = confirm_pending(session, question)
        _remember(session, "[user replied to the confirmation step]", reply.text)
        return reply

    # If the user types a pure OTP-looking code but nothing is pending
    # (e.g. server restarted and in-memory sessions were lost), explain
    # instead of treating it as a normal question / starting a "new" flow.
    if _looks_like_otp(question):
        return ChatReply(
            "text",
            "There is no pending confirmation for this chat. "
            "If you just requested a block/hide action, the session may have "
            "expired or the server restarted — please request the action again "
            "in this same chat (do not open a new chat).",
        )

    if question.lower() in configure.CANCEL_WORDS:
        return ChatReply("text", "There is nothing pending to cancel.")

    # 2. Normal conversation with tool calling
    conversation = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + session.history
        + [{"role": "user", "content": question}]
    )

    for _ in range(configure.MAX_TOOL_ROUNDS):
        try:
            message = call_llm(conversation)
        except requests.RequestException as e:
            return ChatReply("text", f"The language model request failed: {e}")
        except RuntimeError as e:  # e.g. missing API key
            return ChatReply("text", str(e))

        calls = message.get("tool_calls") or []

        if not calls:
            text = message.get("content") or "No response returned."
            _remember(session, question, text)
            return ChatReply("text", text)

        conversation.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": calls,
            }
        )

        for call in calls:
            name = call["function"]["name"]

            try:
                args = json.loads(call["function"]["arguments"])
                if not isinstance(args, dict):
                    raise TypeError
            except (TypeError, json.JSONDecodeError):
                return ChatReply(
                    "text",
                    "Could not understand the tool arguments. No action was taken.",
                )

            # Risky actions: only START the confirmation step, never execute.
            if name in RISKY_TOOLS:
                reply = RISKY_TOOLS[name](session, args.get("card_id"))
                # Keep the OTP out of the history.
                note = (
                    f"Confirmation requested for customer group {session.pending.short_id}."
                    if session.pending is not None
                    else reply.text
                )
                _remember(session, question, note)
                return reply

            if name not in READ_ONLY_TOOLS:
                return ChatReply("text", f"The tool {name} is not allowed.")

            result = run_read_only_tool(name, args)
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    return ChatReply(
        "text", "Reached the maximum number of tool calls. Try a simpler question."
    )
