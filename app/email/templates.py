"""Renders emails from app/email/templates.

layout.html and layout.txt are the ONLY files that decide how an email looks (header, colours,
footer). Every email in templates/emails/ extends them and fills these slots:

    {% set subject = "..." %}      the subject line (required)
    {% block preheader %}          the grey preview line inboxes show after the subject
    {% block content %}            the body
    {% block footer_note %}        why the person got this email (optional)

and can use the button() macro from _components.html. Brand values come from settings, as
`brand.name`, `brand.logo_url`, `brand.support_email`, `brand.website_url`, `brand.color`.
To use Omotoke's design: replace layout.html (and layout.txt) keeping those slot names.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import settings

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    undefined=StrictUndefined,  # a missing value is an error, never an empty gap in an email
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def brand() -> dict[str, Any]:
    return {
        "name": settings.EMAIL_BRAND_NAME,
        "logo_url": settings.EMAIL_LOGO_URL,
        "support_email": settings.SUPPORT_EMAIL,
        "website_url": settings.FRONTEND_URL.rstrip("/"),
        "color": "#2563EB",
        "year": datetime.now(UTC).year,
    }


def available_emails() -> list[str]:
    return sorted(path.stem for path in (TEMPLATE_DIR / "emails").glob("*.html"))


def render_email(name: str, context: dict[str, Any]) -> RenderedEmail:
    values = {**context, "brand": brand()}
    html_template = _env.get_template(f"emails/{name}.html")
    subject = str(getattr(html_template.make_module(values), "subject", "")).strip()
    if not subject:
        raise ValueError(f"emails/{name}.html does not set a subject")
    html = html_template.render(values)
    text = _env.get_template(f"emails/{name}.txt").render(values)
    return RenderedEmail(subject=subject, html=html, text=text)
