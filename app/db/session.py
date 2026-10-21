from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# Creating async engine with connection pooling (postgresql:// is converted to postgresql+asyncpg://)
engine = create_async_engine(
    settings.async_database_url,
    pool_size=10,  # Number of connections to keep open
    max_overflow=20,  # Extra connections allowed beyond pool_size
    pool_pre_ping=True,  # Drop connections the database closed while they sat in the pool
    echo=False,  # Set to True to see SQL queries in terminal
)

# Session factory
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# One session per request: committed when the route succeeds, rolled back when it raises
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
