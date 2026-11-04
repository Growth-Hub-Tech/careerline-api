"""Day 17: Paystack payments, part 2: credits pay for tests. The test catalogue is real (every
skill that can be tested is a test, test_id = 200 + skill_id), each test has a price in credits
(seeds/test_prices.json; free unless listed), GET /tests/{id}/access says whether the person can
start it, and starting a paid test takes its credits once. A test that ends before any answer
(cancelled or out of time) gives them back."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import answer, assert_error_envelope, option_for

API = settings.API_PREFIX


def _test_id(skill: dict) -> int:
    return 200 + skill["skill_id"]


@pytest.fixture
def paid(skill, database) -> dict:
    """The skill's test costs 2 credits."""
    with database.begin() as conn:
        conn.execute(
            text("INSERT INTO test_prices (skill_id, price_credits) VALUES (:s, 2)"),
            {"s": skill["skill_id"]},
        )
    return skill


def give_credits(database, learner: dict, credits: int) -> None:
    with database.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO credit_balances (learner_id, balance) VALUES (:l, :c) "
                "ON CONFLICT (learner_id) DO UPDATE SET balance = :c"
            ),
            {"l": learner["learner_id"], "c": credits},
        )


async def credits(client, learner) -> dict:
    return (await client.get(f"{API}/credits", headers=learner["headers"])).json()["data"]


async def start(client, learner, skill):
    return await client.post(
        f"{API}/attempts/start", headers=learner["headers"], json={"skill_id": skill["skill_id"]}
    )


async def test_the_catalogue_lists_every_skill_that_can_be_tested(client, skill):
    response = await client.get(f"{API}/tests")
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    page = response.json()["data"]
    assert page["total"] == 1
    (item,) = page["items"]
    assert item["test_id"] == _test_id(skill) and item["skill_id"] == skill["skill_id"]
    assert item["title"] == "Python" and item["skill_name"] == "Python"
    assert item["format"] == "adaptive" and item["price_credits"] == 0
    assert item["levels"] == ["BEGINNER", "JUNIOR", "MID", "ADVANCED"]
    assert item["question_count"] == settings.ADAPTIVE_QUESTION_COUNT
    assert item["duration_minutes"] == settings.ATTEMPT_TIME_LIMIT_MINUTES
    assert item["role_ids"] == []
    filtered = (await client.get(f"{API}/tests", params={"skill_id": 999})).json()["data"]
    assert filtered["items"] == [] and filtered["total"] == 0


async def test_test_detail_and_price(client, paid):
    response = await client.get(f"{API}/tests/{_test_id(paid)}")
    assert response.status_code == 200, response.text
    detail = response.json()["data"]
    assert detail["price_credits"] == 2
    assert detail["description"] == "Python basics"
    assert detail["subskills"] == ["Lists", "Functions"]
    assert "Confirmed level" in detail["what_you_get"]


async def test_an_unknown_test_or_one_that_cannot_be_taken_is_a_404(client, skill, database):
    assert_error_envelope(await client.get(f"{API}/tests/999"), 404, "not_found")
    with database.begin() as conn:
        other = conn.execute(
            text("INSERT INTO skills (skill_name) VALUES ('Empty') RETURNING skill_id")
        ).scalar_one()
    assert_error_envelope(await client.get(f"{API}/tests/{200 + other}"), 404, "not_found")


