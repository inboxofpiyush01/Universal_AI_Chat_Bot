# api/chat.py
import logging
import asyncio
import unicodedata
import uuid
import re
from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from datetime import datetime

from config.database import get_db, Client, ChatSession, ChatMessage
from vector_db.chroma_manager import vector_db
from agents.orchestrator import OrchestratorAgent
from memory.memory_manager import memory_manager
from ai.groq_router import groq_router

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Pydantic models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:      str
    session_id:   Optional[str] = None
    user_id:      Optional[str] = None
    user_pincode: Optional[str] = None
    user_contact: Optional[str] = None


class ChatResponse(BaseModel):
    response:           str
    session_id:         str
    agent_used:         str = ""
    intent:             str = ""
    model_used:         str = ""
    suggested_products: List[Dict] = []
    show_dealer_prompt: bool = False
    show_human_handoff: bool = False
    sources:            List[str] = []


class ClientConfigResponse(BaseModel):
    client_id:  str
    bot_name:   str
    bot_color:  str = "#e91e8c"
    bot_avatar: str = ""
    welcome_msg: str = ""



# Orchestrator singleton
orchestrator = OrchestratorAgent()

# In-memory conversation cache
chat_sessions: Dict[str, List[Dict]] = {}


@router.post("/chat/{client_id}")
async def chat(
    client_id: str,
    request: ChatRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:

    # ── Validate client + API key ─────────────────────────────────────────────
    client = await _validate_api_key(client_id, x_api_key, db)

    session_id = request.session_id or str(uuid.uuid4())
    user_id    = request.user_id or f"anon_{session_id[:8]}"

    if session_id not in chat_sessions:
        chat_sessions[session_id] = []
        await _create_chat_session(client_id, session_id, user_id, db)

    conversation_history = chat_sessions[session_id]

    # ── PARALLEL: RAG search + memory load — run simultaneously ──────────────
    # These 3 are fully independent so no reason to run them one after another.
    # asyncio.gather fires all 3 at once and waits for all to finish.
    context_chunks, preferences, past_convos = await asyncio.gather(
        asyncio.to_thread(
            vector_db.search,
            client_id=client_id,
            query=request.message,
            n_results=3
        ),
        memory_manager.load_preferences(db, client_id, user_id),
        asyncio.to_thread(
            memory_manager.recall_relevant,
            client_id, user_id, request.message, 3
        ),
    )

    memory_ctx = memory_manager.build_memory_context(past_convos, preferences)

    # ── Orchestrator: route to correct agent + call LLM ──────────────────────
    client_config = {
        "name":        client.name,
        "bot_name":    client.bot_name,
        "website_url": client.website_url,
    }

    result = await asyncio.to_thread(
        orchestrator.run,
        query=request.message,
        context_chunks=context_chunks,
        client_config=client_config,
        memory_context=memory_ctx,
        conversation_history=conversation_history,
    )

    ai_response = result["response"]
    agent_used  = result["agent_used"]
    intent      = result["intent"]
    model_used  = result.get("model_used", "")

    # ── Update in-memory history ──────────────────────────────────────────────
    conversation_history.append({"role": "user",      "content": request.message})
    conversation_history.append({"role": "assistant", "content": ai_response})
    if len(conversation_history) > 20:
        chat_sessions[session_id] = conversation_history[-20:]

    # ── FIRE AND FORGET: all DB/memory saves happen after response is returned ─
    # User gets the response immediately. Saves happen in background.
    asyncio.create_task(_save_all(
        db=db,
        client_id=client_id,
        session_id=session_id,
        user_id=user_id,
        user_msg=request.message,
        ai_response=ai_response,
        agent_used=agent_used,
        intent=intent,
    ))

    # ── Product cards ─────────────────────────────────────────────────────────
    suggested_products = _get_product_cards(request.message, context_chunks, client.website_url)

    dealer_kw  = ["buy", "purchase", "where", "store", "dealer", "near", "location", "shop"]
    handoff_kw = ["speak to human", "talk to person", "agent", "representative"]
    sources    = list(set([c["url"] for c in context_chunks if c.get("url")]))

    return ChatResponse(
        response=ai_response,
        session_id=session_id,
        agent_used=agent_used,
        intent=intent,
        model_used=model_used,
        suggested_products=suggested_products,
        show_dealer_prompt=any(kw in request.message.lower() for kw in dealer_kw) and not request.user_pincode,
        show_human_handoff=any(kw in request.message.lower() for kw in handoff_kw),
        sources=sources[:3],
    )


# ── Streaming chat endpoint ──────────────────────────────────────────────────

@router.post("/chat/{client_id}/stream")
async def chat_stream(
    client_id: str,
    request: ChatRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
):
    """
    Streaming version of the chat endpoint.
    Sends tokens as Server-Sent Events (SSE) so the widget can
    display words appearing in real-time instead of waiting for full response.
    """
    client = await _validate_api_key(client_id, x_api_key, db)

    session_id = request.session_id or str(uuid.uuid4())
    user_id    = request.user_id or f"anon_{session_id[:8]}"

    if session_id not in chat_sessions:
        chat_sessions[session_id] = []
        await _create_chat_session(client_id, session_id, user_id, db)

    conversation_history = chat_sessions[session_id]

    # Parallel pre-fetch (same as non-streaming endpoint)
    context_chunks, preferences, past_convos = await asyncio.gather(
        asyncio.to_thread(vector_db.search, client_id=client_id, query=request.message, n_results=3),
        memory_manager.load_preferences(db, client_id, user_id),
        asyncio.to_thread(memory_manager.recall_relevant, client_id, user_id, request.message, 3),
    )

    memory_ctx    = memory_manager.build_memory_context(past_convos, preferences)
    client_config = {"name": client.name, "bot_name": client.bot_name, "website_url": client.website_url}

    # Detect intent + pick agent (no LLM call — keyword only)
    intent     = orchestrator.detect_intent(request.message)
    agent_name = orchestrator._intent_to_agent_name(intent)

    # Build the messages the agent would send
    agent_obj  = orchestrator._get_agent(intent)
    system_msg, history_msgs = agent_obj.build_messages(
        query=request.message,
        context_chunks=context_chunks,
        client_config=client_config,
        memory_context=memory_ctx,
        conversation_history=conversation_history,
    )
    msgs = [{"role": "system", "content": system_msg}] + history_msgs

    # Product cards (fast — no LLM)
    suggested_products = _get_product_cards(request.message, context_chunks, client.website_url)
    sources = list(set([c["url"] for c in context_chunks if c.get("url")]))

    async def event_stream():
        import json
        full_response = []

        # ── Meta event — sent immediately so widget can create bubble ────────
        meta = {
            "type":               "meta",
            "session_id":         session_id,
            "agent_used":         agent_name,
            "intent":             intent,
            "model_used":         groq_router.active_model_name(),
            "suggested_products": suggested_products,
            "sources":            sources[:3],
        }
        yield f"data: {json.dumps(meta)}\n\n"

        # ── Queue-based streaming — one thread runs the whole generator ──────
        # Avoids per-chunk run_in_executor overhead (which caused slowness).
        # Thread puts chunks into queue; async loop reads from it instantly.
        _DONE = object()
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _producer():
            """Runs in a single background thread — feeds all chunks into queue."""
            try:
                max_tokens = getattr(agent_obj, "_stream_max_tokens", 200)
                for chunk in groq_router.stream(msgs, max_tokens=max_tokens, temperature=0.4, caller=agent_obj.name):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as ex:
                logger.error(f"Stream producer error: {ex}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        loop.run_in_executor(None, _producer)

        # ── Consume queue — yield each token immediately as it arrives ───────
        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=45.0)
                if item is _DONE:
                    break
                # Special REPLACE marker — means streamed text had mojibake.
                # Tell widget to replace the entire bubble with cleaned version.
                if isinstance(item, str) and item.startswith("\x00REPLACE\x00"):
                    clean_text = item[len("\x00REPLACE\x00"):]
                    full_response = [clean_text]   # replace buffered text too
                    yield f"data: {json.dumps({'type': 'replace', 'text': clean_text})}\n\n"
                else:
                    full_response.append(item)
                    yield f"data: {json.dumps({'type': 'token', 'text': item})}\n\n"
        except asyncio.TimeoutError:
            logger.warning("Stream timeout — no token received in 45s")
            yield f"data: {json.dumps({'type': 'token', 'text': 'Sorry, the AI is taking too long right now. This usually means Groq is rate-limited. Please wait a moment and try again.'})}\n\n"
        except Exception as e:
            logger.error(f"Stream consumer error: {e}")
            yield f"data: {json.dumps({'type': 'token', 'text': ' (stream error, please retry)'})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

        # ── Background save after response fully sent ─────────────────────────
        full_text = "".join(full_response)
        conversation_history.append({"role": "user",      "content": request.message})
        conversation_history.append({"role": "assistant", "content": full_text})
        if len(conversation_history) > 20:
            chat_sessions[session_id] = conversation_history[-20:]

        asyncio.create_task(_save_all(
            db=db, client_id=client_id, session_id=session_id, user_id=user_id,
            user_msg=request.message, ai_response=full_text,
            agent_used=agent_name, intent=intent,
        ))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )



