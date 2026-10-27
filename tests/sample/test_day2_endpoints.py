"""Day 2 sample answers: accounts, skills and roles, tests, results, profile,
beginner path and programme clicks. (The contact form is real since Day 5: see
tests/integration/test_contact.py.)"""

from tests.sample.conftest import API, assert_sample, assert_sample_error


async def test_my_account_belongs_to_the_logged_in_person(client, auth):
    data = assert_sample(await client.get(f"{API}/accounts/me", headers=auth))
    assert data["account_id"] == 1
    assert data["account_type"] in {"learner", "recruiter", "organisation_admin"}
    assert "password" not in str(data).lower()


async def test_updating_my_account_returns_the_changed_account(client, auth):
    response = await client.patch(f"{API}/accounts/me", headers=auth, json={"full_name": "Ada O."})
    data = assert_sample(response)
    assert data["full_name"] == "Ada O."
    assert data["email"] == "ada.okafor@example.com"


async def test_a_new_password_must_have_8_characters(client, auth):
    response = await client.post(
        f"{API}/accounts/me/password",
        headers=auth,
        json={"current_password": "old-password", "new_password": "short"},
    )
    assert_sample_error(response, 422, "validation_error")


async def test_password_reset_is_public_and_always_accepted(client):
    response = await client.post(f"{API}/accounts/password-reset", json={"email": "x@example.com"})
    assert assert_sample(response, 202) == {"status": "accepted"}


async def test_an_expired_reset_token_is_a_410(client):
    response = await client.post(
        f"{API}/accounts/password-reset/confirm",
        headers={"X-Mock-Scenario": "expired"},
        json={"token": "old", "new_password": "a-new-password"},
    )
    assert_sample_error(response, 410, "expired")


async def test_roles_list_the_skills_they_need(client):
    roles = assert_sample(await client.get(f"{API}/roles"))
    assert roles["total"] == len(roles["items"]) >= 3
    role = assert_sample(await client.get(f"{API}/roles/{roles['items'][0]['role_id']}"))
    assert role["skills"][0]["target_level"] in {"BEGINNER", "JUNIOR", "MID", "ADVANCED"}
    assert role["test_ids"]


async def test_an_unknown_role_is_a_404(client):
    assert_sample_error(await client.get(f"{API}/roles/999"), 404, "not_found")


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


async def test_my_results_and_one_result_in_detail(client, auth):
    results = assert_sample(await client.get(f"{API}/results", headers=auth))
    assert results["total"] == 2
    result = assert_sample(await client.get(f"{API}/results/501", headers=auth))
    assert result["level"] == "JUNIOR"
    assert {s["band"] for s in result["subskills"]} <= {"strong", "developing", "weak"}
    assert result["recommendations"][0]["programme_id"] == 301


async def test_the_pdf_report_is_ready_generating_or_failed(client, auth):
    ready = assert_sample(await client.get(f"{API}/results/501/report", headers=auth))
    assert ready["status"] == "ready" and ready["download_url"].endswith(".pdf")
    for state in ("generating", "failed"):
        report = assert_sample(
            await client.get(
                f"{API}/results/501/report", headers={**auth, "X-Mock-Scenario": state}
            )
        )
        assert report["status"] == state and report["download_url"] is None
    again = await client.post(f"{API}/results/501/report", headers=auth)
    assert assert_sample(again, 202)["status"] == "generating"


async def test_my_profile_and_skill_profile(client, auth):
    profile = assert_sample(await client.get(f"{API}/profile", headers=auth))
    assert profile["learner_id"] == 1 and 0 <= profile["completeness"] <= 100
    changed = assert_sample(
        await client.patch(f"{API}/profile", headers=auth, json={"weekly_hours": 15})
    )
    assert changed["weekly_hours"] == 15 and changed["headline"] == profile["headline"]
    skills = assert_sample(await client.get(f"{API}/profile/skills", headers=auth))
    assert skills["skills"][0]["level"] == "JUNIOR"
    empty = await client.get(f"{API}/profile/skills", headers={**auth, "X-Mock-Scenario": "empty"})
    assert assert_sample(empty)["skills"] == []


async def test_profile_rejects_an_unknown_budget(client, auth):
    response = await client.patch(f"{API}/profile", headers=auth, json={"budget": "millions"})
    assert_sample_error(response, 422, "validation_error")


async def test_beginner_path_intake_gives_ranked_career_paths(client, auth):
    intake = assert_sample(await client.get(f"{API}/beginner-path/intake"))
    sections = {q["section"] for q in intake["questions"]}
    assert sections == {"personality", "goals", "time", "finances"}

    answers = [
        {"question_id": q["question_id"], "values": [q["options"][0]["value"]]}
        for q in intake["questions"]
    ]
    response = await client.post(
        f"{API}/beginner-path/intake",
        headers=auth,
        json={"version": intake["version"], "answers": answers},
    )
    path = assert_sample(response, 201)
    ranks = [r["rank"] for r in path["recommendations"]]
    assert ranks == sorted(ranks) and ranks[0] == 1
    assert path["recommendations"][0]["reasons"]
    assert path["recommendations"][0]["programme"]["provider_type"] == "incubate"


async def test_beginner_path_rejects_unknown_questions(client, auth):
    response = await client.post(
        f"{API}/beginner-path/intake",
        headers=auth,
        json={"version": "2026-10", "answers": [{"question_id": "nope", "values": ["x"]}]},
    )
    assert_sample_error(response, 400, "bad_request")


async def test_no_career_paths_before_the_intake(client, auth):
    response = await client.get(
        f"{API}/beginner-path/recommendations", headers={**auth, "X-Mock-Scenario": "empty"}
    )
    assert assert_sample(response)["recommendations"] == []


async def test_programmes_and_a_recorded_click(client, auth):
    programmes = assert_sample(await client.get(f"{API}/programmes", params={"role_id": 102}))
    assert {p["programme_id"] for p in programmes["items"]} == {302, 303}
    programme = assert_sample(await client.get(f"{API}/programmes/301"))
    assert programme["price"] == {"amount": 25_000_000, "currency": "NGN"}

    response = await client.post(
        f"{API}/programmes/301/clicks", headers=auth, json={"source": "result", "result_id": 501}
    )
    click = assert_sample(response, 201)
    assert click["click_id"] in click["redirect_url"]


async def test_a_click_needs_a_login(client):
    response = await client.post(f"{API}/programmes/301/clicks", json={"source": "result"})
    assert_sample_error(response, 401, "unauthenticated")
