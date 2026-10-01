from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

#Convert postgresql:// to postgresql+asyncpg:// for async support
DATABASE_URL = settings.DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://"
)

#Creating async engine with connection pooling
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,        #Number of connections to keep open
    max_overflow=20,     #Extra connections allowed beyond pool_size
    echo=False           #Set to True to see SQL queries in terminal
)

#Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

#Base class for all models
class Base(DeclarativeBase):
    pass

#Dependency for FastAPI routes
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()