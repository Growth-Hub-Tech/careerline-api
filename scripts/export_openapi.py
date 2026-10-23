"""Write openapi.json, the API description the frontend generates TypeScript types from.

    python scripts/export_openapi.py          # regenerate openapi.json
    python scripts/export_openapi.py --check  # exit 1 if openapi.json is out of date (CI)

The file always includes the sample routes (whatever SAMPLE_API_ENABLED says here), so it is the
whole contract: real endpoints plus the sample ones that will be built later. Keys are sorted and
the output is stable, so the git diff of openapi.json shows exactly what changed in the API.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_FILE = REPO_ROOT / "openapi.json"

# Importing the app needs these; nothing here connects to a database
os.environ.setdefault("DATABASE_URL", "postgresql://openapi:openapi@127.0.0.1:5432/openapi")
os.environ.setdefault("SECRET_KEY", "openapi-export-only")
sys.path.insert(0, str(REPO_ROOT))


def build_openapi() -> dict[str, Any]:
    from app.core.config import settings
    from app.main import create_app

    previous = settings.SAMPLE_API_ENABLED
    settings.SAMPLE_API_ENABLED = True
    try:
        return create_app().openapi()
    finally:
        settings.SAMPLE_API_ENABLED = previous


def render(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = render(build_openapi())
    if "--check" in argv:
        current = OPENAPI_FILE.read_text(encoding="utf-8") if OPENAPI_FILE.exists() else ""
        if current != text:
            print(
                "openapi.json is out of date. Run: python scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print("openapi.json is up to date")
        return 0
    OPENAPI_FILE.write_text(text, encoding="utf-8")
    print(f"Wrote {OPENAPI_FILE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
