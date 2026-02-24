# api/webhook.py
import hmac
import hashlib
import logging
from typing import Dict
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from config.database import get_db, Client
from vector_db.chroma_manager import vector_db

router = APIRouter()
logger = logging.getLogger(__name__)


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify webhook authenticity using HMAC signature.
    Prevents fake/malicious webhook calls.
    Works same as Shopify/WooCommerce webhook verification.
    """
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook/{client_id}/shopify")
async def shopify_webhook(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Shopify webhooks for real-time product updates.
    
    Setup in Shopify:
    - Go to Settings → Notifications → Webhooks
    - Add webhook URL: https://your-server.com/webhook/{client_id}/shopify
    - Select events: Product creation, Product update, Product deletion
    
    Shopify sends webhooks for:
    - products/create → new product added
    - products/update → product details changed
    - products/delete → product removed
    """
    # Get client and verify they exist
    client = await _get_client(client_id, db)

    # Get webhook topic (what happened)
    topic = request.headers.get("X-Shopify-Topic", "")
    body = await request.body()

    # Verify signature if client has webhook secret configured
    if client.webhook_secret:
        signature = request.headers.get("X-Shopify-Hmac-Sha256", "")
        if not verify_webhook_signature(body, signature, client.webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse the product data
    import json
    data = json.loads(body)
    product = data.get("product", data)  # Shopify wraps in "product" key

    logger.info(f"📦 Shopify webhook: {topic} for client {client_id}")

    if topic == "products/create":
        await _handle_product_created(client_id, product)

    elif topic == "products/update":
        await _handle_product_updated(client_id, product)

    elif topic == "products/delete":
        await _handle_product_deleted(client_id, product)

    return {"status": "ok", "topic": topic}


@router.post("/webhook/{client_id}/woocommerce")
async def woocommerce_webhook(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle WooCommerce webhooks for real-time product updates.
    
    Setup in WooCommerce:
    - Go to WooCommerce → Settings → Advanced → Webhooks
    - Add webhook URL: https://your-server.com/webhook/{client_id}/woocommerce
    - Select topic: Product created/updated/deleted
    """
    client = await _get_client(client_id, db)
    body = await request.body()

    # Verify WooCommerce signature
    if client.webhook_secret:
        signature = request.headers.get("X-WC-Webhook-Signature", "")
        if not verify_webhook_signature(body, signature, client.webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import json
    data = json.loads(body)
    topic = request.headers.get("X-WC-Webhook-Topic", "")

    logger.info(f"🛍️ WooCommerce webhook: {topic} for client {client_id}")

    if "product.created" in topic:
        await _handle_product_created(client_id, _normalize_woo_product(data))

    elif "product.updated" in topic:
        await _handle_product_updated(client_id, _normalize_woo_product(data))

    elif "product.deleted" in topic:
        await _handle_product_deleted(client_id, _normalize_woo_product(data))

    return {"status": "ok", "topic": topic}


@router.post("/webhook/{client_id}/custom")
async def custom_webhook(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Generic webhook for custom/other platforms.
    
    Expected payload format:
    {
        "event": "product_created" | "product_updated" | "product_deleted",
        "product": {
            "id": "123",
            "name": "Product Name",
            "description": "...",
            "price": "₹999",
            "category": "...",
            "url": "https://...",
            "tags": ["tag1", "tag2"]
        }
    }
    """
    await _get_client(client_id, db)
    body = await request.body()

    import json
    data = json.loads(body)
    event = data.get("event", "")
    product = data.get("product", {})

    logger.info(f"🔔 Custom webhook: {event} for client {client_id}")

    if event == "product_created":
        await _handle_product_created(client_id, product)
    elif event == "product_updated":
        await _handle_product_updated(client_id, product)
    elif event == "product_deleted":
        await _handle_product_deleted(client_id, product)
    elif event == "full_sync":
        # Complete re-sync from webhook data
        products = data.get("products", [])
        for p in products:
            vector_db.add_single_product(client_id, p)
        logger.info(f"✅ Full sync: {len(products)} products for client {client_id}")

    return {"status": "ok", "event": event}


# ─── Internal Handlers ────────────────────────────────────────────────────────

async def _handle_product_created(client_id: str, product: Dict):
    """Add new product to vector DB."""
    vector_db.add_single_product(client_id, product)
    logger.info(f"✅ New product added: {product.get('name', 'Unknown')}")


async def _handle_product_updated(client_id: str, product: Dict):
    """Update existing product in vector DB."""
    # Delete old version first
    vector_db.delete_product(client_id, str(product.get("id", "")))
    # Add new version
    vector_db.add_single_product(client_id, product)
    logger.info(f"🔄 Product updated: {product.get('name', 'Unknown')}")


async def _handle_product_deleted(client_id: str, product: Dict):
    """Remove product from vector DB."""
    vector_db.delete_product(client_id, str(product.get("id", "")))
    logger.info(f"🗑️ Product deleted: {product.get('id', 'Unknown')}")


async def _get_client(client_id: str, db: AsyncSession) -> Client:
    """Get client from DB, raise 404 if not found."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _normalize_woo_product(data: Dict) -> Dict:
    """Normalize WooCommerce product format to our standard format."""
    return {
        "id": str(data.get("id", "")),
        "name": data.get("name", ""),
        "description": data.get("description", "") or data.get("short_description", ""),
        "price": data.get("price", ""),
        "category": ", ".join([c.get("name", "") for c in data.get("categories", [])]),
        "url": data.get("permalink", ""),
        "tags": [t.get("name", "") for t in data.get("tags", [])],
    }



