"""Database access: lookups, searches and the (confirmed-only) write actions.

Schema is built from BankSim1 (customer = card group).
"""
import sqlite3
from contextlib import contextmanager

import pandas as pd

from . import configure


@contextmanager
def db():
    """Open a connection, commit on success, roll back on error, ALWAYS close."""
    if not configure.DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found at {configure.DB_PATH}. Run build_db.py first."
        )
    conn = sqlite3.connect(configure.DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def resolve_card(ref):
    """Look up a customer group by full ID or short ID. Returns a dict or None."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    ref = ref.strip().strip("'\"")

    with db() as conn:
        row = conn.execute(
            "SELECT card_id, short_id, status FROM cards "
            "WHERE card_id = ? OR short_id = ?",
            (ref, ref.lower()),
        ).fetchone()

    if row is None:
        return None
    return {"card_id": row[0], "short_id": row[1], "status": row[2]}


def search_transactions(status="all", limit=10, min_amount=0, card_id=None):
    if status not in ["all", "fraud", "legitimate"]:
        return {"error": "status must be all, fraud, or legitimate"}

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        return {"error": "limit must be an integer between 1 and 100"}

    try:
        min_amount = float(min_amount)
    except (TypeError, ValueError):
        return {"error": "min_amount must be a number"}

    if min_amount < 0:
        return {"error": "min_amount cannot be negative"}

    query = """
        SELECT TransactionID, step, TransactionAmt, isFraud,
               category, merchant, age, gender, card_short_id
        FROM transactions
        WHERE TransactionAmt >= ?
          AND is_deleted = 0
    """
    params = [min_amount]

    if status == "fraud":
        query += " AND isFraud = 1"
    elif status == "legitimate":
        query += " AND isFraud = 0"

    if card_id is not None:
        card = resolve_card(card_id)
        if card is None:
            return {"error": "Demo customer group not found"}
        query += " AND card_id = ?"
        params.append(card["card_id"])

    query += " ORDER BY TransactionAmt DESC LIMIT ?"
    params.append(limit)

    with db() as conn:
        result = pd.read_sql_query(query, conn, params=params)

    return {
        "count_returned": len(result),
        "transactions": result.to_dict(orient="records"),
    }


def get_card_status(card_id):
    card = resolve_card(card_id)
    if card is None:
        return {"error": "Demo customer group not found"}
    return card


def block_demo_card(card_id):
    """Block a customer group (full card_id). Call ONLY after OTP confirmation."""
    if not isinstance(card_id, str) or not card_id.strip():
        return {"success": False, "message": "Invalid card_id"}

    with db() as conn:
        cursor = conn.execute(
            "UPDATE cards SET status = 'blocked' "
            "WHERE card_id = ? AND status = 'active'",
            (card_id,),
        )

        if cursor.rowcount == 1:
            conn.execute(
                "INSERT INTO audit_log (action, card_id, affected_rows) "
                "VALUES (?, ?, ?)",
                ("BLOCK_CARD", card_id, 1),
            )
            return {
                "success": True,
                "card_id": card_id,
                "status": "blocked",
                "message": "Demo customer group blocked successfully.",
            }

        row = conn.execute(
            "SELECT status FROM cards WHERE card_id = ?", (card_id,)
        ).fetchone()

    if row is None:
        return {"success": False, "message": "Demo customer group not found."}

    return {
        "success": False,
        "card_id": card_id,
        "status": row[0],
        "message": "Demo customer group is already blocked.",
    }


def delete_demo_transactions(card_id, confirmed=False):
    """Soft delete: rows are flagged as hidden, never removed."""
    if not isinstance(card_id, str) or not card_id.strip():
        return {"success": False, "message": "Invalid card_id"}

    if confirmed is not True:
        return {
            "success": False,
            "confirmation_required": True,
            "message": "Explicit confirmation is required.",
        }

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        card = conn.execute(
            "SELECT status FROM cards WHERE card_id = ?", (card_id,)
        ).fetchone()

        if card is None:
            conn.rollback()
            return {"success": False, "message": "Demo customer group not found."}

        count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE card_id = ? AND is_deleted = 0",
            (card_id,),
        ).fetchone()[0]

        if count == 0:
            conn.rollback()
            return {
                "success": True,
                "affected_rows": 0,
                "message": "No active demo transactions to hide.",
            }

        conn.execute(
            "UPDATE transactions SET is_deleted = 1 "
            "WHERE card_id = ? AND is_deleted = 0",
            (card_id,),
        )
        conn.execute(
            "INSERT INTO audit_log (action, card_id, affected_rows) "
            "VALUES (?, ?, ?)",
            ("SOFT_DELETE_TRANSACTIONS", card_id, count),
        )

    return {
        "success": True,
        "card_id": card_id,
        "affected_rows": count,
        "message": "Demo transactions hidden successfully; records retained.",
    }
