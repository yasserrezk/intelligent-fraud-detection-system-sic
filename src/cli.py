"""Terminal chat for testing the bot WITHOUT the API:  python cli.py"""

from .chat import chat
from .session import Session

session = Session(id="cli")
print("FraudLens AI - type 'exit' to quit, 'reset' to clear memory.\n")

while True:
    text = input("You: ").strip()
    if text.lower() in {"exit", "quit"}:
        break
    if text.lower() == "reset":
        session.reset()
        print("Memory cleared.\n")
        continue
    reply = chat(session, text)
    print(f"\nFraudLens AI [{reply.type}]:", reply.text, "\n")
