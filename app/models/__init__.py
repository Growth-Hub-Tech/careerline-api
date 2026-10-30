# Every model module, imported here so Base.metadata (Alembic, the schema tests) sees all tables.
from app.models import accounts, contact, email, history, jobs, models, organisations, roles  # noqa: F401
