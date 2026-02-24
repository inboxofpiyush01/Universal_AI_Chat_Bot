# vector_db/chroma_manager.py
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Optional
import logging
import hashlib
from config.settings import settings

logger = logging.getLogger(__name__)


class VectorDBManager:

    def __init__(self):
        self.client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        logger.info("VectorDB initialized")

    def _get_collection(self, client_id: str):
        name = "c_" + client_id.replace("-","_")[:40]
        return self.client.get_or_create_collection(
            name=name,
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )

    def add_pages(self, client_id: str, pages: List[Dict]):
        collection = self._get_collection(client_id)
        documents, metadatas, ids = [], [], []

        for page in pages:
            content = page.get("content","").strip()
            if not content:
                continue

            # ── Extract first real product image from crawled page ────────────
            image_url = ""
            structured = page.get("structured", {})
            images = structured.get("images", [])
            for img in images:
                src = img.get("src", "")
                # Skip icons, logos, tiny images — prefer product photos
                if src and not any(x in src.lower() for x in ["logo", "icon", "banner", "hero", ".svg", ".ico", "sprite"]):
                    # Resolve relative URLs
                    if src.startswith("http"):
                        image_url = src
                    else:
                        base = page.get("url", "").rsplit("/", 1)[0]
                        image_url = base + "/" + src.lstrip("/") if base else src
                    break

            # Split into smaller chunks — max 300 words each
            chunks = self._chunk(content, max_words=300, overlap=50)
            logger.info(f"Page '{page.get('title','')}' → {len(chunks)} chunks, image: {'yes' if image_url else 'no'}")

            for i, chunk in enumerate(chunks):
                if len(chunk.strip()) < 30:
                    continue
                cid = hashlib.md5(f"{client_id}{page['url']}{i}".encode()).hexdigest()
                documents.append(chunk)
                metadatas.append({
                    "url":       page.get("url",""),
                    "title":     page.get("title","")[:100],
                    "page_type": page.get("page_type","general"),
                    "chunk_idx": i,
                    "image_url": image_url,   # ← FIX: store real image from crawl
                })
                ids.append(cid)

        if not documents:
            logger.warning("No documents to add!")
            return

        # Upsert in batches of 50
        batch = 50
        for i in range(0, len(documents), batch):
            collection.upsert(
                documents=documents[i:i+batch],
                metadatas=metadatas[i:i+batch],
                ids=ids[i:i+batch],
            )
        logger.info(f"Stored {len(documents)} chunks for client {client_id}")

    def _chunk(self, text: str, max_words: int = 300, overlap: int = 50) -> List[str]:
        """Split text into overlapping word chunks."""
        words = text.split()
        if len(words) <= max_words:
            return [text]
        chunks = []
        start = 0
        while start < len(words):
            end = min(start + max_words, len(words))
            chunks.append(" ".join(words[start:end]))
            start += max_words - overlap
        return chunks

    def search(self, client_id: str, query: str, n_results: int = 5) -> List[Dict]:
        try:
            collection = self._get_collection(client_id)
            count = collection.count()
            if count == 0:
                logger.warning(f"Empty collection for {client_id}")
                return []

            results = collection.query(
                query_texts=[query],
                n_results=min(n_results, count),
                include=["documents","metadatas","distances"]
            )

            formatted = []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
            ):
                if dist < 1.5:
                    formatted.append({
                        "content":         doc,
                        "url":             meta.get("url",""),
                        "title":           meta.get("title",""),
                        "page_type":       meta.get("page_type",""),
                        "image_url":       meta.get("image_url",""),   # ← return stored image
                        "relevance_score": round(1 - dist, 3),
                    })

            logger.info(f"Search '{query[:40]}' → {len(formatted)} results")
            return formatted

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def delete_page(self, client_id: str, page_url: str):
        collection = self._get_collection(client_id)
        all_items = collection.get()
        ids_to_del = [
            iid for iid, meta in zip(all_items["ids"], all_items["metadatas"])
            if meta.get("url") == page_url
        ]
        if ids_to_del:
            collection.delete(ids=ids_to_del)

    def add_single_product(self, client_id: str, product_data: Dict):
        collection = self._get_collection(client_id)
        text = "\n".join(f"{k}: {v}" for k, v in product_data.items() if v)
        pid = f"webhook_{product_data.get('id','x')}"
        collection.upsert(
            documents=[text],
            metadatas=[{"url":"","title":product_data.get("title",""),"page_type":"product","chunk_idx":0,"image_url":product_data.get("image","")}],
            ids=[pid]
        )

    def get_stats(self, client_id: str) -> Dict:
        try:
            col = self._get_collection(client_id)
            return {"total_chunks": col.count(), "client_id": client_id}
        except Exception as e:
            return {"total_chunks": 0, "error": str(e)}

    def _url_to_id(self, url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def _product_to_text(self, p: Dict) -> str:
        return "\n".join(f"{k}: {v}" for k, v in p.items() if v)


vector_db = VectorDBManager()
