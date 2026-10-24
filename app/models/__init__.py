# Every model module, imported here so Base.metadata (Alembic, the schema tests) sees all tables.
from app.models import jobs, models  # noqa: F401
