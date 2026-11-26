"""Local development server: python -m app

Serves on PORT from the environment or .env (default 8000) and reloads on code changes.
Render and the CI smoke test start through scripts/start.sh instead.
"""

import uvicorn

from app.core.config import settings


def main() -> None:
    uvicorn.run("app.main:app", port=settings.PORT, reload=True)


if __name__ == "__main__":
    main()