async def test_access_to_a_free_test(client, learner, skill):
    response = await client.get(f"{API}/tests/{_test_id(skill)}/access", headers=learner["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "test_id": _test_id(skill),
        "can_start": True,
        "reason": "free",
        "price_credits": 0,
        "credits_balance": 0,
    }


async def test_access_to_a_paid_test_depends_on_the_balance(client, learner, paid, database):
    path = f"{API}/tests/{_test_id(paid)}/access"
    short = (await client.get(path, headers=learner["headers"])).json()["data"]
    assert short["can_start"] is False and short["reason"] == "insufficient_credits"
    give_credits(database, learner, 3)
    enough = (await client.get(path, headers=learner["headers"])).json()["data"]
    assert enough == {
        "test_id": _test_id(paid),
        "can_start": True,
        "reason": "credits",
        "price_credits": 2,
        "credits_balance": 3,
    }
    assert_error_envelope(await client.get(path), 401, "unauthenticated")


async def test_a_paid_test_without_credits_is_a_402_and_starts_nothing(client, learner, paid, db):
    response = await start(client, learner, paid)
    error = assert_error_envelope(response, 402, "payment_required")
    assert "2 credits" in error["message"]
    assert db.execute(text("SELECT count(*) FROM test_attempt")).scalar() == 0


async def test_starting_a_paid_test_takes_its_credits_once(client, learner, paid, database):
    give_credits(database, learner, 5)
    first = await start(client, learner, paid)
    assert first.status_code == 200, first.text
    resumed = await start(client, learner, paid)
    assert resumed.json()["data"]["resumed"] is True
    mine = await credits(client, learner)
    assert mine["credits_balance"] == 3
    assert [(t["change"], t["reason"], t["balance_after"]) for t in mine["transactions"]] == [
        (-2, "test_started", 3)
    ]


async def test_a_free_test_never_touches_credits(client, learner, skill):
    assert (await start(client, learner, skill)).status_code == 200
    mine = await credits(client, learner)
    assert mine["credits_balance"] == 0 and mine["transactions"] == []


async def test_cancelling_before_any_answer_gives_the_credits_back(client, learner, paid, database):
    give_credits(database, learner, 2)
    attempt = (await start(client, learner, paid)).json()["data"]
    response = await client.patch(
        f"{API}/attempts/{attempt['attempt_id']}/cancel", headers=learner["headers"]
    )
    assert response.status_code == 200, response.text
    mine = await credits(client, learner)
    assert mine["credits_balance"] == 2
    assert [t["reason"] for t in mine["transactions"]] == ["refund", "test_started"]


async def test_cancelling_after_answering_keeps_the_credits(client, learner, paid, database):
    give_credits(database, learner, 2)
    attempt = (await start(client, learner, paid)).json()["data"]
    question_id = attempt["question"]["question_id"]
    await answer(
        client,
        learner["headers"],
        attempt["attempt_id"],
        question_id,
        option_for(paid, question_id, True),
    )
    await client.patch(f"{API}/attempts/{attempt['attempt_id']}/cancel", headers=learner["headers"])
    assert (await credits(client, learner))["credits_balance"] == 0


async def test_a_test_that_runs_out_unanswered_gives_the_credits_back_once(
    client, learner, paid, database
):
    give_credits(database, learner, 4)
    attempt = (await start(client, learner, paid)).json()["data"]
    with database.begin() as conn:
        conn.execute(
            text("UPDATE test_attempt SET expires_at = :past WHERE attempt_id = :a"),
            {"past": datetime.now(UTC) - timedelta(minutes=1), "a": attempt["attempt_id"]},
        )
    again = await start(client, learner, paid)  # the old one expires, a new one starts
    assert again.status_code == 200, again.text
    assert again.json()["data"]["attempt_id"] != attempt["attempt_id"]
    await client.get(f"{API}/attempts/{attempt['attempt_id']}", headers=learner["headers"])
    mine = await credits(client, learner)
    assert mine["credits_balance"] == 2
    assert [t["reason"] for t in mine["transactions"]] == ["test_started", "refund", "test_started"]


async def test_seeded_prices_are_loaded(database):
    from app.db.seed import load

    with database.begin() as conn:
        load(conn, tables=("skills", "subskills", "test_prices"))
        prices = dict(conn.execute(text("SELECT skill_id, price_credits FROM test_prices")).all())
    assert prices and all(price > 0 for price in prices.values())
