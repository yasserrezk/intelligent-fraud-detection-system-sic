"""Build the demo SQLite database from the BankSim1 dataset.

Expected CSV (from https://www.kaggle.com/datasets/ealaxi/banksim1):
  bs140513_032310.csv

Columns used:
  step, customer, age, gender, merchant, category, amount, fraud

Run once, then keep the .db file:

    python build_db.py --csv path/to/bs140513_032310.csv
    python build_db.py --csv bs140513_032310.csv --out data/fraudlens_demo.db

WARNING: this REPLACES the transactions/cards/audit_log tables. Re-run it to
reset the demo data (blocked cards, hidden transactions, audit log).
"""
import argparse
import hashlib
import sqlite3
from pathlib import Path

import pandas as pd

from . import configure

# BankSim1 columns we need
COLUMNS = [
    "step",
    "customer",
    "age",
    "gender",
    "merchant",
    "category",
    "amount",
    "fraud",
]


def _clean_quoted(series: pd.Series) -> pd.Series:
    """BankSim often stores values like 'C123456' with surrounding quotes."""
    return (
        series.astype("string")
        .fillna("UNKNOWN")
        .str.strip()
        .str.strip("'\"")
    )


def build(csv_path, db_path):
    csv_path, db_path = Path(csv_path), Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path, usecols=COLUMNS)
    print("Dataset loaded. Shape:", df.shape)
    print(f"Fraud percentage: {df['fraud'].mean() * 100:.2f}%")

    # Customer ID is the natural "card group" in BankSim
    df["card_id"] = _clean_quoted(df["customer"])
    df["merchant"] = _clean_quoted(df["merchant"])
    df["category"] = _clean_quoted(df["category"])
    df["age"] = _clean_quoted(df["age"])
    df["gender"] = _clean_quoted(df["gender"])

    # Short, easy-to-type ID (first 8 hex chars of SHA-1 of the full customer ID)
    short_map = {
        cid: hashlib.sha1(cid.encode()).hexdigest()[:8]
        for cid in df["card_id"].unique()
    }
    if len(set(short_map.values())) != len(short_map):
        raise RuntimeError("short ID collision: increase the hash length")

    df["card_short_id"] = df["card_id"].map(short_map)
    df["is_deleted"] = 0

    # Keep a stable transaction identifier and map names used by the rest of the app
    df["TransactionID"] = range(1, len(df) + 1)
    df["TransactionAmt"] = df["amount"].astype(float)
    df["isFraud"] = df["fraud"].astype(int)
    # category plays the role ProductCD had in IEEE-CIS
    df["ProductCD"] = df["category"]

    out_cols = [
        "TransactionID",
        "step",
        "TransactionAmt",
        "isFraud",
        "ProductCD",
        "category",
        "merchant",
        "age",
        "gender",
        "card_id",
        "card_short_id",
        "is_deleted",
    ]

    conn = sqlite3.connect(db_path)
    try:
        df[out_cols].to_sql(
            "transactions", conn, if_exists="replace", index=False, chunksize=5000
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transactions_card ON transactions (card_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transactions_fraud ON transactions (isFraud)"
        )

        conn.execute("DROP TABLE IF EXISTS cards")
        conn.execute(
            """
            CREATE TABLE cards (
                card_id  TEXT PRIMARY KEY,
                short_id TEXT NOT NULL UNIQUE,
                status   TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        pd.DataFrame(
            {
                "card_id": list(short_map.keys()),
                "short_id": list(short_map.values()),
                "status": "active",
            }
        ).to_sql("cards", conn, if_exists="append", index=False)

        conn.execute("DROP TABLE IF EXISTS audit_log")
        conn.execute(
            """
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                card_id TEXT NOT NULL,
                affected_rows INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

        n_tx = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        n_cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    finally:
        conn.close()

    print(f"Database written to {db_path}")
    print(f"Transactions: {n_tx} | Customer groups: {n_cards}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--csv",
        default=configure.TRANSACTION_CSV,
        help="BankSim CSV (e.g. bs140513_032310.csv)",
    )
    parser.add_argument("--out", default=str(configure.DB_PATH), help="output .db path")
    args = parser.parse_args()

    if not args.csv:
        parser.error("pass --csv or set TRANSACTION_CSV in .env")
    build(args.csv, args.out)


if __name__ == "__main__":
    main()
