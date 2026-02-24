# ChatBot SaaS — CrewAI Edition v2.0

Multi-tenant AI chatbot SaaS. One codebase, infinite clients. Plug into any website — tiles, fashion, restaurants, hospitals, real estate — the bot learns from whatever is on that website automatically.

---

## What Makes This Different

| Feature | This Project |
|---------|-------------|
| AI | 4 specialist agents (RAG Search, Sales, Comparison, Support) |
| Model fallback | 3 Groq models → Ollama — bot never goes down |
| Memory | Persistent: ChromaDB (semantic) + SQLite (structured) |
| Multi-tenant | Per-client API keys, vector DB collections, crawl schedules |
| Product cards | Dynamic — extracted from crawled website, not hardcoded |
| Generic | Zero hardcoded content — works for any business type |

---

## Project Structure

```
YourProject/
│
├── ai/                          ← model chain manager
│   ├── __init__.py              ← required — must exist (empty file)
│   └── groq_router.py           ← auto-switches: Primary → F1 → F2 → Ollama
│
├── agents/                      ← specialist AI agents
│   ├── __init__.py
│   ├── agents.py                ← 4 agents (RAG Search, Sales, Comparison, Support)
│   └── orchestrator.py          ← detects intent, routes to right agent
│
├── api/                         ← FastAPI backend
│   ├── __init__.py
│   ├── main.py                  ← app startup, scheduler, /status endpoint
│   ├── chat.py                  ← chat endpoint, dynamic product cards
│   ├── clients.py               ← client registration, crawl triggers
│   └── webhook.py               ← Shopify / WooCommerce / custom webhooks
│
├── config/
│   ├── __init__.py
│   ├── settings.py              ← all settings incl. 3-model Groq chain
│   └── database.py              ← 5 tables: clients, sessions, page_hashes,
│                                   chat_messages, user_memories
│
├── crawler/
│   ├── __init__.py
│   ├── scraper.py               ← crawls any website (respects robots.txt)
│   └── change_detector.py       ← MD5 hashing — only re-crawls changed pages
│
├── memory/
│   ├── __init__.py
│   └── memory_manager.py        ← ChromaDB (semantic) + SQLite (preferences)
│
├── vector_db/
│   ├── __init__.py
│   └── chroma_manager.py        ← per-client ChromaDB collections (RAG)
│
├── widget/
│   └── chatbot.js               ← embeddable widget v10.1
│                                   agent badge, dynamic cards, rotating chips
│
├── test_website/                ← TileVista demo (6 HTML pages)
│   ├── index.html
│   ├── floor-tiles.html
│   ├── wall-tiles.html
│   ├── bathroom-tiles.html
│   ├── products.html
│   └── about.html
│
├── chroma_storage/              ← auto-created: RAG vectors (per client)
├── chroma_memory/               ← auto-created: agent memory (per user)
├── chatbot_saas.db              ← auto-created: SQLite database
│
├── .env                         ← your keys (copy from .env.example)
├── .env.example
├── requirements.txt
├── test_api.py                  ← register client, get embed script
├── check_rag.py                 ← diagnose + reindex RAG
└── test_page.html               ← test page with chatbot widget embedded
```

---

## Model Chain (Never Goes Down)

`ai/groq_router.py` is a singleton shared by all 4 agents. Same Groq API key, 3 models tried in order:

```
Primary    → llama-3.1-8b-instant       14,400 req/day   fast
Fallback 1 → llama-3.3-70b-versatile    1,000  req/day   better quality
Fallback 2 → llama-4-scout-17b          1,000  req/day   multimodal
Last resort → Ollama                    unlimited         local, free forever
```

Total free Groq quota: **16,400 requests/day** before Ollama kicks in.

Switching is automatic — on 429 error OR when daily counter hits limit, silently moves to next model. Counters reset at midnight UTC. Check live status anytime:

```
GET http://localhost:8000/status
```

---

## 4 Specialist Agents