# ── Background save — runs after response is already sent to user ─────────────

async def _save_all(
    db: AsyncSession,
    client_id: str,
    session_id: str,
    user_id: str,
    user_msg: str,
    ai_response: str,
    agent_used: str,
    intent: str,
):
    """
    Fire-and-forget: saves chat history + memory AFTER the response is returned.
    User never waits for these writes.
    """
    try:
        now = datetime.utcnow()
        # Save both chat turns in one commit
        await db.execute(
            text("INSERT INTO chat_messages (id,client_id,session_id,user_id,role,content,agent_used,intent,created_at) VALUES (:id,:cid,:sid,:uid,:role,:content,:agent,:intent,:now)"),
            {"id": str(uuid.uuid4()), "cid": client_id, "sid": session_id, "uid": user_id,
             "role": "user", "content": user_msg, "agent": "", "intent": intent, "now": now}
        )
        await db.execute(
            text("INSERT INTO chat_messages (id,client_id,session_id,user_id,role,content,agent_used,intent,created_at) VALUES (:id,:cid,:sid,:uid,:role,:content,:agent,:intent,:now)"),
            {"id": str(uuid.uuid4()), "cid": client_id, "sid": session_id, "uid": user_id,
             "role": "assistant", "content": ai_response, "agent": agent_used, "intent": intent, "now": now}
        )
        await db.commit()

        # Extract + save preferences
        await memory_manager.extract_and_save(db, client_id, user_id, user_msg)

        # Store in ChromaDB memory (sync call — run in thread)
        await asyncio.to_thread(
            memory_manager.store_conversation,
            client_id, user_id, session_id, user_msg, ai_response, agent_used
        )
    except Exception as e:
        logger.error(f"Background save failed: {e}")


