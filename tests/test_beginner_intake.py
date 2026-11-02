"""Day 13: the beginner-path questionnaire file and how answers become ranked career paths
(no database). Day 15: how the budget answer counts."""

import json
from pathlib import Path

import pytest

from app.core.exceptions import BadRequestError
from app.services.beginner_path import (
    BudgetFit,
    RoleInfo,
    budget_limit,
    load_questionnaire,
    rank_roles,
    validate_answers,
)

ROOT = Path(__file__).resolve().parents[1]
ROLES = json.loads((ROOT / "seeds" / "job_roles.json").read_text())
ROLE_INFO = [RoleInfo(r["role_id"], r["slug"], r["title"]) for r in ROLES]


def _answers(**chosen: str | list[str]) -> dict[str, list[str]]:
    return {q: [v] if isinstance(v, str) else v for q, v in chosen.items()}


FULL = _answers(
    work_style="data",
    interests=["spreadsheets"],
    background="maths",
    goal=["first_job"],
    weekly_hours="10_20",
    budget="free_only",
)


def test_the_questionnaire_file_is_valid():
    questionnaire = load_questionnaire()
    ids = [q.question_id for q in questionnaire.questions]
    assert len(ids) == len(set(ids)) and len(ids) >= 5
    assert {q.section for q in questionnaire.questions} == {
        "personality",
        "goals",
        "time",
        "finances",
    }
    slugs = {r["slug"] for r in ROLES}
    for question in questionnaire.questions:
        values = [o.value for o in question.options]
        assert len(values) == len(set(values)) and len(values) >= 2
        for option in question.options:
            assert set(option.points) <= slugs, (question.question_id, option.value)
            assert all(points > 0 for points in option.points.values())
            if option.points:
                assert option.reason
    # Every role can be recommended
    reachable = {slug for q in questionnaire.questions for o in q.options for slug in o.points}
    assert reachable == slugs


def test_the_public_questionnaire_hides_the_scoring():
    public = load_questionnaire().public()
    dumped = public.model_dump_json()
    assert "points" not in dumped and "reason" not in dumped
    assert public.version == load_questionnaire().version


def test_data_answers_put_data_analyst_first():
    ranked = rank_roles(load_questionnaire(), FULL, ROLE_INFO)
    assert ranked[0].slug == "data-analyst"
    assert [r.rank for r in ranked] == list(range(1, len(ranked) + 1))
    assert len(ranked) == 3
    scores = [r.match_score for r in ranked]
    assert scores == sorted(scores, reverse=True) and all(0 < s <= 100 for s in scores)
    assert "You like finding patterns in numbers" in ranked[0].reasons
    assert len(ranked[0].reasons) <= 3


def test_people_answers_put_a_revenue_role_first():
    answers = {
        **FULL,
        **_answers(work_style="people", interests=["talk"], background="business"),
    }
    ranked = rank_roles(load_questionnaire(), answers, ROLE_INFO)
    assert ranked[0].slug in {"sales-development-representative", "account-executive"}
    assert ranked[0].match_score >= 85


def test_more_interests_never_lower_a_score():
    one = rank_roles(load_questionnaire(), FULL, ROLE_INFO)
    more = rank_roles(
        load_questionnaire(), {**FULL, "interests": ["spreadsheets", "ai"]}, ROLE_INFO
    )
    one_scores = {r.slug: r.match_score for r in one}
    more_scores = {r.slug: r.match_score for r in more}
    for slug, score in one_scores.items():
        assert more_scores.get(slug, 0) >= score or slug not in more_scores


def test_the_same_answers_always_give_the_same_paths():
    assert rank_roles(load_questionnaire(), FULL, ROLE_INFO) == rank_roles(
        load_questionnaire(), FULL, ROLE_INFO
    )


@pytest.mark.parametrize(
    "answers, words",
    [
        ({**FULL, "nope": ["x"]}, "Unknown intake question"),
        ({**FULL, "work_style": ["sleepy"]}, "not an option"),
        ({**FULL, "work_style": ["data", "logic"]}, "only one"),
        ({k: v for k, v in FULL.items() if k != "budget"}, "Missing answers"),
    ],
)
def test_bad_answers_are_refused(answers, words):
    with pytest.raises(BadRequestError) as caught:
        validate_answers(load_questionnaire(), answers)
    assert words in caught.value.message


@pytest.mark.parametrize(
    "budget,limit",
    [
        ("free_only", 0),
        ("under_50k", 4_999_999),
        ("50k_to_200k", 20_000_000),
        ("over_200k", None),
    ],
)
def test_each_budget_answer_is_a_price_limit_in_kobo(budget, limit):
    assert budget_limit(load_questionnaire(), {**FULL, "budget": [budget]}) == limit


def test_an_affordable_programme_adds_to_the_match_and_gives_a_reason():
    questionnaire = load_questionnaire()
    neutral = {r.role_id: r for r in rank_roles(questionnaire, FULL, ROLE_INFO)}
    fit = BudgetFit(
        limit=0,
        with_programmes={"data-analyst", "machine-learning-engineer"},
        affordable={"machine-learning-engineer"},
    )
    ranked = {r.role_id: r for r in rank_roles(questionnaire, FULL, ROLE_INFO, budget=fit)}
    assert ranked[104].match_score > neutral[104].match_score
    assert ranked[103].match_score < neutral[103].match_score  # nothing it can afford
    assert "There is a free programme for this path" in ranked[104].reasons


def test_a_role_without_programmes_is_not_marked_down_for_the_budget():
    questionnaire = load_questionnaire()
    neutral = {r.role_id: r for r in rank_roles(questionnaire, FULL, ROLE_INFO)}
    fit = BudgetFit(limit=0, with_programmes=set(), affordable=set())
    ranked = {r.role_id: r for r in rank_roles(questionnaire, FULL, ROLE_INFO, budget=fit)}
    assert {k: v.match_score for k, v in ranked.items()} == {
        k: v.match_score for k, v in neutral.items()
    }
