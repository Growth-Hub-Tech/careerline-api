"""Day 31: the gap fixes from the front-end's list (no team decision needed).

- A cancelled plan can be resumed while its period runs (POST /subscriptions/me/resume).
- GET /subscriptions/me shows grace_ends_at while a plan is past_due, null otherwise.
- An organisation audit cannot be re-tested again inside RETEST_COOLDOWN_DAYS: 409
  retest_too_soon, with details.try_again_on (the date it can run again).
- A recruiter's shortlist holds RECRUITER_SHORTLIST_LIMIT candidates: 409 shortlist_full.
- Every result in a candidate report says whether it is shared (shared: true/false).
- Two consent keys, aux_hr_sharing and incubate_sharing, default off like the others.
"""

# ruff: noqa: F811 (pytest fixtures imported from the other day tests)

from datetime import UTC, timedelta

from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import assert_error_envelope
from tests.integration.test_audits import start, untestable  # noqa: F401 (fixtures)
from tests.integration.test_candidate_reports import _finished  # noqa: F401
from tests.integration.test_payments import fake_paystack, packs  # noqa: F401 (fixtures)
from tests.integration.test_recruiter import add_candidate, recruiter, rival  # noqa: F401
from tests.integration.test_retest import owner, retest, roles, roster  # noqa: F401
from tests.integration.test_subscriptions import my_subscription, pay, plans, subscribe  # noqa: F401

API = settings.API_PREFIX


# ---------- resume a cancelled plan ----------


async def test_a_cancelled_plan_can_be_resumed_while_its_period_runs(
    client, learner, plans, fake_paystack
):
    await pay(client, fake_paystack, (await subscribe(client, learner, 11)).json()["data"])
    url = f"{API}/subscriptions/me/resume"
    cancel = await client.post(f"{API}/subscriptions/me/cancel", headers=learner["headers"])
    assert cancel.json()["data"]["cancel_at_period_end"] is True

    response = await client.post(url, headers=learner["headers"])
    assert response.status_code == 200, response.text
    resumed = response.json()["data"]
    assert resumed["status"] == "active" and resumed["cancel_at_period_end"] is False
    assert (await my_subscription(client, learner))["cancel_at_period_end"] is False

    assert_error_envelope(
        await client.post(url, headers=learner["headers"]), 409, "conflict"
    )  # nothing left to resume


async def test_resuming_needs_a_cancelled_plan_whose_period_still_runs(
    client, db, learner, plans, fake_paystack
):
    url = f"{API}/subscriptions/me/resume"
    assert_error_envelope(await client.post(url, headers=learner["headers"]), 409, "conflict")

    await pay(client, fake_paystack, (await subscribe(client, learner, 11)).json()["data"])
    assert_error_envelope(await client.post(url, headers=learner["headers"]), 409, "conflict")

    await client.post(f"{API}/subscriptions/me/cancel", headers=learner["headers"])
    db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '1 minute'"))
    db.commit()
    assert_error_envelope(await client.post(url, headers=learner["headers"]), 409, "conflict")


async def test_a_resumed_plan_still_renews_when_its_renewal_already_ran(
    client, db, learner, plans, fake_paystack
):
    await pay(client, fake_paystack, (await subscribe(client, learner, 11)).json()["data"])
    await client.post(f"{API}/subscriptions/me/cancel", headers=learner["headers"])
    # the renewal ran inside the last hour while the plan was cancelled, and did nothing
    db.execute(text("UPDATE subscriptions SET current_period_end = now() + interval '30 minutes'"))
    db.execute(
        text("UPDATE background_jobs SET status = 'succeeded' WHERE kind = 'renew_subscription'")
    )
    db.commit()
    response = await client.post(f"{API}/subscriptions/me/resume", headers=learner["headers"])
    assert response.status_code == 200, response.text
    pending = db.execute(
        text(
            "SELECT count(*) FROM background_jobs WHERE kind = 'renew_subscription' "
            "AND status = 'queued' AND run_after <= now() + interval '1 minute'"
        )
    ).scalar_one()
    assert pending == 1


# ---------- grace end date ----------


async def test_the_grace_end_is_shown_only_while_the_plan_is_past_due(
    client, db, learner, plans, fake_paystack
):
    await pay(client, fake_paystack, (await subscribe(client, learner, 11)).json()["data"])
    assert (await my_subscription(client, learner))["grace_ends_at"] is None

    db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '1 day'"))
    db.commit()
    past_due = await my_subscription(client, learner)
    assert past_due["status"] == "past_due"
    end = _parse(past_due["current_period_end"])
    assert _parse(past_due["grace_ends_at"]) - end == timedelta(
        days=settings.SUBSCRIPTION_GRACE_DAYS
    )

    db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '10 days'"))
    db.commit()
    ended = await my_subscription(client, learner)
    assert ended["status"] == "cancelled" and ended["grace_ends_at"] is None


def _parse(value: str):
    from datetime import datetime

    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---------- audit re-test cooldown ----------


