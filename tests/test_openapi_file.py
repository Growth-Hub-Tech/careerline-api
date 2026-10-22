"""openapi.json is the API description the frontend generates its TypeScript types from.

It is committed, so a change to any route or response model must regenerate it in the same PR:
    python scripts/export_openapi.py
"""

import json

from scripts.export_openapi import OPENAPI_FILE, build_openapi, render


def test_the_committed_openapi_file_is_up_to_date():
    assert OPENAPI_FILE.exists(), "openapi.json is missing: run python scripts/export_openapi.py"
    committed = OPENAPI_FILE.read_text(encoding="utf-8")
    assert committed == render(build_openapi()), (
        "openapi.json is out of date: run python scripts/export_openapi.py and commit it"
    )


def test_the_openapi_file_includes_the_sample_routes_and_the_real_ones():
    paths = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/tests" in paths
    assert paths["/api/v1/tests"]["get"]["x-sample"] is True


def test_rendering_is_deterministic():
    assert render(build_openapi()) == render(build_openapi())
