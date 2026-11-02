"""Day 2 sample answers: tests and profile. (The contact form is real since Day 5, the accounts
since Day 6, the roles since Day 8, the results with their PDF report since Day 12, the beginner
path since Day 13 and the programmes since Day 14: see tests/integration/test_contact.py,
test_accounts.py, test_roles.py, test_results_and_reports.py, test_beginner_path.py and
test_programmes.py.)"""

from tests.sample.conftest import API, assert_sample, assert_sample_error


async def test_the_test_catalogue_filters_by_skill_and_role(client):
    by_skill = assert_sample(await client.get(f"{API}/tests", params={"skill_id": 3}))
    assert {t["skill_id"] for t in by_skill["items"]} == {3}
    by_role = assert_sample(await client.get(f"{API}/tests", params={"role_id": 101}))
    assert all(101 in t["role_ids"] for t in by_role["items"])
    assert by_role["total"] == 2


async def test_test_detail_and_paging(client):
    page = assert_sample(await client.get(f"{API}/tests", params={"limit": 1, "offset": 1}))
    assert len(page["items"]) == 1 and page["total"] == 4 and page["offset"] == 1
    test = assert_sample(await client.get(f"{API}/tests/201"))
    assert test["format"] == "adaptive" and test["price_credits"] == 0


async def test_access_to_a_free_and_a_paid_test(client, auth):
    free = assert_sample(await client.get(f"{API}/tests/201/access", headers=auth))
    assert free["can_start"] is True and free["reason"] == "free"
    paid = assert_sample(await client.get(f"{API}/tests/202/access", headers=auth))
    assert paid["reason"] == "credits" and paid["credits_balance"] >= paid["price_credits"]


async def test_payment_needed_on_test_access_is_a_402(client, auth):
    response = await client.get(
        f"{API}/tests/202/access", headers={**auth, "X-Mock-Scenario": "payment_required"}
    )
    assert_sample_error(response, 402, "payment_required")


async def test_my_profile(client, auth):
    profile = assert_sample(await client.get(f"{API}/profile", headers=auth))
    assert profile["learner_id"] == 1 and 0 <= profile["completeness"] <= 100
    changed = assert_sample(
        await client.patch(f"{API}/profile", headers=auth, json={"weekly_hours": 15})
    )
    assert changed["weekly_hours"] == 15 and changed["headline"] == profile["headline"]
    # GET /profile/skills is real since Day 10 (tests/integration/test_test_taking.py)


async def test_profile_rejects_an_unknown_budget(client, auth):
    response = await client.patch(f"{API}/profile", headers=auth, json={"budget": "millions"})
    assert_sample_error(response, 422, "validation_error")
