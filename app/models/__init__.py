# Every model module, imported here so Base.metadata (Alembic, the schema tests) sees all tables.
from app.models import accounts, contact, email, jobs, models, organisations  # noqa: F401
