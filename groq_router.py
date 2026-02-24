# ai/groq_router.py
"""
Groq Model Router — automatic multi-model fallback chain.

Chain order (all on the same Groq API key, free tier):
  Primary    → llama-3.1-8b-instant       (14,400 req/day) — fast, daily workhorse
  Fallback 1 → llama-3.3-70b-versatile    ( 1,000 req/day) — better quality responses
  Fallback 2 → llama-4-scout-17b          ( 1,000 req/day) — multimodal capable
  Last resort → Ollama                    (unlimited)       — local, no internet needed

How it works:
  1. Try Primary model
  2. If rate limit hit (429) or daily quota exhausted → auto switch to Fallback 1
  3. If Fallback 1 also exhausted → auto switch to Fallback 2
  4. If all Groq models exhausted → fall back to Ollama
  5. All counters reset at midnight UTC (matching Groq's reset window)

Usage (from any agent or orchestrator):
    from ai.groq_router import groq_router
    response = groq_router.call(messages, max_tokens=400)
    print(groq_router.status())   # see which model is active + usage
"""

import logging
import re
import requests as http_requests
from datetime import datetime, timezone
from typing import List, Dict, Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class GroqModelRouter:
    """
    Single-instance router that manages the Groq model chain.
    Tracks daily usage per model and auto-switches when limits are hit.
    Resets counters at midnight UTC daily.
    """

    def __init__(self):
        self._client = None

        # Model chain — ordered by preference
        self._models = [
            {
                "name":        settings.GROQ_MODEL_PRIMARY,
                "label":       "Primary",
                "daily_limit": settings.GROQ_LIMIT_PRIMARY,
                "used_today":  0,
                "exhausted":   False,
            },
            {
                "name":        settings.GROQ_MODEL_FALLBACK1,
                "label":       "Fallback 1",
                "daily_limit": settings.GROQ_LIMIT_FALLBACK1,
                "used_today":  0,
                "exhausted":   False,
            },
            {
                "name":        settings.GROQ_MODEL_FALLBACK2,
                "label":       "Fallback 2",
                "daily_limit": settings.GROQ_LIMIT_FALLBACK2,
                "used_today":  0,
                "exhausted":   False,
            },
        ]
        self._reset_date: str = self._today()

    # ── Public API ─────────────────────────────────────────────────────────────

    def call(
        self,
        messages: List[Dict],
        max_tokens: int = 400,
        temperature: float = 0.5,
        caller: str = "",
    ) -> str:
        """
        Call the best available Groq model.
        Automatically falls back through the chain if rate limits are hit.
        Falls back to Ollama if all Groq models are exhausted.
        Returns the response text (already cleaned).
        """
        self._maybe_reset_daily_counters()

        for model in self._models:
            if model["exhausted"]:
                continue

            # Proactive skip if daily limit already reached in our tracking
            if model["daily_limit"] > 0 and model["used_today"] >= model["daily_limit"]:
                logger.warning(
                    f"[Router] {model['label']} ({model['name']}) limit reached "
                    f"({model['used_today']}/{model['daily_limit']}) — skipping"
                )
                model["exhausted"] = True
                continue

            try:
                result = self._call_groq(model, messages, max_tokens, temperature)
                model["used_today"] += 1
                tag = f"{caller} | " if caller else ""
                logger.info(
                    f"[Router] {tag}{model['label']} ({model['name']}) "
                    f"— usage {model['used_today']}/{model['daily_limit']}"
                )
                return result

            except Exception as e:
                err = str(e).lower()
                if self._is_rate_limit(err):
                    logger.warning(
                        f"[Router] {model['label']} ({model['name']}) rate limited "
                        f"— switching to next model"
                    )
                    model["exhausted"] = True
                    continue
                else:
                    # Non-rate-limit error (network, auth, etc.) — log and try next
                    logger.warning(
                        f"[Router] {model['label']} ({model['name']}) failed: {e} "
                        f"— trying next model"
                    )
                    continue

        # All Groq models failed → fall back to Ollama
        logger.warning("[Router] All Groq models exhausted — falling back to Ollama")
        return self._call_ollama(messages, max_tokens, temperature)

    def status(self) -> Dict:
        """Return current router status — useful for /health endpoint or logging."""
        self._maybe_reset_daily_counters()
        active = self._active_model()
        return {
            "active_model":  active["name"] if active else "ollama",
            "active_label":  active["label"] if active else "Ollama Fallback",
            "reset_date":    self._reset_date,
            "models": [
                {
                    "label":       m["label"],
                    "model":       m["name"],
                    "used_today":  m["used_today"],
                    "daily_limit": m["daily_limit"],
                    "exhausted":   m["exhausted"],
                    "remaining":   max(0, m["daily_limit"] - m["used_today"]),
                }
                for m in self._models
            ],
        }

    def active_model_name(self) -> str:
        """Quick helper — returns name of currently active model."""
        m = self._active_model()
        return m["name"] if m else settings.OLLAMA_MODEL

    def stream(
        self,
        messages: List[Dict],
        max_tokens: int = 280,
        temperature: float = 0.4,
        caller: str = "",
    ):
        """
        Stream tokens from the best available Groq model.
        Yields text chunks as they arrive — caller receives a generator.
        Falls back to non-streaming call() if streaming fails.
        """
        self._maybe_reset_daily_counters()

        for model in self._models:
            if model["exhausted"]:
                continue
            if model["daily_limit"] > 0 and model["used_today"] >= model["daily_limit"]:
                model["exhausted"] = True
                continue
            try:
                client = self._get_client()
                msgs = messages
                response = client.chat.completions.create(
                    model=model["name"],
                    messages=msgs,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                )
                model["used_today"] += 1
                logger.info(f"[Router] STREAM {caller} | {model['label']} ({model['name']}) — {model['used_today']}/{model['daily_limit']}")
                full_text = ""
                for chunk in response:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        full_text += delta
                # Clean the complete text ONCE — multi-byte mojibake sequences
                # (like rupee ₹ = 3 bytes) can only be fixed reliably on the full string,
                # not on individual tokens which may each carry only one byte of the sequence.
                if full_text:
                    yield _clean(full_text)
                return  # done streaming

            except Exception as e:
                err = str(e).lower()
                if self._is_rate_limit(err):
                    logger.warning(f"[Router] STREAM {model['label']} rate limited — next model")
                    model["exhausted"] = True
                    continue
                else:
                    logger.warning(f"[Router] STREAM {model['label']} failed: {e} — next model")
                    continue

        # All Groq models exhausted — fall back to Ollama (non-streaming)
        logger.warning("[Router] STREAM: all Groq exhausted — Ollama fallback (non-streaming)")
        result = self._call_ollama(messages, max_tokens, temperature)
        if result:
            yield result

    # ── Internal ───────────────────────────────────────────────────────────────

    def _get_client(self):
        if not self._client:
            from groq import Groq
            self._client = Groq(api_key=settings.GROQ_API_KEY)
        return self._client

    def _call_groq(
        self,
        model: Dict,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        client = self._get_client()
        r = client.chat.completions.create(
            model=model["name"],
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return _clean(r.choices[0].message.content or "")

    def _call_ollama(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        try:
            r = http_requests.post(
                f"{settings.OLLAMA_URL}/api/chat",
                json={
                    "model":   settings.OLLAMA_MODEL,
                    "messages": messages,
                    "stream":  False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=120,
            )
            r.raise_for_status()
            text = r.json()["message"]["content"]
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
            return _clean(text)
        except Exception as e:
            logger.error(f"[Router] Ollama also failed: {e}")
            return ""

    def _is_rate_limit(self, err_lower: str) -> bool:
        return any(w in err_lower for w in ["rate", "limit", "quota", "429", "exceeded", "throttl"])

    def _active_model(self) -> Optional[Dict]:
        """Return first non-exhausted model, or None if all exhausted."""
        self._maybe_reset_daily_counters()
        for m in self._models:
            if not m["exhausted"] and (m["daily_limit"] == 0 or m["used_today"] < m["daily_limit"]):
                return m
        return None

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _maybe_reset_daily_counters(self):
        """Reset all counters at midnight UTC — matching Groq's reset window."""
        today = self._today()
        if today != self._reset_date:
            logger.info(f"[Router] New day ({today}) — resetting all model counters")
            for m in self._models:
                m["used_today"] = 0
                m["exhausted"]  = False
            self._reset_date = today


# ── Shared text cleaner (used here and imported by agents) ────────────────────

def _needs_cleaning(text: str) -> bool:
    """Quick check — does the text have mojibake or bad chars that need fixing?"""
    bad_seqs = ["Ã", "â€", "Â", "â\x80", "â\x99", "Ã©", "Ã—"]
    return any(seq in text for seq in bad_seqs)

def _clean(text: str) -> str:
    """Aggressively clean AI text: fix mojibake, strip URLs, normalize whitespace."""
    if not text:
        return ""

    # Step 1: Fix rupee mojibake FIRST (before any encoding tricks)
    # ₹ (U+20B9) decoded wrong via Latin-1 becomes: â (U+00E2) + ‚ (U+201A) + ¹ (U+00B9)
    # Match that exact 3-char sequence and replace with Rs.
    text = re.sub(r"\u00e2[\u0080-\u00bf\u201a\u2020\u0082]?\u00b9", "Rs.", text)

    # Step 2: Fix other common mojibake sequences (curly quotes, dashes, ellipsis)
    text = re.sub(r"\u00e2\u0080[\u0098\u0099]", "'", text)   # ' '
    text = re.sub(r"\u00e2\u0080[\u009c\u009d]", '"', text)  # " "
    text = re.sub(r"\u00e2\u0080[\u0093\u0094]", "-", text)   # – —
    text = re.sub(r"\u00e2\u0080\u00a6", "...", text)           # …
    text = re.sub(r"\u00c3\u0097", "x", text)                   # ×
    text = re.sub(r"\u00c2\u00a0", " ", text)                   # non-breaking space

    # Step 3: Direct unicode symbol replacements
    text = text.replace("\u20b9", "Rs.")   # ₹
    text = text.replace("\u00d7", "x")     # ×
    text = text.replace("\u2019", "'")
    text = text.replace("\u2018", "'")
    text = text.replace("\u201c", '"')
    text = text.replace("\u201d", '"')
    text = text.replace("\u2013", "-")
    text = text.replace("\u2014", "-")
    text = text.replace("\u2026", "...")
    text = text.replace("\u00a0", " ")
    text = text.replace("\u00ae", "(R)")
    text = text.replace("\u2122", "(TM)")

    # Step 4: Collapse any duplicate Rs. (Rs.Rs. → Rs.)
    text = re.sub(r"(Rs\.)+", "Rs.", text)

    # Step 5: Strip raw URLs
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"www\.\S+", "", text)
    text = re.sub(r"(?i)(link|url)\s*:\s*", "", text)

    # Step 6: Strip ALL remaining non-ASCII characters
    cleaned = "".join(ch if ord(ch) < 128 else " " for ch in text)

    # Step 7: Normalize whitespace and formatting
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" +\n", "\n", cleaned)
    cleaned = re.sub(r"\n +", "\n", cleaned)
    cleaned = re.sub(r"Rs\.(\d)", r"Rs. \1", cleaned)
    cleaned = re.sub(r"(\d) x (\d)", r"\1x\2", cleaned)
    cleaned = re.sub(r"(\d) x(\d)", r"\1x\2", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)

    return cleaned.strip()

# ── Singleton instance — shared across all agents ─────────────────────────────
groq_router = GroqModelRouter()