async def test_a_retest_too_soon_says_the_date_it_can_run_again(
    client,
    db,
    owner,
    roles,
    roster,
    skill,  # noqa: F811
):
    first = (await start(client, owner, role_ids=[roles["backend"]])).json()["data"]
    started = db.execute(
        text("SELECT started_at FROM audits WHERE id = :a"), {"a": first["audit_id"]}
    ).scalar_one()
    error = assert_error_envelope(
        await retest(client, owner, first["audit_id"]), 409, "retest_too_soon"
    )
    available = started.astimezone(UTC) + timedelta(days=settings.RETEST_COOLDOWN_DAYS)
    assert error["details"]["try_again_on"] == available.date().isoformat()
    assert "try again on" in error["message"]

    # two weeks on, the re-test runs; then the cooldown starts again from the re-test
    db.execute(
        text("UPDATE audits SET started_at = started_at - interval '15 days' WHERE id = :a"),
        {"a": first["audit_id"]},
    )
    db.commit()
    second = await retest(client, owner, first["audit_id"])
    assert second.status_code == 201, second.text
    assert_error_envelope(await retest(client, owner, first["audit_id"]), 409, "retest_too_soon")


async def test_the_retest_cooldown_is_a_setting(
    client,
    owner,
    roles,
    roster,
    skill,
    monkeypatch,  # noqa: F811
):
    monkeypatch.setattr(settings, "RETEST_COOLDOWN_DAYS", 0)
    first = (await start(client, owner, role_ids=[roles["backend"]])).json()["data"]
    assert (await retest(client, owner, first["audit_id"])).status_code == 201
    assert (await retest(client, owner, first["audit_id"])).status_code == 201


def test_the_defaults_are_fourteen_days_and_twenty_five_candidates():
    assert settings.RETEST_COOLDOWN_DAYS == 14
    assert settings.RECRUITER_SHORTLIST_LIMIT == 25


# ---------- recruiter shortlist cap ----------


async def test_the_shortlist_holds_its_limit_then_refuses_with_the_limit(
    client,
    recruiter,
    monkeypatch,  # noqa: F811
):
    monkeypatch.setattr(settings, "RECRUITER_SHORTLIST_LIMIT", 2)
    for email in ("a@example.com", "b@example.com"):
        assert (await add_candidate(client, recruiter, email=email)).status_code == 201
    error = assert_error_envelope(
        await add_candidate(client, recruiter, email="c@example.com"), 409, "shortlist_full"
    )
    assert error["details"]["limit"] == 2
    assert "2" in error["message"]
    listed = await client.get(f"{API}/recruiter/candidates", headers=recruiter["headers"])
    assert listed.json()["data"]["total"] == 2


async def test_a_candidate_already_on_the_list_is_still_a_409_not_a_full_list(
    client,
    recruiter,
    monkeypatch,  # noqa: F811
):
    monkeypatch.setattr(settings, "RECRUITER_SHORTLIST_LIMIT", 1)
    assert (await add_candidate(client, recruiter, email="a@example.com")).status_code == 201
    assert_error_envelope(
        await add_candidate(client, recruiter, email="a@example.com"), 409, "conflict"
    )


# ---------- shared marker in the candidate report ----------


async def test_each_result_in_the_report_says_it_is_shared(
    client,
    recruiter,
    learner,
    skill,  # noqa: F811
):
    candidate = (await add_candidate(client, recruiter)).json()["data"]
    await _finished(client, recruiter, learner, skill, candidate_id=candidate["candidate_id"])
    path = f"{API}/recruiter/candidates/{candidate['candidate_id']}/report"
    report = (await client.get(path, headers=recruiter["headers"])).json()["data"]
    assert [r["shared"] for r in report["results"]] == [True]
    listed = await client.get(f"{API}/recruiter/candidates", headers=recruiter["headers"])
    latest = listed.json()["data"]["items"][0]["latest_result"]
    assert latest["shared"] is True


# ---------- consent keys ----------


async def test_aux_hr_and_incubate_sharing_are_off_until_granted(client, learner):
    url = f"{API}/privacy/consents"
    items = (await client.get(url, headers=learner["headers"])).json()["data"]["items"]
    by_key = {c["key"]: c for c in items}
    assert by_key["aux_hr_sharing"]["granted"] is False
    assert by_key["incubate_sharing"]["granted"] is False

    changed = await client.put(
        url,
        headers=learner["headers"],
        json={
            "items": [
                {"key": "aux_hr_sharing", "granted": True},
                {"key": "incubate_sharing", "granted": True},
            ]
        },
    )
    assert changed.status_code == 200, changed.text
    by_key = {c["key"]: c for c in changed.json()["data"]["items"]}
    assert by_key["aux_hr_sharing"]["granted"] is True
    assert by_key["incubate_sharing"]["granted"] is True
    assert by_key["marketing_emails"]["granted"] is False

    unknown = await client.put(
        url, headers=learner["headers"], json={"items": [{"key": "sell_my_data", "granted": True}]}
    )
    assert unknown.status_code == 422, unknown.text
