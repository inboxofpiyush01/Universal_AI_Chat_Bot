# api/clients.py
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from config.database import get_db, Client
from crawler.scraper import WebScraper
from crawler.change_detector import ChangeDetector
from vector_db.chroma_manager import vector_db
from config.settings import settings

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Models ───────────────────────────────────────────────────────────────────

class CreateClientRequest(BaseModel):
    name: str                                   # Business name
    website_url: str                            # Their website
    ai_provider: str = "claude"                 # "claude" or "openai"
    plan: str = "starter"                       # starter / growth / pro
    bot_name: str = "Assistant"
    bot_greeting: str = "Hi! How can I help you today?"
    bot_color: str = "#0066CC"


class ClientResponse(BaseModel):
    id: str
    name: str
    website_url: str
    api_key: str                                # Used in the JS widget
    ai_provider: str
    plan: str
    bot_name: str
    bot_greeting: str
    bot_color: str
    crawl_status: str
    total_pages_crawled: int
    embed_script: str                           # Ready-to-paste HTML snippet
    created_at: datetime


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/clients", response_model=ClientResponse)
async def create_client(
    request: CreateClientRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new client website.
    
    After creation:
    1. Client gets a unique API key
    2. Website crawl starts automatically in background
    3. Client gets an embed script to paste on their website
    """
    # Create client record
    client = Client(
        name=request.name,
        website_url=str(request.website_url),
        ai_provider=request.ai_provider,
        plan=request.plan,
        bot_name=request.bot_name,
        bot_greeting=request.bot_greeting,
        bot_color=request.bot_color,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)

    # Start initial crawl in background (non-blocking)
    background_tasks.add_task(run_initial_crawl, client.id, client.website_url, db)

    logger.info(f"✅ New client created: {client.name} ({client.id})")

    return _build_client_response(client)


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(client_id: str, db: AsyncSession = Depends(get_db)):
    """Get client details including embed script."""
    client = await _get_client(client_id, db)
    return _build_client_response(client)


@router.post("/clients/{client_id}/sync")
async def manual_sync(
    client_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger a website re-crawl.
    Client can click 'Sync' button in their dashboard.
    Only crawls CHANGED pages (smart detection).
    """
    client = await _get_client(client_id, db)

    if client.crawl_status == "running":
        return {"status": "already_running", "message": "Crawl already in progress"}

    background_tasks.add_task(run_smart_crawl, client.id, client.website_url, db)
    return {"status": "started", "message": "Sync started. This may take a few minutes."}


@router.get("/clients/{client_id}/stats")
async def get_stats(client_id: str, db: AsyncSession = Depends(get_db)):
    """Get client statistics - pages crawled, vector DB size, etc."""
    client = await _get_client(client_id, db)
    vector_stats = vector_db.get_stats(client_id)

    return {
        "client_id": client_id,
        "business_name": client.name,
        "website_url": client.website_url,
        "crawl_status": client.crawl_status,
        "total_pages_crawled": client.total_pages_crawled,
        "last_crawled_at": client.last_crawled_at,
        "vector_db_chunks": vector_stats.get("total_chunks", 0),
        "plan": client.plan,
        "ai_provider": client.ai_provider,
    }


@router.put("/clients/{client_id}/provider")
async def update_ai_provider(
    client_id: str,
    provider: str,
    db: AsyncSession = Depends(get_db)
):
    """Switch AI provider for a client (claude ↔ openai)."""
    if provider not in ["claude", "openai"]:
        raise HTTPException(status_code=400, detail="Provider must be 'claude' or 'openai'")

    client = await _get_client(client_id, db)
    client.ai_provider = provider
    await db.commit()

    return {"status": "updated", "ai_provider": provider}


# ─── Background Tasks ─────────────────────────────────────────────────────────

async def run_initial_crawl(client_id: str, website_url: str, db: AsyncSession):
    """
    Full initial crawl of client website.
    Crawls ALL pages and stores in vector DB.
    Called once when client first registers.
    """
    logger.info(f"🕷️ Starting initial crawl for client {client_id}: {website_url}")

    # Update crawl status
    await _update_crawl_status(client_id, "running", db)

    try:
        scraper = WebScraper(website_url)
        pages = scraper.crawl()

        if pages:
            vector_db.add_pages(client_id, pages)
            await _update_crawl_status(client_id, "done", db, len(pages))
            logger.info(f"✅ Initial crawl done: {len(pages)} pages for client {client_id}")
        else:
            await _update_crawl_status(client_id, "failed", db)
            logger.error(f"❌ No pages found for client {client_id}")

    except Exception as e:
        await _update_crawl_status(client_id, "failed", db)
        logger.error(f"❌ Initial crawl failed for client {client_id}: {e}")


async def run_smart_crawl(client_id: str, website_url: str, db: AsyncSession):
    """
    Smart crawl — only re-crawls pages that have CHANGED.
    Uses MD5 hash comparison for efficiency.
    Called on schedule or manual trigger.
    """
    logger.info(f"🔍 Starting smart crawl for client {client_id}")
    await _update_crawl_status(client_id, "running", db)

    try:
        detector = ChangeDetector(db)
        scraper = WebScraper(website_url)

        # Get list of all pages (light crawl - just URLs)
        all_urls = scraper._extract_links("", website_url)
        all_urls.insert(0, website_url)  # Include homepage

        changed_pages = []
        for url in all_urls[:settings.MAX_PAGES_PER_SITE]:
            has_changed, new_hash = await detector.has_page_changed(client_id, url)

            if has_changed:
                page_data = scraper._scrape_page(url)
                if page_data:
                    changed_pages.append(page_data)
                    await detector.update_hash(client_id, url, new_hash)
            else:
                await detector.mark_checked(client_id, url)

        if changed_pages:
            vector_db.add_pages(client_id, changed_pages)
            logger.info(f"✅ Smart crawl: {len(changed_pages)} changed pages updated")
        else:
            logger.info(f"✅ Smart crawl: No changes detected for client {client_id}")

        await _update_crawl_status(client_id, "done", db)

    except Exception as e:
        await _update_crawl_status(client_id, "failed", db)
        logger.error(f"❌ Smart crawl failed for client {client_id}: {e}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_client(client_id: str, db: AsyncSession) -> Client:
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def _update_crawl_status(
    client_id: str,
    status: str,
    db: AsyncSession,
    pages_count: int = None
):
    """Update crawl status in DB."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client:
        client.crawl_status = status
        client.last_crawled_at = datetime.utcnow()
        if pages_count is not None:
            client.total_pages_crawled = pages_count
        await db.commit()


def _build_client_response(client: Client) -> ClientResponse:
    """Build response with embed script."""
    server_url = f"http://localhost:{settings.APP_PORT}"

    # This is the ONE LINE clients paste on their website!
    embed_script = f"""<script src="{server_url}/widget/chatbot.js" data-client-id="{client.id}" data-api-key="{client.api_key}" defer></script>"""

    return ClientResponse(
        id=client.id,
        name=client.name,
        website_url=client.website_url,
        api_key=client.api_key,
        ai_provider=client.ai_provider,
        plan=client.plan,
        bot_name=client.bot_name,
        bot_greeting=client.bot_greeting,
        bot_color=client.bot_color,
        crawl_status=client.crawl_status,
        total_pages_crawled=client.total_pages_crawled,
        embed_script=embed_script,
        created_at=client.created_at,
    )
