"""Central settings. Values come from environment variables / the .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# --- Database -------------------------------------------------------------
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "data" / "fraudlens_demo.db"))
TRANSACTION_CSV = os.environ.get(
    "TRANSACTION_CSV", ""
)  # BankSim CSV path for build_db.py

# --- LLM (OpenRouter) -----------------------------------------------------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# "openrouter/free" picks a random free model, and not all of them handle tool
# calls well. Pin a specific tool-capable model here for stable behaviour.
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/free")
# Only route to providers that support "tools". Set to false if you get
# a "no endpoints found" error.
REQUIRE_TOOL_SUPPORT = _bool("REQUIRE_TOOL_SUPPORT", True)

# --- Confirmation (OTP) ---------------------------------------------------
# Demo mode: the OTP is shown in the reply because no SMS is sent.
# NEVER leave this on in a real deployment.
SHOW_DEMO_OTP = _bool("SHOW_DEMO_OTP", True)
OTP_LENGTH = 4
MAX_OTP_ATTEMPTS = 3
OTP_TTL_SECONDS = 300
CANCEL_WORDS = {"cancel", "إلغاء", "الغاء"}

# --- Chat -----------------------------------------------------------------
MAX_HISTORY_MESSAGES = 12  # keep even (user/assistant pairs)
MAX_TOOL_ROUNDS = 5
MAX_MESSAGE_CHARS = 2000
