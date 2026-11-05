"""Day 3 sample answers: subscriptions, organisation audit, heatmap and targets (the flows are in
test_day3_flows.py). Real now: the organisation and its roster since Day 21
(tests/integration/test_team_roster.py), audits since Day 22 (test_audits.py), privacy since
Day 18 (tests/integration/test_privacy.py), the recruiter's candidates and invitations since Days 19-20 (tests/integration/test_recruiter.py,
test_candidate_reports.py)."""

import pytest

from tests.sample.conftest import API, assert_sample, assert_sample_error

ORG = f"{API}/organisations/41"


async def test_plans_are_public(client):
    plans = assert_sample(await client.get(f"{API}/subscriptions/plans"))
    assert {p["audience"] for p in plans} == {"individual", "recruiter", "organisation"}


async def test_another_organisation_is_a_404(client, auth):
    assert_sample_error(
        await client.get(f"{API}/organisations/99/heatmap", headers=auth), 404, "not_found"
    )


@pytest.mark.parametrize("group_by,rows", [("department", 2), ("role", 3), ("member", 2)])
async def test_heatmap_by_department_role_or_person(client, auth, group_by, rows):
    heatmap = assert_sample(
        await client.get(f"{ORG}/heatmap", headers=auth, params={"group_by": group_by})
    )
    assert heatmap["group_by"] == group_by and len(heatmap["rows"]) == rows
    skill_ids = [s["skill_id"] for s in heatmap["skills"]]
    for row in heatmap["rows"]:
        assert [c["skill_id"] for c in row["cells"]] == skill_ids
        assert all(
            c["band"] in {"strong", "developing", "weak", "not_tested"} for c in row["cells"]
        )


async def test_heatmap_rejects_an_unknown_grouping_and_can_be_empty(client, auth):
    bad = await client.get(f"{ORG}/heatmap", headers=auth, params={"group_by": "shoe_size"})
    assert_sample_error(bad, 422, "validation_error")
    empty = await client.get(f"{ORG}/heatmap", headers={**auth, "X-Mock-Scenario": "empty"})
    assert assert_sample(empty)["rows"] == []


async def test_targets_can_be_read_and_replaced(client, auth):
    targets = assert_sample(await client.get(f"{ORG}/targets", headers=auth))
    assert all(0 <= t["progress_percent"] <= 100 for t in targets["items"])
    response = await client.put(
        f"{ORG}/targets",
        headers=auth,
        json={
            "items": [
                {"role_id": 103, "skill_id": 3, "target_level": "MID", "due_date": "2027-06-30"}
            ]
        },
    )
    replaced = assert_sample(response)["items"]
    assert len(replaced) == 1 and replaced[0]["role_title"] == "Data Analyst"
    assert replaced[0]["due_date"] == "2027-06-30"
