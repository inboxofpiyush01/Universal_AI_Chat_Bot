# memory/memory_manager.py
"""
Dual Memory System:
  - ChromaDB : semantic/vector memory — stores full conversations,
                recalls relevant past chats by similarity
  - SQLite   : structured memory — stores user preferences like
                budget, room type, style. Persists forever.
"""
import chromadb
import logging
import uuid
from datetime import datetime
from typing import Dict, List
from config.settings import settings

logger = logging.getLogger(__name__)


class MemoryManager:

    def __init__(self):
        self._chroma = None
        self._collection = None

    def _get_collection(self):
        """Lazy-init ChromaDB memory collection."""
        if self._collection is None:
            self._chroma = chromadb.PersistentClient(path=settings.MEMORY_PERSIST_DIR)
            self._collection = self._chroma.get_or_create_collection(
                name="agent_conversations",
                metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    # ── ChromaDB: store a conversation turn ──────────────────────────────────
    def store_conversation(
        self,
        client_id: str,
        user_id: str,
        session_id: str,
        user_msg: str,
        bot_reply: str,
        agent_used: str
    ):
        """Store a conversation turn in ChromaDB for future semantic recall."""
        try:
            col = self._get_collection()
            doc_id = f"{client_id}_{user_id}_{datetime.utcnow().timestamp()}"
            combined = f"User: {user_msg}\nBot ({agent_used}): {bot_reply}"
            col.add(
                documents=[combined],
                metadatas=[{
                    "client_id":  client_id,
                    "user_id":    user_id,
                    "session_id": session_id,
                    "agent_used": agent_used,
                    "timestamp":  datetime.utcnow().isoformat(),
                    "user_msg":   user_msg[:300],
                }],
                ids=[doc_id]
            )
        except Exception as e:
            logger.warning(f"Memory store failed: {e}")

    # ── ChromaDB: recall relevant past conversations ──────────────────────────
    def recall_relevant(self, client_id: str, user_id: str, query: str, n: int = 5) -> List[Dict]:
        """Retrieve semantically similar past conversations for this user+client."""
        try:
            col = self._get_collection()
            total = col.count()
            if total == 0:
                return []
            results = col.query(
                query_texts=[query],
                n_results=min(n, total),
                where={"$and": [{"client_id": client_id}, {"user_id": user_id}]},
            )
            memories = []
            if results and results["documents"]:
                for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                    memories.append({
                        "content":    doc,
                        "agent_used": meta.get("agent_used", ""),
                        "timestamp":  meta.get("timestamp", ""),
                        "user_msg":   meta.get("user_msg", ""),
                    })
            return memories
        except Exception as e:
            logger.warning(f"Memory recall failed: {e}")
            return []

    # ── SQLite: save/update a structured preference ───────────────────────────
    async def save_preference(self, db, client_id: str, user_id: str, key: str, value: str):
        """Upsert a user preference in SQLite."""
        from sqlalchemy import text
        try:
            existing = await db.execute(
                text("SELECT id FROM user_memories WHERE client_id=:cid AND user_id=:uid AND memory_key=:key"),
                {"cid": client_id, "uid": user_id, "key": key}
            )
            row = existing.fetchone()
            now = datetime.utcnow()
            if row:
                await db.execute(
                    text("UPDATE user_memories SET memory_val=:val, updated_at=:now WHERE id=:id"),
                    {"val": value, "now": now, "id": row[0]}
                )
            else:
                await db.execute(
                    text("INSERT INTO user_memories (id,client_id,user_id,memory_key,memory_val,created_at,updated_at) VALUES (:id,:cid,:uid,:key,:val,:now,:now)"),
                    {"id": str(uuid.uuid4()), "cid": client_id, "uid": user_id, "key": key, "val": value, "now": now}
                )
            await db.commit()
        except Exception as e:
            logger.warning(f"Preference save failed: {e}")

    # ── SQLite: load all preferences for a user+client ────────────────────────
    async def load_preferences(self, db, client_id: str, user_id: str) -> Dict:
        """Load all stored preferences for this user+client combo."""
        from sqlalchemy import text
        try:
            result = await db.execute(
                text("SELECT memory_key, memory_val FROM user_memories WHERE client_id=:cid AND user_id=:uid"),
                {"cid": client_id, "uid": user_id}
            )
            return {row[0]: row[1] for row in result.fetchall()}
        except Exception as e:
            logger.warning(f"Preference load failed: {e}")
            return {}

    # ── Build context string for agents ──────────────────────────────────────
    def build_memory_context(self, memories: List[Dict], preferences: Dict) -> str:
        """Format memory into a context string to inject into agent prompts."""
        parts = []
        if preferences:
            pref_str = ", ".join([f"{k}: {v}" for k, v in preferences.items()])
            parts.append(f"Known user preferences: {pref_str}")
        if memories:
            parts.append("Relevant past conversations with this user:")
            for m in memories[:3]:
                parts.append(f"  [{m.get('agent_used','?')}] {m.get('user_msg','')[:100]}")
        return "\n".join(parts) if parts else ""

    # ── Auto-extract preferences from conversation ────────────────────────────
    async def extract_and_save(self, db, client_id: str, user_id: str, user_msg: str):
        """Auto-detect budget, room, style preferences from user message and save."""
        import re
        msg = user_msg.lower()

        # Budget
        m = re.search(r'budget.{0,10}rs\.?\s*(\d+)', msg)
        if m:
            await self.save_preference(db, client_id, user_id, "budget", f"Rs. {m.group(1)}")

        # Room type
        for room in ["bathroom", "kitchen", "bedroom", "living room", "outdoor", "office", "lobby"]:
            if room in msg:
                await self.save_preference(db, client_id, user_id, "preferred_room", room)
                break

        # Style
        for style in ["luxury", "budget", "modern", "traditional", "minimalist", "rustic"]:
            if style in msg:
                await self.save_preference(db, client_id, user_id, "style", style)
                break


memory_manager = MemoryManager()
