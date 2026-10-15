from pydantic_settings import BaseSettings

def _with_driver(url: str, driver: str) -> str:
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return driver + "://" + url[len(prefix):]
    return url
class Settings(BaseSettings):
    #Database
    DATABASE_URL: str

    #OpenAI
    OPENAI_API_KEY: str = ""

    #App
    APP_ENV: str = "development"
    APP_PORT: int = 8000

    #Assessment config
    PASS_THRESHOLD: int = 60
    WEAK_THRESHOLD: int = 60
    QUESTIONS_PER_LEVEL: int = 25

    @property
    def async_database_url(self) -> str:
        return _with_driver(self.DATABASE_URL, "postgresql+asyncpg")

    @property
    def sync_database_url(self) -> str:
        return _with_driver(self.DATABASE_URL, "postgresql")

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()