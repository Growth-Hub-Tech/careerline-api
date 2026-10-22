"""Day 3 sample answers: privacy, payments, subscriptions, recruiter, invitations, organisation
audit, heatmap and targets (the flows are in test_day3_flows.py)."""

import pytest

from tests.sample.conftest import API, assert_sample, assert_sample_error

ORG = f"{API}/organisations/41"


async def test_consents_can_be_read_and_changed(client, auth):
    consents = assert_sample(await client.get(f"{API}/privacy/consents", headers=auth))
    assert {c["key"] for c in consents["items"]} == {
        "marketing_emails",
        "share_profile_with_recruiters",
        "product_research",
    }
    response = await client.put(
        f"{API}/privacy/consents",
        headers=auth,
        json={"items": [{"key": "marketing_emails", "granted": True}]},
    )
    changed = {c["key"]: c["granted"] for c in assert_sample(response)["items"]}
    assert changed["marketing_emails"] is True


async def test_an_unknown_consent_is_rejected(client, auth):
    response = await client.put(
        f"{API}/privacy/consents",
        headers=auth,
        json={"items": [{"key": "sell_my_data", "granted": True}]},
    )
    assert_sample_error(response, 422, "validation_error")


async def test_data_export_is_queued_then_ready(client, auth):
    queued = assert_sample(await client.post(f"{API}/privacy/data-exports", headers=auth), 202)
    assert queued["status"] == "queued" and queued["download_url"] is None
    ready = assert_sample(
        await client.get(f"{API}/privacy/data-exports/{queued['export_id']}", headers=auth)
    )
    assert ready["status"] == "ready" and ready["download_url"]
    pending = await client.get(
        f"{API}/privacy/data-exports/{queued['export_id']}",
        headers={**auth, "X-Mock-Scenario": "pending"},
    )
    assert assert_sample(pending)["status"] == "queued"


async def test_account_deletion_is_scheduled_and_can_be_cancelled(client, auth):
    response = await client.post(
        f"{API}/privacy/account-deletion", headers=auth, json={"password": "my-password"}
    )
    scheduled = assert_sample(response, 202)
    assert (
        scheduled["status"] == "scheduled"
        and scheduled["scheduled_for"] > scheduled["requested_at"]
    )
    cancelled = assert_sample(await client.delete(f"{API}/privacy/account-deletion", headers=auth))
    assert cancelled["status"] == "cancelled"


async def test_credit_packs_and_plans_are_public(client):
    packs = assert_sample(await client.get(f"{API}/payments/credit-packs"))
    assert all(p["price"]["currency"] == "NGN" and p["credits"] > 0 for p in packs)
    plans = assert_sample(await client.get(f"{API}/subscriptions/plans"))
    assert {p["audience"] for p in plans} == {"individual", "recruiter", "organisation"}


async def test_payment_history_can_be_empty(client, auth):
    response = await client.get(f"{API}/payments", headers={**auth, "X-Mock-Scenario": "empty"})
    assert assert_sample(response)["items"] == []


async def test_recruiter_candidates_filter_and_report(client, auth):
    candidates = assert_sample(await client.get(f"{API}/recruiter/candidates", headers=auth))
    assert candidates["total"] == 3
    done = assert_sample(
        await client.get(
            f"{API}/recruiter/candidates", headers=auth, params={"status": "completed"}
        )
    )
    assert [c["candidate_id"] for c in done["items"]] == [601]
    report = assert_sample(await client.get(f"{API}/recruiter/candidates/601/report", headers=auth))
    assert report["fit"] in {"strong_fit", "possible_fit", "not_a_fit"}
    assert report["results"][0]["level"] == "MID"


async def test_no_report_before_the_candidate_finishes(client, auth):
    response = await client.get(f"{API}/recruiter/candidates/602/report", headers=auth)
    assert_sample_error(response, 404, "not_found")


async def test_adding_a_candidate(client, auth):
    response = await client.post(
        f"{API}/recruiter/candidates",
        headers=auth,
        json={"full_name": "Ada Okafor", "email": "ada@example.com", "role_id": 101},
    )
    candidate = assert_sample(response, 201)
    assert candidate["status"] == "added" and candidate["role_title"] == "Frontend Developer"


async def test_a_learner_on_a_recruiter_route_is_forbidden(client, auth):
    response = await client.get(
        f"{API}/recruiter/candidates", headers={**auth, "X-Mock-Scenario": "forbidden"}
    )
    assert_sample_error(response, 403, "forbidden")


async def test_my_organisation_roster_and_upload(client, auth):
    org = assert_sample(await client.get(f"{API}/organisations/me", headers=auth))
    assert org["organisation_id"] == 41 and org["seats_used"] <= org["seats_total"]
    members = assert_sample(
        await client.get(f"{ORG}/members", headers=auth, params={"department": "Lending"})
    )
    assert {m["department"] for m in members["items"]} == {"Lending"}
    upload = await client.post(
        f"{ORG}/members",
        headers=auth,
        json={
            "members": [
                {"full_name": "Ngozi Okeke", "email": "ngozi.okeke@example.com", "role_id": 102},
                {"full_name": "New Person", "email": "new@example.com", "role_id": 101},
            ]
        },
    )
    assert assert_sample(upload) == {"added": 1, "updated": 1, "members_total": 5}


async def test_another_organisation_is_a_404(client, auth):
    assert_sample_error(
        await client.get(f"{API}/organisations/99/members", headers=auth), 404, "not_found"
    )


async def test_audits_with_benchmarks(client, auth):
    audits = assert_sample(await client.get(f"{ORG}/audits", headers=auth))
    audit_id = audits["items"][0]["audit_id"]
    audit = assert_sample(await client.get(f"{ORG}/audits/{audit_id}", headers=auth))
    assert audit["benchmarks"][0]["target_level"] in {"BEGINNER", "JUNIOR", "MID", "ADVANCED"}
    started = await client.post(
        f"{ORG}/audits", headers=auth, json={"name": "Backend check", "role_ids": [102]}
    )
    new = assert_sample(started, 201)
    assert new["status"] == "in_progress" and new["members_total"] == 2


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
