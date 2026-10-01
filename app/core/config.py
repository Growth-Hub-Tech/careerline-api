from pydantic_settings import BaseSettings

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

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()