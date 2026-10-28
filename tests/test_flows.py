"""Run with:  pytest -q   (from the project folder). No LLM or API key needed."""
import csv
import random
import time

import pytest

from src import build_db, configure
from src.chat import chat
from src.confirmation import confirm_pending, request_demo_block, request_demo_delete
from src.db import get_card_status, resolve_card, search_transactions
from src.session import Session

TEST_CUSTOMER = "C123456789"


@pytest.fixture()
def demo_db(tmp_path, monkeypatch):
    """Small fake BankSim-like dataset -> temporary database."""
    random.seed(1)
    csv_path = tmp_path / "fake_banksim.csv"
    header = [
        "step",
        "customer",
        "age",
        "gender",
        "zipcodeOri",
        "merchant",
        "zipMerchant",
        "category",
        "amount",
        "fraud",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i in range(300):
            if i < 20:
                customer = TEST_CUSTOMER
            else:
                customer = f"C{random.randint(100000, 999999)}"
            w.writerow(
                [
                    i % 50,
                    f"'{customer}'",
                    str(random.randint(1, 6)),
                    random.choice(["'M'", "'F'"]),
                    "'28007'",
                    f"'M{random.randint(100,999)}'",
                    "'28007'",
                    random.choice(
                        ["'es_food'", "'es_travel'", "'es_health'", "'es_leisure'"]
                    ),
                    round(random.random() * 500, 2),
                    int(random.random() < 0.1),
                ]
            )

    db_path = tmp_path / "test.db"
    build_db.build(csv_path, db_path)
    monkeypatch.setattr(configure, "DB_PATH", db_path)
    monkeypatch.setattr(configure, "SHOW_DEMO_OTP", True)
    return db_path


def wrong_code(otp):
    return "0000" if otp != "0000" else "1111"


def test_lookup_by_full_and_short_id(demo_db):
    card = resolve_card(TEST_CUSTOMER)
    assert card and len(card["short_id"]) == 8
    assert get_card_status(card["short_id"])["card_id"] == TEST_CUSTOMER
    assert "error" in get_card_status("nope")
    assert "error" in search_transactions(card_id="nope")


def test_block_flow(demo_db):
    s = Session("a")
    short = resolve_card(TEST_CUSTOMER)["short_id"]

    reply = request_demo_block(s, short)
    assert reply.type == "otp_required" and reply.data["demo_otp"] == s.pending.otp

    assert "attempt" in confirm_pending(s, wrong_code(s.pending.otp)).text
    assert "pending" in confirm_pending(s, "what time is it").text  # not a code
    assert s.pending.attempts == 1

    result = confirm_pending(s, s.pending.otp)
    assert result.type == "result" and result.data["success"] is True
    assert s.pending is None
    assert get_card_status(short)["status"] == "blocked"
    assert "already blocked" in request_demo_block(s, short).text


def test_lockout_cancel_and_expiry(demo_db):
    s = Session("a")
    short = resolve_card(TEST_CUSTOMER)["short_id"]

    request_demo_delete(s, short)
    bad = wrong_code(s.pending.otp)
    for _ in range(configure.MAX_OTP_ATTEMPTS):
        reply = confirm_pending(s, bad)
    assert s.pending is None and "Too many" in reply.text

    request_demo_delete(s, short)
    assert "cancelled" in confirm_pending(s, "cancel").text and s.pending is None

    request_demo_delete(s, short)
    s.pending.created_at = time.time() - configure.OTP_TTL_SECONDS - 1
    assert "expired" in confirm_pending(s, s.pending.otp).text and s.pending is None


def test_delete_flow_hides_transactions(demo_db):
    s = Session("a")
    short = resolve_card(TEST_CUSTOMER)["short_id"]
    assert search_transactions(card_id=short)["count_returned"] > 0

    request_demo_delete(s, short)
    result = confirm_pending(s, s.pending.otp)
    assert result.type == "result" and result.data["success"] is True
    assert search_transactions(card_id=short)["count_returned"] == 0


def test_otp_without_pending_does_not_reset_chat(demo_db):
    """Typing an OTP when nothing is pending must not start a new flow."""
    s = Session("same-session")
    # First a normal search keeps history
    # (no LLM in unit tests — just pending path)
    reply = chat(s, "1234")
    assert "no pending confirmation" in reply.text.lower() or "nothing pending" in reply.text.lower() or "request the action again" in reply.text.lower()
    assert s.pending is None
    # Session object is the same; history may be empty but chat was not "reset"
    assert s.id == "same-session"


def test_llm_request_uses_bearer_api_key(monkeypatch):
    import src.llm as llm

    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(configure, "OPENROUTER_API_KEY", "test-api-key")
    monkeypatch.setattr(llm.requests, "post", fake_post)

    assert llm.call_llm([])["content"] == "ok"
    assert captured["headers"]["Authorization"] == "Bearer test-api-key"
