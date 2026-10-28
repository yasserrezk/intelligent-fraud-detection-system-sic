# FraudLens AI

Chatbot over the **BankSim1** synthetic payment dataset (LLM tool calling).
Risky actions (block a customer group / hide its transactions) need a per-session OTP.
Everything is a demo: `fraud` / `isFraud` is a historical label and customer IDs are synthetic.

Dataset: https://www.kaggle.com/datasets/ealaxi/banksim1
Main file: `bs140513_032310.csv`

## Structure
```
fraudlens/
├── src/
│   ├── configure.py  settings (from .env)
│   ├── session.py    Session (history + pending OTP) and ChatReply
│   ├── db.py         queries + confirmed-only write actions
│   ├── confirmation.py OTP flow
│   ├── llm.py        system prompt, tools, OpenRouter call
│   ├── chat.py       chat(session, message) -> ChatReply
│   ├── build_db.py   builds the SQLite DB from BankSim CSV
│   └── cli.py        terminal chat
├── main.py           FastAPI app
├── frontend/         browser UI
├── tests/            pytest (no LLM / key needed)
└── data/             the .db file lives here
```

## Setup
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Set OPENROUTER_API_KEY in .env to enable LLM chat.
```

## Database (BankSim1)
Download the dataset from Kaggle and put the CSV next to the project (or anywhere):

```bash
python -m src.build_db --csv path/to/bs140513_032310.csv
# or
python -m src.build_db --csv path/to/bs140513_032310.csv --out data/fraudlens_demo.db
```

Re-running resets the demo data (blocked customers, hidden transactions, audit log).

Mapped fields:
| BankSim column | App field        | Notes                          |
|----------------|------------------|--------------------------------|
| customer       | card_id          | full customer group ID         |
| (hash)         | card_short_id    | 8-char short ID for the UI     |
| amount         | TransactionAmt   |                                |
| fraud          | isFraud          | 0/1 label                      |
| category       | category / ProductCD | e.g. es_food, es_travel   |
| merchant       | merchant         |                                |
| step           | step             | simulation time step           |

## Try it
```bash
pytest -q
python -m src.cli
uvicorn main:app --reload --port 8000
# in another terminal, serve frontend/ at an allowed CORS origin
python -m http.server 5500 --directory frontend
# open http://localhost:5500 and use the API at http://localhost:8000
```

## OTP / same-chat rule (important)
- The OTP is tied to the **same `session_id`**.
- Do **not** click "New chat" while a confirmation is pending.
- If the server restarts (`uvicorn --reload`), in-memory sessions are lost — request the action again in the **same** chat window.
- The UI modal and the main input both send the code with the current `session_id`; neither creates a new session.

## Notes for the API
- One `Session` per user/conversation (dict keyed by `session_id`).
  Never share one Session between users: it holds the pending OTP and the memory.
- `chat(session, message)` returns a `ChatReply(type, text, data)`;
  types: `text`, `otp_required`, `result`.
- With `SHOW_DEMO_OTP=false` the OTP is never in the reply. Implement
  `deliver_otp` in `confirmation.py` first.
