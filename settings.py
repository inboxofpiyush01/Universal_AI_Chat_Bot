# config/settings.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # ── AI Provider Chain: Groq model cascade → Ollama ───────────────────────
    DEFAULT_AI_PROVIDER: str = os.getenv("DEFAULT_AI_PROVIDER", "groq")

    # Groq API key (shared across all models — same key works for all)
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    # ── Groq Model Chain (tried in order when rate limits hit) ────────────────
    # Primary:    llama-3.1-8b-instant       → 14,400 req/day, very fast
    # Fallback 1: llama-3.3-70b-versatile    → 1,000 req/day, better quality
    # Fallback 2: llama-4-scout-17b          → 1,000 req/day, multimodal capable
    GROQ_MODEL_PRIMARY:   str = os.getenv("GROQ_MODEL_PRIMARY",   "llama-3.1-8b-instant")
    GROQ_MODEL_FALLBACK1: str = os.getenv("GROQ_MODEL_FALLBACK1", "llama-3.3-70b-versatile")
    GROQ_MODEL_FALLBACK2: str = os.getenv("GROQ_MODEL_FALLBACK2", "llama-4-scout-17b-e3-instruct")

    # Daily request limits (used for proactive tracking + auto-switching)
    GROQ_LIMIT_PRIMARY:   int = int(os.getenv("GROQ_LIMIT_PRIMARY",   14400))
    GROQ_LIMIT_FALLBACK1: int = int(os.getenv("GROQ_LIMIT_FALLBACK1", 1000))
    GROQ_LIMIT_FALLBACK2: int = int(os.getenv("GROQ_LIMIT_FALLBACK2", 1000))

    # Legacy alias — backward compat
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    # ── Ollama (final fallback — runs locally, free forever) ──────────────────
    OLLAMA_URL:   str = os.getenv("OLLAMA_URL",   "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:4b")

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = os.getenv("APP_NAME", "ChatBot SaaS - CrewAI Edition")
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", 8000))
    DEBUG: bool   = os.getenv("DEBUG", "True") == "True"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./chatbot_saas.db")

    # ── Vector DB (RAG) ───────────────────────────────────────────────────────
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_storage")

    # ── Agent Memory (separate ChromaDB path) ─────────────────────────────────
    MEMORY_PERSIST_DIR: str = os.getenv("MEMORY_PERSIST_DIR", "./chroma_memory")

    # ── Crawler ───────────────────────────────────────────────────────────────
    CRAWL_INTERVAL_HOURS: int = int(os.getenv("CRAWL_INTERVAL_HOURS", 6))
    MAX_PAGES_PER_SITE:   int = int(os.getenv("MAX_PAGES_PER_SITE",   100))
    CRAWL_DELAY_SECONDS:  int = int(os.getenv("CRAWL_DELAY_SECONDS",  1))

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")

settings = Settings()