| Agent | Triggers | Does |
|-------|----------|------|
| RAG Search | "show me", "find", "do you have", "available" | Searches crawled website, presents top 3 results |
| Sales | "recommend", "suggest", "best for", "help me choose" | Recommends best product for the customer's need |
| Comparison | "vs", "compare", "difference", "which is better" | Side-by-side table comparison |
| Customer Support | "delivery", "warranty", "return", "store", "contact" | Handles all support queries |

---

## Dual Memory

**ChromaDB** (`./chroma_memory/`) — semantic memory. Stores conversation turns as vectors. Finds relevant past chats on each new message.

**SQLite** (`user_memories` table) — structured memory. Auto-extracts budget, room type, style from messages. Personalizes future recommendations.

Both scoped per `client_id + user_id` — each business's users are fully isolated.

---

## Setup

### 1. Create .env file

```
GROQ_API_KEY=your_groq_api_key_here

GROQ_MODEL_PRIMARY=llama-3.1-8b-instant
GROQ_LIMIT_PRIMARY=14400

GROQ_MODEL_FALLBACK1=llama-3.3-70b-versatile
GROQ_LIMIT_FALLBACK1=1000

GROQ_MODEL_FALLBACK2=llama-4-scout-17b-e3-instruct
GROQ_LIMIT_FALLBACK2=1000

OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b

DATABASE_URL=sqlite+aiosqlite:///./chatbot_saas.db
CHROMA_PERSIST_DIR=./chroma_storage
MEMORY_PERSIST_DIR=./chroma_memory
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Terminal 1 — Serve test website

Run from **project root** (not inside test_website/):

```bash
python -m http.server 3000
```

Visit: `http://localhost:3000/test_page.html`

### 4. Terminal 2 — Start API server

```bash
python -m api.main
```

### 5. Register client + get embed script

```bash
python test_api.py
```

### 6. Paste embed script into your HTML

```html
<script
  src="http://localhost:8000/widget/chatbot.js"
  data-client-id="YOUR_CLIENT_ID"
  data-api-key="YOUR_API_KEY"
  defer>
</script>
```

### 7. If bot doesn't know products — reindex

```bash
python check_rag.py --reindex
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/clients` | Register new client → CLIENT_ID, API_KEY, embed script |
| GET | `/api/clients/{id}` | Client info + embed script |
| POST | `/api/clients/{id}/sync` | Manually trigger smart re-crawl |
| GET | `/api/chat/config/{client_id}` | Widget config — bot name, color, greeting |
| POST | `/api/chat/{client_id}` | Send message → response + agent_used + model_used + cards |
| GET | `/api/chat/history/{session_id}` | Full persistent chat history |
| GET | `/api/memory/{client_id}/{user_id}` | View stored user preferences |
| DELETE | `/api/memory/{client_id}/{user_id}` | Clear user memory |
| POST | `/api/webhook/{id}/shopify` | Shopify product webhooks |
| POST | `/api/webhook/{id}/woocommerce` | WooCommerce webhooks |
| POST | `/api/webhook/{id}/custom` | Generic webhook |
| GET | `/health` | Health check |
| GET | `/status` | Live model chain status + daily usage |
| GET | `/docs` | Swagger UI |

---

## Troubleshooting

**`No module named 'ai'`**
Create `ai/__init__.py` as an empty file in the project root. The `ai/` folder must contain it to be importable as a Python package.

**Bot says "Something went wrong"**
Check API server terminal for error logs. Most common:
- Wrong CLIENT_ID or API_KEY in test_page.html — re-run `python test_api.py`
- API server not running
- Groq API key invalid

**Bot doesn't know about products**
Run `python check_rag.py --reindex` to re-crawl and rebuild the vector index.

**Product card links broken (404)**
Start the HTTP server from the project root, not from inside `test_website/`. The URL builder in `chat.py` automatically prefixes relative paths with the client's `website_url`.

**Special characters in product names**
Already fixed — `chat.py` cleans all titles character by character before returning cards.

**Model chain not switching**
Check `/status`. If all 3 Groq models are exhausted and Ollama isn't running, bot returns empty. Either wait for midnight UTC reset or start Ollama locally with `ollama serve`.
