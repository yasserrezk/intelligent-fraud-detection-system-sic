import secrets
import time

from . import configure
from .db import block_demo_card, delete_demo_transactions, db, resolve_card
from .session import ChatReply, Pending, Session


def deliver_otp(code: str) -> None:
    """Hook for a real delivery channel (SMS, email, authenticator...)."""
    raise NotImplementedError("Plug in an SMS/email provider here.")


def _new_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(configure.OTP_LENGTH))


def _start_pending(session: Session, action: str, card: dict, count=None) -> None:
    session.pending = Pending(
        action=action,
        card_id=card["card_id"],
        short_id=card["short_id"],
        otp=_new_otp(),
        count=count,
    )
    if not configure.SHOW_DEMO_OTP:
        deliver_otp(session.pending.otp)


def _otp_required_reply(session: Session) -> ChatReply:
    p = session.pending
    what = (
        "Block this customer group"
        if p.action == "block"
        else f"Hide {p.count} transaction(s) of this customer group"
    )
    lines = [
        "⚠️ OTP verification required",
        "",
        f"Action: {what}",
        f"Customer group: {p.short_id}  ({p.card_id})",
        "",
    ]
    if configure.SHOW_DEMO_OTP:
        lines.append(f"Demo mode: no SMS is sent. Your OTP is {p.otp}.")
    else:
        lines.append("Enter the code that was sent to you.")
    lines.append(
        f'Type the {configure.OTP_LENGTH}-digit code to confirm, or "cancel" to cancel.'
    )

    data = {
        "action": p.action,
        "card_id": p.card_id,
        "short_id": p.short_id,
        "count": p.count,
        "otp_length": configure.OTP_LENGTH,
    }
    if configure.SHOW_DEMO_OTP:
        data["demo_otp"] = p.otp  # never sent when SHOW_DEMO_OTP is False

    return ChatReply("otp_required", "\n".join(lines), data)


def request_demo_block(session: Session, card_ref) -> ChatReply:
    card = resolve_card(card_ref)

    if card is None:
        return ChatReply(
            "text",
            "Not blocked: the ID does not match any customer group (full or short ID).",
        )
    if card["status"] != "active":
        return ChatReply(
            "text", "This customer group is already blocked; no changes were made."
        )

    _start_pending(session, "block", card)
    return _otp_required_reply(session)


def request_demo_delete(session: Session, card_ref) -> ChatReply:
    card = resolve_card(card_ref)

    if card is None:
        return ChatReply("text", "Demo customer group not found.")

    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE card_id = ? AND is_deleted = 0",
            (card["card_id"],),
        ).fetchone()[0]

    if count == 0:
        return ChatReply("text", "There are no visible transactions to hide.")

    _start_pending(session, "delete", card, count=count)
    return _otp_required_reply(session)


def confirm_pending(session: Session, user_reply: str) -> ChatReply:
    """Handle the user's reply while an action is pending for this session.

    The same Session object must be used for the whole OTP flow. If the
    server process restarted, pending is lost and this returns a clear message
    instead of starting a new unrelated conversation.
    """
    p = session.pending

    if p is None:
        return ChatReply("text", "There is nothing pending.")

    reply = user_reply.strip()

    if reply.lower() in configure.CANCEL_WORDS:
        action = "Block" if p.action == "block" else "Hide"
        session.pending = None
        return ChatReply(
            "text",
            f"{action} request cancelled. No changes were made.",
            {"cancelled": True},
        )

    if time.time() - p.created_at > configure.OTP_TTL_SECONDS:
        session.pending = None
        return ChatReply(
            "text",
            "The confirmation code expired. No changes were made.",
            {"expired": True},
        )

    looks_like_code = (
        reply.isascii() and reply.isdigit() and len(reply) == configure.OTP_LENGTH
    )
    if not looks_like_code:
        # Keep pending alive; do NOT clear history or start a new chat.
        return ChatReply(
            "text",
            f"A confirmation is pending for customer group {p.short_id}. "
            f'Enter the {configure.OTP_LENGTH}-digit code, or type "cancel".',
            {"still_pending": True},
        )

    if not secrets.compare_digest(reply, p.otp):
        p.attempts += 1
        left = configure.MAX_OTP_ATTEMPTS - p.attempts
        if left <= 0:
            session.pending = None
            return ChatReply(
                "text",
                "Too many wrong codes. The request was cancelled; no changes were made.",
                {"lockout": True},
            )
        return ChatReply(
            "text",
            f'Wrong code. {left} attempt(s) left. Type "cancel" to cancel.',
            {"wrong_code": True, "attempts_left": left},
        )

    # Correct code: clear the pending state BEFORE executing (one-time use)
    session.pending = None

    if p.action == "block":
        result = block_demo_card(p.card_id)
    else:
        result = delete_demo_transactions(p.card_id, confirmed=True)

    return ChatReply("result", result.get("message", "Done."), result)
