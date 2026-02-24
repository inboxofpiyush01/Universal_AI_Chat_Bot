# config/database.py
from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import uuid
from config.settings import settings

Base = declarative_base()
engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Client(Base):
    """
    Represents a business/website that uses our chatbot service.
    Each client gets their own isolated vector DB collection and chat widget.
    """
    __tablename__ = "clients"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name         = Column(String, nullable=False)
    website_url  = Column(String, nullable=False)
    api_key      = Column(String, unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    ai_provider  = Column(String, default="groq")
    is_active    = Column(Boolean, default=True)
    plan         = Column(String, default="starter")

    # Chatbot personality
    bot_name     = Column(String, default="Assistant")
    bot_greeting = Column(String, default="Hi! How can I help you today?")
    bot_color    = Column(String, default="#0066CC")

    # Crawl tracking
    last_crawled_at    = Column(DateTime, nullable=True)
    crawl_status       = Column(String, default="pending")
    total_pages_crawled = Column(Integer, default=0)

    # Webhook support
    webhook_secret = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PageHash(Base):
    """Stores content hashes for smart change detection."""
    __tablename__ = "page_hashes"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id    = Column(String, nullable=False)
    page_url     = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)
    last_checked_at = Column(DateTime, default=datetime.utcnow)
    last_changed_at = Column(DateTime, default=datetime.utcnow)


class ChatSession(Base):
    """Tracks chat sessions for analytics."""
    __tablename__ = "chat_sessions"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id     = Column(String, nullable=False)
    session_id    = Column(String, nullable=False)
    user_id       = Column(String, nullable=True)
    user_pincode  = Column(String, nullable=True)
    user_contact  = Column(String, nullable=True)
    messages_count = Column(Integer, default=0)
    created_at    = Column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    """Stores individual chat messages for persistent history."""
    __tablename__ = "chat_messages"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id  = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    user_id    = Column(String, nullable=True)
    role       = Column(String, nullable=False)       # "user" or "assistant"
    content    = Column(Text, nullable=False)
    agent_used = Column(String, default="")           # which CrewAI agent responded
    intent     = Column(String, default="")           # detected intent
    created_at = Column(DateTime, default=datetime.utcnow)


class UserMemory(Base):
    """
    Stores structured user preferences per client.
    e.g. budget, preferred room, style, last product viewed.
    Persists across sessions.
    """
    __tablename__ = "user_memories"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id  = Column(String, nullable=False, index=True)
    user_id    = Column(String, nullable=False, index=True)
    memory_key = Column(String, nullable=False)
    memory_val = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


async def init_db():
    """Initialize all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database initialized")


async def get_db():
    """Dependency for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        yield session
