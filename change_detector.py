# crawler/change_detector.py
import hashlib
import requests
import logging
from typing import Optional, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from config.database import PageHash

logger = logging.getLogger(__name__)


class ChangeDetector:
    """
    Smart change detection using MD5 hashing.
    
    Before re-crawling a page, we check if its content has changed.
    If NOT changed → skip → saves API cost and server resources!
    
    Flow:
    1. Fetch page content
    2. Compute MD5 hash of content
    3. Compare with stored hash
    4. If different → re-crawl and update vector DB
    5. If same → skip!
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def has_page_changed(self, client_id: str, url: str) -> Tuple[bool, str]:
        """
        Check if a page's content has changed since last crawl.
        
        Returns:
            (has_changed: bool, new_hash: str)
        """
        try:
            # Fetch current page content
            response = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ChatBotSaaSBot/1.0)"
            })

            if response.status_code != 200:
                logger.warning(f"Could not fetch {url}: {response.status_code}")
                return False, ""

            # Compute new hash
            new_hash = self._compute_hash(response.text)

            # Get stored hash from DB
            stored_hash = await self._get_stored_hash(client_id, url)

            if stored_hash is None:
                # First time seeing this page → definitely needs crawling
                logger.info(f"🆕 New page detected: {url}")
                return True, new_hash

            if stored_hash != new_hash:
                logger.info(f"🔄 Page changed: {url}")
                return True, new_hash
            else:
                logger.debug(f"✅ No change: {url} — skipping")
                return False, new_hash

        except Exception as e:
            logger.error(f"Change detection failed for {url}: {e}")
            return True, ""  # Default to re-crawl on error

    async def update_hash(self, client_id: str, url: str, new_hash: str):
        """Save or update the hash for a page."""
        try:
            existing = await self._get_stored_hash_record(client_id, url)

            if existing:
                existing.content_hash = new_hash
                existing.last_checked_at = datetime.utcnow()
                existing.last_changed_at = datetime.utcnow()
            else:
                new_record = PageHash(
                    client_id=client_id,
                    page_url=url,
                    content_hash=new_hash,
                )
                self.db.add(new_record)

            await self.db.commit()
            logger.debug(f"💾 Hash updated for: {url}")

        except Exception as e:
            logger.error(f"Failed to update hash for {url}: {e}")

    async def mark_checked(self, client_id: str, url: str):
        """Update last_checked_at without changing the hash (for unchanged pages)."""
        try:
            record = await self._get_stored_hash_record(client_id, url)
            if record:
                record.last_checked_at = datetime.utcnow()
                await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to mark checked for {url}: {e}")

    def _compute_hash(self, content: str) -> str:
        """Compute MD5 hash of page content."""
        # Normalize whitespace before hashing to avoid false positives
        normalized = " ".join(content.split())
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    async def _get_stored_hash(self, client_id: str, url: str) -> Optional[str]:
        """Get stored hash value for a page."""
        record = await self._get_stored_hash_record(client_id, url)
        return record.content_hash if record else None

    async def _get_stored_hash_record(self, client_id: str, url: str) -> Optional[PageHash]:
        """Get full PageHash record from DB."""
        result = await self.db.execute(
            select(PageHash).where(
                PageHash.client_id == client_id,
                PageHash.page_url == url
            )
        )
        return result.scalar_one_or_none()
