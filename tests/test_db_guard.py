import pytest

from tests.db_guard import UnsafeTestDatabase, check_test_database_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:postgres@localhost:5432/careerline_test",
        "postgresql+asyncpg://user:pw@127.0.0.1/careerline_test",
        "postgres://user:pw@db:5432/test_careerline",
    ],
)
def test_local_test_databases_are_accepted(url):
    check_test_database_url(url)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("postgresql://u:p@dpg-abc123.oregon-postgres.render.com/careerline_test", "Render"),
        ("postgresql://u:p@db.example.com:5432/careerline_test", "not local"),
        ("postgresql://u:p@localhost:5432/careerline", "'test' in its name"),
        ("mysql://u:p@localhost:3306/careerline_test", "PostgreSQL"),
    ],
)
def test_anything_else_is_refused(url, reason):
    with pytest.raises(UnsafeTestDatabase, match=reason):
        check_test_database_url(url)


def test_the_real_database_from_env_file_is_refused_even_if_named_test():
    url = "postgresql://u:p@localhost:5432/careerline_test"
    with pytest.raises(UnsafeTestDatabase, match="same database"):
        check_test_database_url(url, real_database_url="postgresql://x:y@localhost/careerline_test")
