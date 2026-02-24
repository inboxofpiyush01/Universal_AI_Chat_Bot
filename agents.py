# agents/agents.py
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..')))
"""
4 Specialist Agents — all use shared GroqModelRouter.
IMPORTANT: Agents NEVER include URLs/links in text response.
Product cards with images + links are sent separately via API.
"""
import logging
from typing import List, Dict, Tuple
from ai.groq_router import groq_router

logger = logging.getLogger(__name__)


class BaseAgent:
    name = "Base Agent"
    _stream_max_tokens = 200

    def _call_llm(self, system: str, messages: List[Dict], max_tokens: int = 200) -> str:
        msgs = [{"role": "system", "content": system}] + messages
        result = groq_router.call(msgs, max_tokens=max_tokens, temperature=0.4, caller=self.name)
        if not result:
            logger.error(f"{self.name}: all models returned empty")
        return result

    def build_messages(
        self,
        query: str,
        context_chunks: List[Dict],
        client_config: Dict,
        memory_context: str = "",
        conversation_history: List[Dict] = None,
    ) -> Tuple[str, List[Dict]]:
        """Return (system_prompt, messages_list) — used by streaming endpoint."""
        system = self._build_system(context_chunks, client_config, memory_context)
        history = (conversation_history or [])[-4:]
        return system, history + [{"role": "user", "content": query}]

    def _build_system(self, context_chunks, client_config, memory_context=""):
        return f"You are {client_config.get('bot_name','Bot')} for {client_config.get('name','this business')}. Answer helpfully."

    def _clean(self, text: str) -> str:
        from ai.groq_router import _clean
        return _clean(text)

    def _ctx(self, chunks: List[Dict]) -> str:
        """Format RAG chunks for LLM context."""
        if not chunks:
            return "No relevant content found."
        parts = []
        for c in chunks:
            parts.append(c.get("content", ""))
        return "\n\n---\n\n".join(parts)


    def _extract_product_cards(self, chunks: List[Dict]) -> List[Dict]:
        """Extract product card data directly from chunk metadata — exact data, no hallucination."""
        cards = []
        seen = set()
        for c in chunks:
            name = c.get("title", "").strip()
            url  = c.get("url", "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            cards.append({
                "title": name,
                "price": c.get("price", "") or "Contact for price",
                "brand": c.get("brand", ""),
                "image": c.get("image_url", ""),
                "url":   url,
            })
        return cards[:3]


# ── AGENT 1: RAG Search ───────────────────────────────────────────────────────
class RAGSearchAgent(BaseAgent):
    name = "RAG Search Agent"
    _stream_max_tokens = 250

    def _build_system(self, context_chunks, client_config, memory_context=""):
        return (
            f"You are {client_config.get('bot_name','Bot')} for {client_config.get('name','this business')}.\n"
            f"Answer ONLY using the verified product data below. Do NOT invent names, prices, descriptions.\n"
            f"List the matching products. For each: product name (bold), price (Rs. X,XXX), description. "
            f"Skip fields you do not have — do not use placeholders.\n"
            f"Rules:\n"
            f"- ONLY use prices from the data below — never make up prices\n"
            f"- ALWAYS write Rs. for prices, NEVER use the rupee symbol\n"
            f"- Do NOT include URLs, links or web addresses\n"
            f"- Product image cards are shown automatically — do not repeat them\n"
            f"- End with one short question\n\n"
            f"CONTENT:\n{self._ctx(context_chunks)}"
            + (f"\n\nUSER PREFS: {memory_context}" if memory_context else "")
        )

    def run(self, query, context_chunks, client_config, memory_context="", conversation_history=None):
        system = self._build_system(context_chunks, client_config, memory_context)
        history = (conversation_history or [])[-4:]
        return self._call_llm(system, history + [{"role": "user", "content": query}], max_tokens=250)


# ── AGENT 2: Sales ────────────────────────────────────────────────────────────
class SalesAgent(BaseAgent):
    name = "Sales Agent"
    _stream_max_tokens = 200

    def _build_system(self, context_chunks, client_config, memory_context=""):
        return (
            f"You are {client_config.get('bot_name','Bot')} for {client_config.get('name','this business')}.\n"
            f"Recommend the SINGLE best product from the verified data below for this customer.\n"
            f"Write 2-3 sentences: name the product exactly as listed, say why it fits, mention the exact price and sizes.\n"
            f"Rules:\n"
            f"- Use ONLY product names and prices from the data below — never invent prices\n"
            f"- ALWAYS write Rs. for prices, NEVER use rupee symbol\n"
            f"- Do NOT include URLs or links\n"
            f"- End with one follow-up question\n\n"
            f"CONTENT:\n{self._ctx(context_chunks)}"
            + (f"\n\nUSER PREFS: {memory_context}" if memory_context else "")
        )

    def run(self, query, context_chunks, client_config, memory_context="", conversation_history=None):
        system = self._build_system(context_chunks, client_config, memory_context)
        history = (conversation_history or [])[-4:]
        return self._call_llm(system, history + [{"role": "user", "content": query}], max_tokens=200)

    def stream(self, query, context_chunks, client_config, memory_context="", conversation_history=None):
        system = self._build_system(context_chunks, client_config, memory_context)
        history = (conversation_history or [])[-4:]
        return super()._stream_llm(system, history + [{"role": "user", "content": query}])


class ComparisonAgent(BaseAgent):
    name = "Comparison Agent"
    _stream_max_tokens = 300

    def _build_system(self, context_chunks, client_config, memory_context=""):
        return (
            f"You are {client_config.get('bot_name','Bot')} for {client_config.get('name','this business')}.\n"
            f"Create a side-by-side comparison of the products asked about.\n"
            f"Use this exact format:\n"
            f"| Feature | Product 1 | Product 2 |\n"
            f"| --- | --- | --- |\n"
            f"| Price | ... | ... |\n"
            f"| Size | ... | ... |\n"
            f"| Material | ... | ... |\n"
            f"| Best for | ... | ... |\n\n"
            f"Rules:\n"
            f"- Use ONLY names and prices from the data below — never invent\n"
            f"- ALWAYS write Rs. for prices, NEVER use rupee symbol\n"
            f"- End with a recommendation\n\n"
            f"CONTENT:\n{self._ctx(context_chunks)}"
            + (f"\n\nUSER PREFS: {memory_context}" if memory_context else "")
        )

    def run(self, query, context_chunks, client_config, memory_context="", conversation_history=None):
        system = self._build_system(context_chunks, client_config, memory_context)
        history = (conversation_history or [])[-4:]
        return self._call_llm(system, history + [{"role": "user", "content": query}], max_tokens=300)


class CustomerSupportAgent(BaseAgent):
    name = "Customer Support Agent"
    _stream_max_tokens = 150

    def _build_system(self, context_chunks, client_config, memory_context=""):
        return (
            f"You are {client_config.get('bot_name','Bot')} for {client_config.get('name','this business')}.\n"
            f"Answer this support question warmly in 2-3 sentences.\n"
            f"Rules:\n"
            f"- Do NOT include any URLs or links in your reply\n"
            f"- No special characters\n"
            f"- If unsure, say: 'Please contact us via our website for details.'\n"
            f"- End with: 'Anything else I can help with?'\n\n"
            f"CONTENT:\n{self._ctx(context_chunks)}"
        )

    def run(self, query, context_chunks, client_config, memory_context="", conversation_history=None):
        system = self._build_system(context_chunks, client_config, memory_context)
        history = (conversation_history or [])[-4:]
        return self._call_llm(system, history + [{"role": "user", "content": query}], max_tokens=150)
