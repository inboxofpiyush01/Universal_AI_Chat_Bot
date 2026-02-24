# agents/orchestrator.py
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..')))
"""
Orchestrator Agent — the crew manager.
Detects user intent and routes to the right specialist agent.
Uses shared GroqModelRouter — same fallback chain as all agents.
"""
import logging
from typing import List, Dict, Optional
from config.settings import settings
from agents.agents import RAGSearchAgent, SalesAgent, ComparisonAgent, CustomerSupportAgent
from ai.groq_router import groq_router

logger = logging.getLogger(__name__)

# ── Intent → keyword map ──────────────────────────────────────────────────────
INTENT_MAP = {
    "search": [
        "show me", "find", "what tiles", "do you have", "available",
        "looking for", "search", "catalogue", "catalog", "list", "show all"
    ],
    "recommend": [
        "recommend", "suggest", "best for", "which is good", "help me choose",
        "what should", "ideal", "perfect for", "right tile", "which one",
        "i need", "i want", "good for my"
    ],
    "compare": [
        "vs", "versus", "compare", "difference between", "better",
        "vitrified vs", "ceramic vs", "which is better", "comparison",
        "contrast", "pros and cons"
    ],
    "support": [
        "delivery", "shipping", "warranty", "installation", "install",
        "return", "refund", "store", "contact", "how long", "guarantee",
        "nearest", "location", "support", "help", "order", "track",
        "exchange", "replace", "repair"
    ],
}


class OrchestratorAgent:
    """
    Routes each user message to the right specialist agent.
    Uses keyword scoring first, LLM classification as fallback.
    All LLM calls go through the shared groq_router.
    """

    def __init__(self):
        self.rag     = RAGSearchAgent()
        self.sales   = SalesAgent()
        self.compare = ComparisonAgent()
        self.support = CustomerSupportAgent()

    def detect_intent(self, query: str) -> str:
        """Score keywords → detect intent. LLM fallback via groq_router if no clear winner."""
        q = query.lower()
        scores = {intent: 0 for intent in INTENT_MAP}
        for intent, keywords in INTENT_MAP.items():
            for kw in keywords:
                if kw in q:
                    scores[intent] += 1

        best = max(scores, key=scores.get)
        if scores[best] > 0:
            logger.info(f"[Orchestrator] Intent by keywords: {best} (score={scores[best]})")
            return best

        # No LLM fallback — saves 1 full API call per ambiguous message.
        # Keywords catch ~90% of queries. Rest default to "recommend" (Sales Agent).
        logger.info("[Orchestrator] No keyword match — defaulting to: recommend")
        return "recommend"

    def _intent_to_agent_name(self, intent: str) -> str:
        return {
            "search":    self.rag.name,
            "recommend": self.sales.name,
            "compare":   self.compare.name,
            "support":   self.support.name,
        }.get(intent, self.sales.name)

    def _get_agent(self, intent: str):
        return {
            "search":    self.rag,
            "recommend": self.sales,
            "compare":   self.compare,
            "support":   self.support,
        }.get(intent, self.sales)

    def run(
        self,
        query: str,
        context_chunks: List[Dict],
        client_config: Dict,
        memory_context: str = "",
        conversation_history: List[Dict] = None,
    ) -> Dict:
        """
        Main orchestration:
        1. Detect intent
        2. Route to correct specialist agent
        3. Return structured result with agent name, intent, active model
        """
        intent = self.detect_intent(query)
        kwargs = dict(
            query=query,
            context_chunks=context_chunks,
            client_config=client_config,
            memory_context=memory_context,
            conversation_history=conversation_history or [],
        )

        if intent == "search":
            response   = self.rag.run(**kwargs)
            agent_name = self.rag.name
        elif intent == "recommend":
            response   = self.sales.run(**kwargs)
            agent_name = self.sales.name
        elif intent == "compare":
            response   = self.compare.run(**kwargs)
            agent_name = self.compare.name
        elif intent == "support":
            response   = self.support.run(**kwargs)
            agent_name = self.support.name
        else:
            response   = self.sales.run(**kwargs)
            agent_name = self.sales.name

        if not response:
            response = "I'm having trouble right now. Please try again in a moment!"

        return {
            "response":     response,
            "agent_used":   agent_name,
            "intent":       intent,
            "model_used":   groq_router.active_model_name(),
        }
