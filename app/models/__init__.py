# Every model module, imported here so Base.metadata (Alembic, the schema tests) sees all tables.
from app.models import (  # noqa: F401
    accounts,
    beginner,
    contact,
    email,
    explanations,
    history,
    jobs,
    models,
    organisations,
    payments,
    programmes,
    reports,
    roles,
)
