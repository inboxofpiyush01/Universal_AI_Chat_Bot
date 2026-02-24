# api/main.py
import logging
import os
import sys
from pathlib import Path

# ── Ensure project root is on sys.path ───────────────────────────────────────
# Fixes "No module named 'ai'" (and similar) when running `python -m api.main`
# Works regardless of where you launch from.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api.chat import router as chat_router
from api.clients import router as clients_router, run_smart_crawl
from api.webhook import router as webhook_router
from config.database import init_db, AsyncSessionLocal, Client
from config.settings import settings
from sqlalchemy import select

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ChatBot SaaS - CrewAI Edition starting up...")
    logger.info("🤖 Agents: RAG Search | Sales | Comparison | Customer Support")
    logger.info("🧠 Memory: ChromaDB (semantic) + SQLite (structured)")
    logger.info(f"🔗 Model chain: {settings.GROQ_MODEL_PRIMARY} → {settings.GROQ_MODEL_FALLBACK1} → {settings.GROQ_MODEL_FALLBACK2} → Ollama")

    await init_db()

    scheduler.add_job(
        scheduled_crawl_all_clients,
        "interval",
        hours=settings.CRAWL_INTERVAL_HOURS,
        id="smart_crawl_all",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"⏰ Scheduler started — crawling every {settings.CRAWL_INTERVAL_HOURS} hours")

    yield

    scheduler.shutdown()
    logger.info("👋 ChatBot SaaS shutting down...")


app = FastAPI(
    title="ChatBot SaaS API - CrewAI Edition",
    description="Multi-tenant AI chatbot with 4 specialist agents and persistent memory.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_WIDGET_DIR = _ROOT / "widget"
os.makedirs(_WIDGET_DIR, exist_ok=True)
app.mount("/widget", StaticFiles(directory=str(_WIDGET_DIR)), name="widget")

app.include_router(chat_router,    prefix="/api", tags=["Chat"])
app.include_router(clients_router, prefix="/api", tags=["Clients"])
app.include_router(webhook_router, prefix="/api", tags=["Webhooks"])


@app.get("/")
async def root():
    from ai.groq_router import groq_router
    s = groq_router.status()
    return {
        "service":      "ChatBot SaaS - CrewAI Edition",
        "version":      "2.0.0",
        "status":       "running",
        "agents":       ["RAG Search Agent", "Sales Agent", "Comparison Agent", "Customer Support Agent"],
        "memory":       ["ChromaDB (semantic)", "SQLite (structured)"],
        "active_model": s["active_model"],
        "docs":         "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "agents": 4, "memory": "dual"}


@app.get("/status")
async def status():
    """Live model chain status — which model is active + daily usage counts."""
    from ai.groq_router import groq_router
    s = groq_router.status()
    return {
        "service":      "ChatBot SaaS - CrewAI Edition",
        "active_model": s["active_model"],
        "active_label": s["active_label"],
        "reset_date":   s["reset_date"],
        "model_chain":  s["models"],
    }


async def scheduled_crawl_all_clients():
    logger.info("⏰ Running scheduled smart crawl for all clients...")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Client).where(Client.is_active == True, Client.crawl_status != "running")
        )
        clients = result.scalars().all()
        logger.info(f"Found {len(clients)} active clients to crawl")
        for client in clients:
            try:
                await run_smart_crawl(client.id, client.website_url, db)
            except Exception as e:
                logger.error(f"Scheduled crawl failed for {client.id}: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
