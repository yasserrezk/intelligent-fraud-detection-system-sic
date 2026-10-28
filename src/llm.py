"""LLM side: system prompt, tool definitions, and the OpenRouter call."""
import requests

from . import configure
from .confirmation import request_demo_block, request_demo_delete
from .db import get_card_status, search_transactions

SYSTEM_PROMPT = (
    "You are FraudLens AI, a fraud transaction analysis assistant for the "
    "BankSim1 synthetic payment dataset. "
    "Answer in the user's language. Use tools for database questions and "
    "never invent results. "
    "The isFraud / fraud field is a historical dataset label, not a new AI "
    "prediction or real-time fraud probability. "
    "Customer IDs are demo-only groups from BankSim (not real bank card numbers). "
    "Never claim to affect real bank systems. "
    "Every customer group has a short ID (8 characters) and a full customer ID. "
    "Accept either one in tool calls, and show the short ID to the user. "
    "If the user asks about a customer but gives no ID, ask them to provide "
    "one (you may offer to search transactions to find it). "
    "To block a customer group, call block_demo_card with its ID. To hide "
    "a customer group's transactions, call request_demo_delete with its ID. "
    "Do not ask for confirmation yourself: calling the tool is what "
    "starts the OTP confirmation step, and the application handles it. "
    "Never reveal, guess, or repeat OTP codes. "
    "Never claim an action succeeded before it was executed. "
    "Useful fields: amount, category (e.g. es_food, es_travel), merchant, "
    "age, gender, step (simulation time step)."
)

CARD_ID_DESC = "Full customer ID or short (8-character) demo customer group ID"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_transactions",
            "description": (
                "Search the BankSim1 dataset for transactions. "
                "Use status fraud for fraud-labeled transactions, "
                "legitimate for non-fraud-labeled transactions, "
                "or all for every transaction. Results are ordered "
                "by amount from highest to lowest. "
                "Each row includes category, merchant, age, gender, and step."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["all", "fraud", "legitimate"],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    "min_amount": {"type": "number", "minimum": 0},
                    "card_id": {
                        "type": "string",
                        "description": CARD_ID_DESC + ", if the user specifies one.",
                    },
                },
                "required": ["status", "limit", "min_amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_card_status",
            "description": "Get the current status of a demo customer group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": CARD_ID_DESC}
                },
                "required": ["card_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "block_demo_card",
            "description": (
                "Start blocking a demo customer group in the local SQLite "
                "database. This does NOT block immediately: the application "
                "asks the user for an OTP confirmation first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": CARD_ID_DESC}
                },
                "required": ["card_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_demo_delete",
            "description": (
                "Start hiding (soft-deleting) all transactions of a demo "
                "customer group. This does NOT hide anything immediately: the "
                "application asks the user for an OTP confirmation first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": CARD_ID_DESC}
                },
                "required": ["card_id"],
                "additionalProperties": False,
            },
        },
    },
]

# Read-only tools: the model may run these directly. fn(**args) -> dict
READ_ONLY_TOOLS = {
    "search_transactions": search_transactions,
    "get_card_status": get_card_status,
}

# Risky tools: the model can only START the confirmation step. fn(session, card_id) -> ChatReply
RISKY_TOOLS = {
    "block_demo_card": request_demo_block,
    "request_demo_delete": request_demo_delete,
}


def call_llm(messages, tool_choice="auto", max_tokens=700):
    if not configure.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set (put it in .env).")

    payload = {
        "model": configure.OPENROUTER_MODEL,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": tool_choice,
        "max_tokens": max_tokens,
    }
    if configure.REQUIRE_TOOL_SUPPORT:
        payload["provider"] = {"require_parameters": True}

    res = requests.post(
        configure.OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {configure.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=90,
    )
    res.raise_for_status()
    return res.json()["choices"][0]["message"]


def run_read_only_tool(name, args):
    try:
        return READ_ONLY_TOOLS[name](**args)
    except TypeError:
        return {"error": f"Invalid arguments for {name}"}
