# Every model module, imported here so Base.metadata (Alembic, the schema tests) sees all tables.
from app.models import contact, email, jobs, models  # noqa: F401
