from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from agent.config import settings


def _ensure_async_pg(url: str) -> str:
    """AsyncSession requires an async driver; normalize common postgres:// URLs."""
    if not url:
        return url
    if "+asyncpg" in url or "+psycopg" in url:
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(
    _ensure_async_pg(settings.DATABASE_URL),
    echo=False,
    pool_pre_ping=True,
)

async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with async_session() as session:
        yield session
