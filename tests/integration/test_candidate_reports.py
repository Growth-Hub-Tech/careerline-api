"""Day 20: recruiters, part 2: an invited test that finishes completes its invitation, the
candidate shows their latest result, and the recruiter gets the scored report (fit for the role,
a one-line summary, every invited result and the PDF)."""

from urllib.parse import urlparse

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.jobs.runner import JobRunner
from app.services.recruiting import fit_for
from tests.integration.conftest import assert_error_envelope, take_test
from tests.integration.test_recruiter import add_candidate, invite, recruiter, rival  # noqa: F401

API = settings.API_PREFIX


async def run_jobs() -> None:
    runner = JobRunner(worker_id="test")
    while await runner.run_once():
        pass


def _role(db, skill: dict, target: str) -> int:
    role_id = db.execute(
        text(
            "INSERT INTO job_roles (slug, title, track, summary, description) "
            "VALUES ('backend-dev', 'Backend Developer', 'tech', 'Builds APIs', 'Builds APIs') "
            "RETURNING role_id"
        )
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO job_role_skills (role_id, skill_id, target_level, position) "
            "VALUES (:r, :s, :t, 1)"
        ),
        {"r": role_id, "s": skill["skill_id"], "t": target},
    )
    db.commit()
    return role_id


async def _finished(client, recruiter, learner, skill, **extra) -> dict:  # noqa: F811
    sent = (await invite(client, recruiter, skill, **extra)).json()["data"]
    await client.post(f"{API}/invitations/token/{sent['token']}/accept", headers=learner["headers"])
    done = await take_test(client, learner["headers"], skill)
    assert done["status"] == "completed"
    return sent


@pytest.mark.parametrize(
    "results,fit",
    [
        ([("MID", "MID")], "strong_fit"),
        ([("ADVANCED", "MID"), ("MID", "MID")], "strong_fit"),
        ([("JUNIOR", "MID")], "possible_fit"),
        ([("BEGINNER", "MID")], "not_a_fit"),
        ([("MID", "MID"), ("BEGINNER", "ADVANCED")], "not_a_fit"),
        ([("MID", None)], "strong_fit"),
        ([("JUNIOR", None)], "possible_fit"),
        ([("BEGINNER", None)], "not_a_fit"),
    ],
)
def test_fit_compares_each_level_with_what_the_role_needs(results, fit):
    assert fit_for(results) == fit


async def test_finishing_the_invited_test_completes_the_invitation(
    client,
    recruiter,  # noqa: F811
    learner,
    skill,
):
    sent = await _finished(client, recruiter, learner, skill)
    invitation = (
        await client.get(f"{API}/invitations/{sent['invitation_id']}", headers=recruiter["headers"])
    ).json()["data"]
    assert invitation["status"] == "completed" and invitation["completed_at"]
    assert invitation["result_id"] == invitation["attempt_id"]
    candidate = (
        await client.get(
            f"{API}/recruiter/candidates/{sent['candidate_id']}", headers=recruiter["headers"]
        )
    ).json()["data"]
    assert candidate["status"] == "completed"
    latest = candidate["latest_result"]
    assert latest["result_id"] == invitation["result_id"]
    assert latest["test_id"] == sent["test_id"] and latest["test_title"] == "Python"
    assert latest["level"] in {"BEGINNER", "JUNIOR", "MID", "ADVANCED"}
    assert 0 <= latest["percentage_score"] <= 100 and latest["completed_at"]
    completed = await client.get(
        f"{API}/recruiter/candidates", headers=recruiter["headers"], params={"status": "completed"}
    )
    assert completed.json()["data"]["total"] == 1


async def test_the_report_scores_the_candidate_for_the_role(
    client,
    recruiter,  # noqa: F811
    learner,
    skill,
    db,
):
    role_id = _role(db, skill, "BEGINNER")
    candidate = (await add_candidate(client, recruiter, role_id=role_id)).json()["data"]
    assert candidate["role_title"] == "Backend Developer"
    await _finished(client, recruiter, learner, skill, candidate_id=candidate["candidate_id"])
    path = f"{API}/recruiter/candidates/{candidate['candidate_id']}/report"
    response = await client.get(path, headers=recruiter["headers"])
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    report = response.json()["data"]
    assert report["candidate_id"] == candidate["candidate_id"]
    assert report["role_title"] == "Backend Developer" and report["fit"] == "strong_fit"
    assert report["summary"].startswith("Confirmed ") and "Python" in report["summary"]
    assert len(report["results"]) == 1 and report["results"][0]["passed"] is True
    assert report["report_url"] is None  # the PDF is being made

    await run_jobs()
    report = (await client.get(path, headers=recruiter["headers"])).json()["data"]
    pdf = await client.get(urlparse(report["report_url"]).path)  # the link is the proof
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"


async def test_no_report_before_the_candidate_finishes(client, recruiter, learner, skill):  # noqa: F811
    sent = (await invite(client, recruiter, skill)).json()["data"]
    await client.post(f"{API}/invitations/token/{sent['token']}/accept", headers=learner["headers"])
    response = await client.get(
        f"{API}/recruiter/candidates/{sent['candidate_id']}/report", headers=recruiter["headers"]
    )
    assert_error_envelope(response, 404, "not_found")


async def test_another_organisation_sees_no_report(
    client,
    recruiter,  # noqa: F811
    rival,  # noqa: F811
    learner,
    skill,
):
    sent = await _finished(client, recruiter, learner, skill)
    response = await client.get(
        f"{API}/recruiter/candidates/{sent['candidate_id']}/report", headers=rival["headers"]
    )
    assert_error_envelope(response, 404, "not_found")


async def test_a_cancelled_invited_test_can_be_started_again(
    client,
    recruiter,  # noqa: F811
    learner,
    skill,
):
    sent = (await invite(client, recruiter, skill)).json()["data"]
    path = f"{API}/invitations/token/{sent['token']}/accept"
    first = (await client.post(path, headers=learner["headers"])).json()["data"]
    await client.patch(f"{API}/attempts/{first['attempt_id']}/cancel", headers=learner["headers"])
    again = (await client.post(path, headers=learner["headers"])).json()["data"]
    assert again["attempt_id"] != first["attempt_id"] and again["status"] == "accepted"


async def test_the_learners_own_test_does_not_complete_the_invitation(
    client,
    recruiter,  # noqa: F811
    learner,
    skill,
):
    await take_test(client, learner["headers"], skill)  # before any invitation
    sent = (await invite(client, recruiter, skill)).json()["data"]
    shown = await client.get(
        f"{API}/invitations/{sent['invitation_id']}", headers=recruiter["headers"]
    )
    assert shown.json()["data"]["status"] == "sent"
