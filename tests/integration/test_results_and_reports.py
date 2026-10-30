"""Day 12: results are real, and every result has a PDF skill report.

A result is a finished adaptive test (result_id = attempt_id). GET /results/{id}/report starts
the PDF in a background job and answers "generating"; once it is "ready" it carries a
short-lived download link that works without a token (a browser can open it). POST makes it
again; the old link then stops working.
"""

import io
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
from jose import jwt
from pypdf import PdfReader
from sqlalchemy import text

import app.services.reports as reports
from app.core.config import settings
from app.jobs.runner import JobRunner
from tests.integration.conftest import (
    answer,
    assert_error_envelope,
    option_for,
    start_attempt,
    take_test,
)

API = settings.API_PREFIX


async def _run_jobs() -> None:
    runner = JobRunner(worker_id="test")
    while await runner.run_once():
        pass


def _pdf_text(content: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


async def _download(client, url: str):
    # The link is absolute; the test client only needs its path
    return await client.get(urlparse(url).path)


@pytest.fixture
async def finished(client, learner, skill) -> dict:
    return await take_test(
        client,
        learner["headers"],
        skill,
        right=lambda info: info["subskill_id"] == skill["subskill_ids"][0],
    )


async def test_my_results_are_my_finished_tests_newest_first(client, learner, skill, finished):
    headers = learner["headers"]
    second = await take_test(client, headers, skill)
    await start_attempt(client, headers, skill["skill_id"])  # in progress: not a result

    response = await client.get(f"{API}/results", headers=headers)
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    page = response.json()["data"]
    assert page["total"] == 2 and page["limit"] == 20 and page["offset"] == 0
    assert [r["result_id"] for r in page["items"]] == [second["attempt_id"], finished["attempt_id"]]
    item = page["items"][1]
    assert item["attempt_id"] == item["result_id"] == finished["attempt_id"]
    assert item["skill_id"] == skill["skill_id"] and item["skill_name"] == "Python"
    assert item["test_id"] == 200 + skill["skill_id"]
    assert item["level"] == finished["result"]["level"]
    assert item["percentage_score"] == finished["result"]["score"]
    assert "passed" not in item

    paged = (await client.get(f"{API}/results?limit=1&offset=1", headers=headers)).json()["data"]
    assert paged["total"] == 2 and [r["result_id"] for r in paged["items"]] == [
        finished["attempt_id"]
    ]


async def test_one_result_in_detail(client, learner, finished):
    response = await client.get(
        f"{API}/results/{finished['attempt_id']}", headers=learner["headers"]
    )
    assert response.status_code == 200, response.text
    detail = response.json()["data"]
    result = finished["result"]
    assert detail["level"] == result["level"] and detail["percentage_score"] == result["score"]
    assert detail["confidence"] == result["confidence"]
    assert detail["confidence_label"] == result["confidence_label"]
    assert {s["subskill_name"]: s["band"] for s in detail["subskills"]} == {
        s["subskill_name"]: s["band"] for s in result["subskills"]
    }
    assert detail["strengths"] == [s["subskill_name"] for s in result["strengths"]]
    assert detail["gaps"] == [s["subskill_name"] for s in result["weaknesses"]]
    assert (
        detail["recommendations"] and detail["recommendations"][0]["subskill_name"] == "Functions"
    )
    assert detail["percentile"] is None  # too few results of this skill to compare
    assert "declared_level" not in detail and "passed" not in detail


async def test_a_result_is_only_for_its_owner_and_only_when_finished(
    client, learner, other_learner, skill, finished
):
    other = await client.get(
        f"{API}/results/{finished['attempt_id']}", headers=other_learner["headers"]
    )
    assert_error_envelope(other, 404, "not_found")
    running = await start_attempt(client, other_learner["headers"], skill["skill_id"])
    not_finished = await client.get(
        f"{API}/results/{running['attempt_id']}", headers=other_learner["headers"]
    )
    assert_error_envelope(not_finished, 404, "not_found")
    report = await client.get(
        f"{API}/results/{finished['attempt_id']}/report", headers=other_learner["headers"]
    )
    assert_error_envelope(report, 404, "not_found")


async def test_the_percentile_compares_with_other_results_of_the_skill(
    client, learner, skill, monkeypatch
):
    monkeypatch.setattr(reports, "PERCENTILE_MIN_RESULTS", 3)
    headers = learner["headers"]
    await take_test(client, headers, skill, right=lambda info: False)
    await take_test(client, headers, skill, right=lambda info: False)
    high = await take_test(client, headers, skill)
    items = (await client.get(f"{API}/results", headers=headers)).json()["data"]["items"]
    scores = [r["percentage_score"] for r in items]
    for item in items:
        detail = (await client.get(f"{API}/results/{item['result_id']}", headers=headers)).json()[
            "data"
        ]
        lower = sum(score < item["percentage_score"] for score in scores)
        assert detail["percentile"] == round(100 * lower / 3)
    top = next(r for r in items if r["result_id"] == high["attempt_id"])
    assert all(top["percentage_score"] > r["percentage_score"] for r in items if r != top)


async def test_the_report_is_made_in_the_background_then_downloaded(client, learner, finished):
    headers = learner["headers"]
    url = f"{API}/results/{finished['attempt_id']}/report"
    first = await client.get(url, headers=headers)
    assert first.status_code == 200, first.text
    report = first.json()["data"]
    assert report == {
        "result_id": finished["attempt_id"],
        "status": "generating",
        "download_url": None,
        "expires_at": None,
        "generated_at": None,
    }

    await _run_jobs()
    ready = (await client.get(url, headers=headers)).json()["data"]
    assert ready["status"] == "ready" and ready["generated_at"]
    expires_at = datetime.fromisoformat(ready["expires_at"])
    assert datetime.now(UTC) < expires_at <= datetime.now(UTC) + timedelta(minutes=16)
    assert ready["download_url"].startswith("http")

    download = await _download(client, ready["download_url"])  # no Authorization header
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/pdf"
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["content-disposition"].endswith('.pdf"')
    assert download.headers["cache-control"] == "private, no-store"
    assert download.content.startswith(b"%PDF")
    content = _pdf_text(download.content)
    result = finished["result"]
    for part in ("Python", "Ada Learner", result["level"], f"{result['score']}", "Lists"):
        assert part in content, part


async def test_asking_twice_makes_one_report(client, learner, finished, db):
    url = f"{API}/results/{finished['attempt_id']}/report"
    await client.get(url, headers=learner["headers"])
    await client.get(url, headers=learner["headers"])
    jobs = db.execute(
        text("SELECT count(*) FROM background_jobs WHERE kind = 'result_report'")
    ).scalar_one()
    assert jobs == 1


async def test_a_bad_or_old_link_is_410(client, learner, finished):
    headers = learner["headers"]
    url = f"{API}/results/{finished['attempt_id']}/report"
    await client.get(url, headers=headers)
    await _run_jobs()
    link = (await client.get(url, headers=headers)).json()["data"]["download_url"]
    token = urlparse(link).path.rsplit("/", 1)[1]

    tampered = await client.get(f"{API}/reports/{token[:-4]}abcd")
    assert_error_envelope(tampered, 410, "expired")
    claims = jwt.get_unverified_claims(token)
    old = jwt.encode(
        {**claims, "exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    assert_error_envelope(await client.get(f"{API}/reports/{old}"), 410, "expired")
    other_kind = jwt.encode({**claims, "typ": "access"}, settings.SECRET_KEY, algorithm="HS256")
    assert_error_envelope(await client.get(f"{API}/reports/{other_kind}"), 410, "expired")


async def test_making_it_again_retires_the_old_link(client, learner, finished):
    headers = learner["headers"]
    url = f"{API}/results/{finished['attempt_id']}/report"
    await client.get(url, headers=headers)
    await _run_jobs()
    old_link = (await client.get(url, headers=headers)).json()["data"]["download_url"]

    again = await client.post(url, headers=headers)
    assert again.status_code == 202, again.text
    assert again.json()["data"]["status"] == "generating"
    assert_error_envelope(await _download(client, old_link), 410, "expired")

    await _run_jobs()
    new_link = (await client.get(url, headers=headers)).json()["data"]["download_url"]
    assert new_link != old_link
    assert (await _download(client, new_link)).status_code == 200


async def test_a_report_that_cannot_be_made_is_failed_until_asked_again(
    client, learner, finished, monkeypatch
):
    headers = learner["headers"]
    url = f"{API}/results/{finished['attempt_id']}/report"

    def broken(data):
        raise RuntimeError("no fonts today")

    monkeypatch.setattr(reports, "build_report_pdf", broken)
    await client.get(url, headers=headers)
    await _run_jobs()
    failed = (await client.get(url, headers=headers)).json()["data"]
    assert failed["status"] == "failed" and failed["download_url"] is None

    monkeypatch.undo()
    again = await client.post(url, headers=headers)
    assert again.status_code == 202
    await _run_jobs()
    assert (await client.get(url, headers=headers)).json()["data"]["status"] == "ready"


async def test_the_report_lists_the_skill_history(client, learner, skill):
    headers = learner["headers"]
    await take_test(client, headers, skill, right=lambda info: False)
    latest = await take_test(client, headers, skill)
    url = f"{API}/results/{latest['attempt_id']}/report"
    await client.get(url, headers=headers)
    await _run_jobs()
    link = (await client.get(url, headers=headers)).json()["data"]["download_url"]
    content = _pdf_text((await _download(client, link)).content)
    assert "BEGINNER" in content and "ADVANCED" in content  # both tests of the skill
    assert "History" in content


async def test_an_expired_test_without_a_result_has_no_report(client, learner, skill, db):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    question_id = state["question"]["question_id"]
    await answer(
        client, headers, state["attempt_id"], question_id, option_for(skill, question_id, True)
    )
    db.execute(
        text("UPDATE test_attempt SET expires_at = :past WHERE attempt_id = :id"),
        {"past": datetime.now(UTC) - timedelta(minutes=1), "id": state["attempt_id"]},
    )
    db.commit()
    await client.get(f"{API}/attempts/{state['attempt_id']}/question", headers=headers)
    response = await client.get(f"{API}/results/{state['attempt_id']}/report", headers=headers)
    assert_error_envelope(response, 404, "not_found")
