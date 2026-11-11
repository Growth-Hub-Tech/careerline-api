"""Day 30: docs/launch.md, the launch checklist, names every setting the production check looks at
and every setting the code reads that production must decide on."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = (ROOT / "docs/launch.md").read_text(encoding="utf-8")


def test_every_setting_the_production_check_names_is_in_the_checklist():
    source = (ROOT / "app/core/launch_checks.py").read_text(encoding="utf-8")
    names = set(re.findall(r"settings\.([A-Z][A-Z0-9_]+)", source))
    assert names, "the production check reads no settings?"
    missing = sorted(name for name in names if name not in CHECKLIST)
    assert missing == [], f"docs/launch.md does not mention {missing}"


def test_the_checklist_names_the_services_and_the_webhook():
    for words in ("python -m app.worker", "scripts/start.sh", "/readyz", "webhooks/paystack"):
        assert words in CHECKLIST, words


# The website pages the API sends people to (emails and Paystack's return): each must be a
# route of the website (careerline/src/routes), or the link in the email is a 404
PAGES = (
    "/verify-email",
    "/reset-password",
    "/forgot-password",
    "/invitations/",
    "/settings/privacy",
    "/billing",
    "/payments/callback",
)


def test_every_page_the_api_links_to_is_in_the_checklist():
    code = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app").rglob("*.py"))
    for page in PAGES:
        assert page in code, f"{page} is no longer linked: update this list"
        assert page in CHECKLIST, f"docs/launch.md does not list the page {page}"
