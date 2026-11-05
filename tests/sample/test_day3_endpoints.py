"""Day 3 sample answers: subscription plans (the subscription flows are in test_day3_flows.py).
Real now: the organisation audit since Days 21-23 (tests/integration/test_team_roster.py,
test_audits.py, test_heatmap_targets.py), privacy since Day 18
(tests/integration/test_privacy.py), the recruiter's candidates and invitations since Days
19-20 (tests/integration/test_recruiter.py, test_candidate_reports.py)."""

from tests.sample.conftest import API, assert_sample


async def test_plans_are_public(client):
    plans = assert_sample(await client.get(f"{API}/subscriptions/plans"))
    assert {p["audience"] for p in plans} == {"individual", "recruiter", "organisation"}
