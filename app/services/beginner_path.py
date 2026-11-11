"""The beginner path, part 1 (Day 13): the intake questionnaire and ranked career paths.

- The questionnaire lives in seeds/beginner_intake.json (personality, goals, time and money,
  PRD 4.2). Each option can give points to some job roles (by slug) with the reason shown to
  the person; the points and reasons never leave the server.
- A role's match score is the points the person's answers give it out of the most its answers
  could give it (for a pick-any question, the best option picked counts, so picking more never
  lowers a score). Up to RECOMMENDATIONS_COUNT roles with any points, best first; ties go to
  more points, then the lower role id. The same answers always give the same paths.
- The starting test of a path is the role's first skill (main skill first) that can be tested
  now; null when none can.
- Every intake is kept with its answers and the paths it gave; GET .../recommendations is the
  latest one.
- Day 14 (part 2): each path carries the programme that best prepares for its role (the first
  in the programme list's order, app/services/programmes.py); null when the role has none.
- Day 15 (part 3): the budget answer counts. Each budget option is a price limit (max_price, in
  kobo; null = no limit). A role with a programme within that limit gets the file's
  budget.points on top of its answer points, and (when the budget has a limit) a reason that
  always takes one of the places; a role whose programmes are all
  over budget gets nothing (its score is out of the extra points too, so it drops); a role with
  no programme at all is left as it was. The programme shown is the best one within budget, or
  else the cheapest, and programme_within_budget says which.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.models.beginner import BeginnerIntake
from app.models.programmes import Programme, ProgrammeRole
from app.models.roles import JobRole, JobRoleSkill
from app.repositories.question_repo import testable_skill_ids
from app.schemas.beginner_path import (
    BeginnerPath,
    CareerPathRecommendation,
    IntakeOption,
    IntakeQuestion,
    IntakeQuestionnaire,
    IntakeSection,
    IntakeSubmission,
    QuestionKind,
)
from app.services.programmes import best_programmes_for_roles
from app.services.test_catalogue import TEST_ID_OFFSET

QUESTIONNAIRE_FILE = Path(__file__).resolve().parents[2] / "seeds" / "beginner_intake.json"
RECOMMENDATIONS_COUNT = 3
MAX_REASONS = 3


class ScoredOption(BaseModel):
    value: str
    label: str
    points: dict[str, int] = Field(default_factory=dict)  # role slug -> points
    reason: str = ""
    # budget options only: the most a programme may cost, in kobo (None = no limit)
    max_price: int | None = None


class BudgetRules(BaseModel):
    points: int = Field(ge=0)
    reason_free: str
    reason_within: str


class ScoredQuestion(BaseModel):
    question_id: str
    section: IntakeSection
    text: str
    kind: QuestionKind
    options: list[ScoredOption]

    def option(self, value: str) -> ScoredOption | None:
        return next((o for o in self.options if o.value == value), None)


class Questionnaire(BaseModel):
    version: str
    budget: BudgetRules
    questions: list[ScoredQuestion]

    def public(self) -> IntakeQuestionnaire:
        return IntakeQuestionnaire(
            version=self.version,
            questions=[
                IntakeQuestion(
                    question_id=q.question_id,
                    section=q.section,
                    text=q.text,
                    kind=q.kind,
                    options=[IntakeOption(value=o.value, label=o.label) for o in q.options],
                )
                for q in self.questions
            ],
        )


@lru_cache(maxsize=1)
def load_questionnaire() -> Questionnaire:
    return Questionnaire.model_validate(json.loads(QUESTIONNAIRE_FILE.read_text("utf-8")))


@dataclass(frozen=True)
class RoleInfo:
    role_id: int
    slug: str
    title: str


@dataclass(frozen=True)
class RankedRole:
    rank: int
    role_id: int
    slug: str
    title: str
    match_score: int
    reasons: list[str]


BUDGET_QUESTION = "budget"


@dataclass(frozen=True)
class BudgetFit:
    """What the budget means for each role: `limit` is the price limit in kobo (None = no
    limit), `with_programmes` the roles (slugs) that have any programme and `affordable` those
    with one within the limit."""

    limit: int | None
    with_programmes: set[str]
    affordable: set[str]


def budget_limit(questionnaire: Questionnaire, answers: dict[str, list[str]]) -> int | None:
    question = next(q for q in questionnaire.questions if q.question_id == BUDGET_QUESTION)
    option = question.option(answers[BUDGET_QUESTION][0])
    return option.max_price if option else None


def validate_answers(questionnaire: Questionnaire, answers: dict[str, list[str]]) -> None:
    by_id = {q.question_id: q for q in questionnaire.questions}
    unknown = sorted(set(answers) - set(by_id))
    if unknown:
        raise BadRequestError(f"Unknown intake question ids: {', '.join(unknown)}")
    missing = [q for q in by_id if q not in answers]
    if missing:
        raise BadRequestError(f"Missing answers for: {', '.join(missing)}")
    for question_id, values in answers.items():
        question = by_id[question_id]
        wrong = [v for v in values if question.option(v) is None]
        if wrong:
            raise BadRequestError(
                f"{', '.join(wrong)} is not an option of {question_id}; options: "
                f"{', '.join(o.value for o in question.options)}"
            )
        if question.kind != "multi_choice" and len(set(values)) != 1:
            raise BadRequestError(f"{question_id} takes only one answer")


def rank_roles(
    questionnaire: Questionnaire,
    answers: dict[str, list[str]],
    roles: list[RoleInfo],
    budget: BudgetFit | None = None,
) -> list[RankedRole]:
    rules = questionnaire.budget
    scored = []
    for position, role in enumerate(roles):
        best = got = 0
        budget_reason = ""
        reasons: list[tuple[int, int, str]] = []  # (points, question order, reason)
        for order, question in enumerate(questionnaire.questions):
            best += max((o.points.get(role.slug, 0) for o in question.options), default=0)
            picked = [o for v in answers.get(question.question_id, []) if (o := question.option(v))]
            points = max((o.points.get(role.slug, 0) for o in picked), default=0)
            got += points
            reasons += [
                (o.points[role.slug], order, o.reason)
                for o in picked
                if o.points.get(role.slug) and o.reason
            ]
        if got <= 0 or best <= 0:
            continue
        if budget is not None and role.slug in budget.with_programmes:
            best += rules.points
            if role.slug in budget.affordable:
                got += rules.points
                if budget.limit is not None:  # no limit: nothing worth saying
                    budget_reason = rules.reason_free if budget.limit == 0 else rules.reason_within
        texts: list[str] = []
        for _, _, reason in sorted(reasons, key=lambda r: (-r[0], r[1])):
            if reason not in texts:
                texts.append(reason)
        if budget_reason:  # money matters to a beginner: it always gets a place
            texts = [*texts[: MAX_REASONS - 1], budget_reason]
        scored.append((round(100 * got / best), got, role, texts[:MAX_REASONS], position))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2].role_id))
    return [
        RankedRole(rank, role.role_id, role.slug, role.title, score, reasons)
        for rank, (score, _, role, reasons, _) in enumerate(scored[:RECOMMENDATIONS_COUNT], start=1)
    ]


def _answers_by_question(submission: IntakeSubmission) -> dict[str, list[str]]:
    answers: dict[str, list[str]] = {}
    for answer in submission.answers:
        if answer.question_id in answers:
            raise BadRequestError(f"{answer.question_id} is answered twice")
        answers[answer.question_id] = list(dict.fromkeys(answer.values))
    return answers


async def _starting_tests(db: AsyncSession, role_ids: list[int]) -> dict[int, int | None]:
    links = (
        await db.scalars(
            select(JobRoleSkill)
            .where(JobRoleSkill.role_id.in_(role_ids))
            .order_by(JobRoleSkill.role_id, JobRoleSkill.position)
        )
    ).all()
    testable = await testable_skill_ids(db, list({link.skill_id for link in links}))
    starting: dict[int, int | None] = dict.fromkeys(role_ids)
    for link in links:
        if starting[link.role_id] is None and link.skill_id in testable:
            starting[link.role_id] = TEST_ID_OFFSET + link.skill_id
    return starting


async def _budget_fit(db: AsyncSession, limit: int | None) -> BudgetFit:
    prices = (
        await db.execute(
            select(JobRole.slug, func.min(Programme.price_amount))
            .join(ProgrammeRole, ProgrammeRole.role_id == JobRole.role_id)
            .join(Programme, Programme.programme_id == ProgrammeRole.programme_id)
            .where(Programme.is_active.is_(True))
            .group_by(JobRole.slug)
        )
    ).all()
    return BudgetFit(
        limit=limit,
        with_programmes={slug for slug, _ in prices},
        affordable={slug for slug, cheapest in prices if limit is None or cheapest <= limit},
    )


async def submit_intake(
    db: AsyncSession, learner_id: int, submission: IntakeSubmission
) -> BeginnerPath:
    questionnaire = load_questionnaire()
    if submission.version != questionnaire.version:
        raise BadRequestError(
            f"The questionnaire has changed (now version {questionnaire.version}): "
            "load it again with GET /beginner-path/intake"
        )
    answers = _answers_by_question(submission)
    validate_answers(questionnaire, answers)

    roles = [
        RoleInfo(r.role_id, r.slug, r.title)
        for r in (await db.scalars(select(JobRole).order_by(JobRole.role_id))).all()
    ]
    limit = budget_limit(questionnaire, answers)
    fit = await _budget_fit(db, limit)
    ranked = rank_roles(questionnaire, answers, roles, budget=fit)
    starting = await _starting_tests(db, [r.role_id for r in ranked])
    programmes = await best_programmes_for_roles(db, [r.role_id for r in ranked], limit)
    recommendations = [
        CareerPathRecommendation(
            rank=r.rank,
            role_id=r.role_id,
            title=r.title,
            match_score=r.match_score,
            reasons=r.reasons,
            starting_test_id=starting.get(r.role_id),
            programme=programmes[r.role_id].programme,
            programme_within_budget=programmes[r.role_id].within_budget,
        )
        for r in ranked
    ]
    intake = BeginnerIntake(
        learner_id=learner_id,
        version=questionnaire.version,
        answers=answers,
        recommendations=[r.model_dump(mode="json") for r in recommendations],
    )
    db.add(intake)
    await db.flush()
    await db.refresh(intake)
    return BeginnerPath(
        intake_id=intake.id, submitted_at=intake.submitted_at, recommendations=recommendations
    )


async def latest_career_paths(db: AsyncSession, learner_id: int) -> BeginnerPath:
    intake = await db.scalar(
        select(BeginnerIntake)
        .where(BeginnerIntake.learner_id == learner_id)
        .order_by(BeginnerIntake.submitted_at.desc(), BeginnerIntake.id.desc())
        .limit(1)
    )
    if intake is None:
        return BeginnerPath(intake_id=None, submitted_at=None, recommendations=[])
    return BeginnerPath(
        intake_id=intake.id,
        submitted_at=intake.submitted_at,
        recommendations=[
            CareerPathRecommendation.model_validate(r) for r in intake.recommendations
        ],
    )