# ── Other endpoints ───────────────────────────────────────────────────────────

@router.delete("/chat/session/{session_id}")
async def clear_session(session_id: str):
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    return {"status": "cleared"}


@router.get("/chat/history/{session_id}")
async def get_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT role, content, agent_used, created_at FROM chat_messages WHERE session_id=:sid ORDER BY created_at ASC"),
        {"sid": session_id}
    )
    rows = result.fetchall()
    return {"session_id": session_id, "messages": [
        {"role": r[0], "content": r[1], "agent_used": r[2], "created_at": str(r[3])}
        for r in rows
    ]}


@router.get("/memory/{client_id}/{user_id}")
async def get_memory(client_id: str, user_id: str, db: AsyncSession = Depends(get_db)):
    prefs = await memory_manager.load_preferences(db, client_id, user_id)
    past  = memory_manager.recall_relevant(client_id, user_id, "products", n=3)
    return {"client_id": client_id, "user_id": user_id,
            "preferences": prefs, "past_conversations": len(past)}


@router.delete("/memory/{client_id}/{user_id}")
async def clear_memory(client_id: str, user_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(
        text("DELETE FROM user_memories WHERE client_id=:cid AND user_id=:uid"),
        {"cid": client_id, "uid": user_id}
    )
    await db.commit()
    return {"message": f"Memory cleared for user {user_id}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_product_cards(message: str, context_chunks: List[Dict], website_url: str = "") -> List[Dict]:
    """
    Build product cards from RAG search results.
    Uses the metadata stored per-product during crawl: image_url, price, url, title.
    No hardcoded data. Works for any website that has been crawled.
    """
    if not context_chunks:
        return []

    msg = message.lower()

    # Skip cards for pure support queries (shipping, returns, about, etc.)
    support_kw = ["shipping", "delivery", "return policy", "refund policy", "about us",
                  "contact us", "faq", "track order", "store hours", "our story",
                  "how do i", "where is", "when will"]
    product_kw = ["show", "recommend", "buy", "price", "product", "collection",
                  "dress", "shirt", "bag", "watch", "jacket", "shoes", "saree",
                  "kurti", "top", "sale", "women", "men", "accessories"]
    is_support_only = (
        any(kw in msg for kw in support_kw) and
        not any(kw in msg for kw in product_kw)
    )
    if is_support_only:
        return []

    cards = []
    seen_titles = set()

    # Sort by relevance score — best match first
    sorted_chunks = sorted(context_chunks, key=lambda c: c.get("relevance_score", 0), reverse=True)

    for chunk in sorted_chunks:
        # Only show cards for product-type chunks
        page_type = chunk.get("page_type", "")
        if page_type not in ("product", "pricing", "category", "general"):
            continue

        title = chunk.get("title", "").strip()
        if not title or title.lower() in seen_titles:
            continue
        # Skip generic page titles
        if any(t in title.lower() for t in ["home", "about", "contact", "faq", "policy", "login"]):
            continue
        seen_titles.add(title.lower())

        # ── URL ───────────────────────────────────────────────────────────────
        url = chunk.get("url", "")
        if not url:
            url = website_url or "#"
        elif not url.startswith("http") and website_url:
            url = website_url.rstrip("/") + "/" + url.lstrip("/")

        # ── Price — from metadata (set at crawl time, guaranteed correct) ─────
        price = chunk.get("price", "")
        if not price:
            # Try to extract from content as fallback
            m = re.search(r"Price:\s*(Rs[.]?\s*[\d,]+)", chunk.get("content",""), re.IGNORECASE)
            if m:
                price = m.group(1).strip()

        # ── Image — from metadata (real product image from crawl) ─────────────
        image = chunk.get("image_url", "").strip()
        if not image or not image.startswith("http"):
            # Fallback: generic fashion image (never a tile or food image)
            image = "https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=400&q=80"

        cards.append({
            "title": title,
            "price": price or "",
            "url":   url,
            "image": image,
        })

        if len(cards) >= 3:
            break

    return cards


async def _get_active_client(client_id: str, db: AsyncSession) -> Client:
    result = await db.execute(select(Client).where(Client.id == client_id, Client.is_active == True))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Chatbot not found or inactive")
    return client


async def _validate_api_key(client_id: str, api_key: str, db: AsyncSession) -> Client:
    result = await db.execute(select(Client).where(Client.id == client_id, Client.is_active == True))
    client = result.scalar_one_or_none()
    if not client or client.api_key != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return client


async def _create_chat_session(client_id: str, session_id: str, user_id: str, db: AsyncSession):
    session = ChatSession(client_id=client_id, session_id=session_id, user_id=user_id)
    db.add(session)
    await db.commit()
