"""Every sample router. app/main.py mounts this under /api/v1 when the sample API is on.

When a feature is built for real: move its route to app/api/routes (same path, same response
model), delete the sample route here, and regenerate openapi.json. tests/sample checks that no
sample route ever has the same method and path as a real one.
"""

from fastapi import APIRouter

sample_router = APIRouter()
