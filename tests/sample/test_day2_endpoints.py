"""Day 2 sample answers: the profile. (The contact form is real since Day 5, the accounts since
Day 6, the roles since Day 8, the results with their PDF report since Day 12, the beginner path
since Day 13, the programmes since Day 14 and the test catalogue since Day 17: see
tests/integration/test_contact.py, test_accounts.py, test_roles.py, test_results_and_reports.py, test_beginner_path.py,
test_programmes.py and test_credits_for_tests.py.)"""

from tests.sample.conftest import API, assert_sample, assert_sample_error


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
