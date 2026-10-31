"""Taking a test for real (Day 10): the adaptive engine (Day 9) behind the API.

- One question at a time, never with its answer; the next one is chosen after each answer.
- Starting a skill that already has a test in progress resumes it (same question).
- A test runs out after ATTEMPT_TIME_LIMIT_MINUTES. With at least
  ADAPTIVE_MIN_ANSWERS_FOR_RESULT answers it is scored on what was answered (ended_by
  "time_up"), otherwise it ends EXPIRED with no result.
- When a test ends, the result (on test_attempt, with the per-level and per-subskill stats and
  the level for /recommendations/levels) and a skill-history entry are written in the same
  database transaction as the last answer: either all of it is saved or none of it.
- There is no pass or fail and no self-declared level.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ExpiredError,
    ForbiddenError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.models.history import SkillHistory
from app.models.models import (
    AttemptQuestion,
    AttemptStatus,
    LearnerAnswer,
    LevelName,
    Option,
    Question,
    QuestionStatus,
    Skill,
    Subskill,
    TestAttempt,
)
from app.repositories.attempt_repo import get_level_id_by_name, get_options_for_question
from app.repositories.question_repo import readiness
from app.repositories.scoring_repo import (
    assign_learner_level,
    save_difficulty_stats,
    save_subskill_stats,
)
from app.schemas.attempts import (
    AttemptResult,
    AttemptState,
    ServedOption,
    ServedQuestion,
    SubskillOutcome,
    SubskillRef,
)
from app.services import adaptive_engine as engine
from app.services.explanations import queue_explanations
from app.services.question_picking import pick_next
from app.services.scoring_service import generate_recommendations

logger = get_logger(__name__)

STATUS_WORDS = {
    AttemptStatus.IN_PROGRESS: "in_progress",
    AttemptStatus.COMPLETED: "completed",
    AttemptStatus.EXPIRED: "expired",
    AttemptStatus.CANCELLED: "cancelled",
    AttemptStatus.PASSED: "completed",  # the retired fixed test
    AttemptStatus.FAILED: "completed",
}


class SkillNotReady(ConflictError):
    """Some level of the skill has too few ACTIVE questions to test it fairly (Day 8)."""

    code = "skill_not_ready"


class AttemptFinished(ConflictError):
    code = "attempt_finished"


class NotCurrentQuestion(ConflictError):
    code = "not_current_question"


@dataclass(frozen=True)
class PoolQuestion:
    question_id: int
    subskill_id: int
    level: str


@dataclass
class Served:
    row: AttemptQuestion
    subskill_id: int


def _now() -> datetime:
    return datetime.now(UTC)


def _config(attempt: TestAttempt, start_level: str | None = None) -> engine.EngineConfig:
    return engine.EngineConfig(
        length=attempt.question_count or settings.ADAPTIVE_QUESTION_COUNT,
        start_level=start_level or settings.ADAPTIVE_START_LEVEL,
    )


async def _served(db: AsyncSession, attempt_id: int) -> list[Served]:
    rows = await db.execute(
        select(AttemptQuestion, Question.subskill_id)
        .join(Question, Question.question_id == AttemptQuestion.question_id)
        .where(AttemptQuestion.attempt_id == attempt_id)
        .order_by(AttemptQuestion.position)
    )
    return [Served(row, subskill_id) for row, subskill_id in rows.all()]


def _answers(served: list[Served]) -> list[engine.Answer]:
    return [
        engine.Answer(
            s.row.question_id,
            s.row.level.value if s.row.level else "JUNIOR",
            s.subskill_id,
            bool(s.row.is_correct),
        )
        for s in served
        if s.row.answered_at is not None
    ]


async def _pool(db: AsyncSession, skill_id: int) -> list[PoolQuestion]:
    rows = await db.execute(
        select(Question.question_id, Question.subskill_id, Question.difficulty_level)
        .join(Subskill, Subskill.subskill_id == Question.subskill_id)
        .where(Subskill.skill_id == skill_id, Question.status == QuestionStatus.ACTIVE)
        .order_by(Question.question_id)
    )
    return [PoolQuestion(qid, sid, level.value) for qid, sid, level in rows.all()]


async def _seen(
    db: AsyncSession, learner_id: int, skill_id: int, attempt_id: int
) -> dict[int, int]:
    """How often this person got each question in earlier tests of this skill."""
    rows = await db.execute(
        select(AttemptQuestion.question_id, func.count())
        .join(TestAttempt, TestAttempt.attempt_id == AttemptQuestion.attempt_id)
        .where(
            TestAttempt.learner_id == learner_id,
            TestAttempt.skill_id == skill_id,
            TestAttempt.attempt_id != attempt_id,
        )
        .group_by(AttemptQuestion.question_id)
    )
    return {qid: count for qid, count in rows.all()}


async def _serve_next(
    db: AsyncSession, attempt: TestAttempt, served: list[Served], level: str
) -> Served | None:
    pool = await _pool(db, attempt.skill_id)
    seen = await _seen(db, attempt.learner_id, attempt.skill_id, attempt.attempt_id)
    already = [PoolQuestion(s.row.question_id, s.subskill_id, "") for s in served]
    rng = random.Random(f"{attempt.attempt_id}-{len(served) + 1}")
    question = pick_next(pool, level, already, seen, rng, level_of=lambda q: q.level)
    if question is None:
        return None
    row = AttemptQuestion(
        attempt_id=attempt.attempt_id,
        question_id=question.question_id,
        position=len(served) + 1,
        level=LevelName(question.level),
        served_at=_now(),
    )
    db.add(row)
    await db.flush()
    item = Served(row, question.subskill_id)
    served.append(item)
    return item


async def _question_payload(db: AsyncSession, attempt_id: int, item: Served) -> ServedQuestion:
    question = await db.get(Question, item.row.question_id)
    assert question is not None
    options = await get_options_for_question(db, question.question_id, attempt_id)
    return ServedQuestion(
        position=item.row.position,
        question_id=question.question_id,
        question_text=question.question_text,
        subskill_id=question.subskill_id,
        options=[ServedOption(**o) for o in options],
    )


async def _subskill_names(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(Subskill.subskill_id, Subskill.subskill_name).where(Subskill.subskill_id.in_(ids))
    )
    return dict(rows.tuples().all())


async def _result_payload(
    db: AsyncSession, attempt: TestAttempt, served: list[Served], recorded_at: datetime
) -> AttemptResult:
    scored = engine.score_attempt(_answers(served), _config(attempt))
    names = await _subskill_names(db, [s.subskill_id for s in scored.subskills])

    def ref(subskill_id: int) -> SubskillRef:
        return SubskillRef(subskill_id=subskill_id, subskill_name=names.get(subskill_id, ""))

    # The score, level and confidence saved when the test ended (the engine's settings could
    # change later); the subskill details are worked out again from the answers
    score = scored.score if attempt.overall_percentage is None else int(attempt.overall_percentage)
    return AttemptResult(
        score=score,
        level=LevelName(engine.score_to_level(score, _config(attempt))),
        confidence=scored.confidence if attempt.confidence is None else float(attempt.confidence),
        confidence_label=scored.confidence_label,
        answered=scored.answered,
        correct=scored.correct,
        strengths=[ref(s) for s in scored.strengths],
        weaknesses=[ref(s) for s in scored.weaknesses],
        subskills=[
            SubskillOutcome(
                subskill_id=s.subskill_id,
                subskill_name=names.get(s.subskill_id, ""),
                answered=s.answered,
                correct=s.correct,
                percentage_score=s.percentage_score,
                band=s.band,
            )
            for s in scored.subskills
        ],
        ended_by="time_up" if attempt.ended_by == "time_up" else "finished",
        completed_at=recorded_at,
    )


async def save_skill_history(db: AsyncSession, attempt: TestAttempt, scored: engine.Result) -> None:
    """One skill-history entry for a finished test (same transaction as the result)."""
    db.add(
        SkillHistory(
            learner_id=attempt.learner_id,
            skill_id=attempt.skill_id,
            attempt_id=attempt.attempt_id,
            level=LevelName(scored.level),
            score=scored.score,
            confidence=scored.confidence,
            strengths=scored.strengths,
            weaknesses=scored.weaknesses,
        )
    )
    await db.flush()


async def _finish(
    db: AsyncSession, attempt: TestAttempt, served: list[Served], ended_by: str
) -> dict | None:
    """Score the test and save the result, the stats, the level and the history entry."""
    answers = _answers(served)
    scored = engine.score_attempt(answers, _config(attempt))
    level_id = await get_level_id_by_name(db, scored.level)
    attempt.attempt_status = AttemptStatus.COMPLETED
    attempt.end_time = _now().replace(tzinfo=None)  # type: ignore[assignment]
    attempt.overall_percentage = scored.score
    attempt.assigned_level_id = level_id
    attempt.ability = scored.ability
    attempt.confidence = scored.confidence
    attempt.ended_by = ended_by

    by_level: dict[LevelName, dict[str, int]] = {}
    by_subskill: dict[int, dict[str, int]] = {}
    for a in answers:
        level_stats = by_level.setdefault(LevelName(a.level), {"correct": 0, "total": 0})
        subskill_stats = by_subskill.setdefault(a.subskill_id, {"correct": 0, "total": 0})
        for stats in (level_stats, subskill_stats):
            stats["total"] += 1
            stats["correct"] += int(a.correct)
    await save_difficulty_stats(db, attempt.attempt_id, by_level)
    await save_subskill_stats(db, attempt.attempt_id, by_subskill)
    if level_id:
        await assign_learner_level(
            db, attempt.learner_id, attempt.skill_id, attempt.attempt_id, level_id
        )
    await save_skill_history(db, attempt, scored)
    # Day 11: the AI explanations of the answers are written in the background
    await queue_explanations(db, attempt.attempt_id)
    logger.info(
        "attempt_finished",
        attempt_id=attempt.attempt_id,
        score=scored.score,
        level=scored.level,
        ended_by=ended_by,
    )
    return await generate_recommendations(
        db, attempt.attempt_id, attempt.learner_id, weak_subskill_ids=scored.weaknesses
    )


def _is_expired(attempt: TestAttempt) -> bool:
    return attempt.expires_at is not None and _now() >= attempt.expires_at


async def _expire(db: AsyncSession, attempt: TestAttempt, served: list[Served]) -> None:
    if len(_answers(served)) >= settings.ADAPTIVE_MIN_ANSWERS_FOR_RESULT:
        await _finish(db, attempt, served, "time_up")
    else:
        attempt.attempt_status = AttemptStatus.EXPIRED
        attempt.end_time = _now().replace(tzinfo=None)  # type: ignore[assignment]
        logger.info("attempt_expired", attempt_id=attempt.attempt_id)
    await db.flush()


def is_expired(attempt: TestAttempt) -> bool:
    return _is_expired(attempt)


async def expire(db: AsyncSession, attempt: TestAttempt) -> None:
    """End a test whose time ran out (scored if enough answers), e.g. when it is reviewed."""
    await _expire(db, attempt, await _served(db, attempt.attempt_id))


async def _state(
    db: AsyncSession,
    attempt: TestAttempt,
    served: list[Served],
    *,
    resumed: bool = False,
    recommendations: dict | None = None,
) -> AttemptState:
    question = None
    result = None
    if attempt.attempt_status == AttemptStatus.IN_PROGRESS:
        current = next((s for s in served if s.row.answered_at is None), None)
        if current is not None:
            question = await _question_payload(db, attempt.attempt_id, current)
    elif attempt.attempt_status == AttemptStatus.COMPLETED and attempt.test_format == "adaptive":
        history = await db.scalar(
            select(SkillHistory).where(SkillHistory.attempt_id == attempt.attempt_id)
        )
        recorded = history.recorded_at if history else _now()
        result = await _result_payload(db, attempt, served, recorded or _now())
    return AttemptState(
        attempt_id=attempt.attempt_id,
        skill_id=attempt.skill_id,
        status=STATUS_WORDS[attempt.attempt_status],
        resumed=resumed,
        total_questions=attempt.question_count or len(served),
        answered=len(_answers(served)),
        expires_at=attempt.expires_at,
        question=question,
        result=result,
        recommendations=recommendations,
    )


async def _latest_level(db: AsyncSession, learner_id: int, skill_id: int) -> str | None:
    level = await db.scalar(
        select(SkillHistory.level)
        .where(SkillHistory.learner_id == learner_id, SkillHistory.skill_id == skill_id)
        .order_by(SkillHistory.recorded_at.desc(), SkillHistory.id.desc())
        .limit(1)
    )
    return level.value if level else None


async def start_or_resume(db: AsyncSession, learner_id: int, skill_id: int) -> AttemptState:
    if await db.get(Skill, skill_id) is None:
        raise NotFoundError(f"Skill {skill_id} not found")
    # One start at a time per person and skill (two taps on "Start" give one test)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:learner, :skill)"),
        {"learner": learner_id, "skill": skill_id},
    )
    in_progress = await db.scalar(
        select(TestAttempt)
        .where(
            TestAttempt.learner_id == learner_id,
            TestAttempt.skill_id == skill_id,
            TestAttempt.attempt_status == AttemptStatus.IN_PROGRESS,
            TestAttempt.test_format == "adaptive",
        )
        .order_by(TestAttempt.attempt_id.desc())
        .limit(1)
        .with_for_update()
    )
    if in_progress is not None:
        served = await _served(db, in_progress.attempt_id)
        if not _is_expired(in_progress):
            return await _state(db, in_progress, served, resumed=True)
        await _expire(db, in_progress, served)

    ready, short_by = await readiness(db, skill_id)
    if not ready:
        raise SkillNotReady(
            f"Skill {skill_id} cannot be tested yet: some levels have too few reviewed questions",
            details={
                "minimum_per_level": settings.MIN_ACTIVE_QUESTIONS_PER_LEVEL,
                "short_by": short_by,
            },
        )

    attempt = TestAttempt(
        learner_id=learner_id,
        skill_id=skill_id,
        test_format="adaptive",
        question_count=settings.ADAPTIVE_QUESTION_COUNT,
        expires_at=_now() + timedelta(minutes=settings.ATTEMPT_TIME_LIMIT_MINUTES),
        attempt_status=AttemptStatus.IN_PROGRESS,
    )
    db.add(attempt)
    await db.flush()
    start_level = await _latest_level(db, learner_id, skill_id) or settings.ADAPTIVE_START_LEVEL
    first: list[Served] = []
    await _serve_next(db, attempt, first, start_level)
    logger.info(
        "attempt_started", attempt_id=attempt.attempt_id, skill_id=skill_id, start_level=start_level
    )
    return await _state(db, attempt, first)


async def _owned_attempt(db: AsyncSession, attempt_id: int, learner_id: int) -> TestAttempt:
    attempt = await db.scalar(
        select(TestAttempt).where(TestAttempt.attempt_id == attempt_id).with_for_update()
    )
    if attempt is None:
        raise NotFoundError(f"Attempt {attempt_id} not found")
    if attempt.learner_id != learner_id:
        raise ForbiddenError(f"Attempt {attempt_id} does not belong to you")
    return attempt


async def current_state(db: AsyncSession, attempt_id: int, learner_id: int) -> AttemptState:
    attempt = await _owned_attempt(db, attempt_id, learner_id)
    served = await _served(db, attempt_id)
    if attempt.attempt_status == AttemptStatus.IN_PROGRESS and _is_expired(attempt):
        await _expire(db, attempt, served)
    return await _state(db, attempt, served)


async def answer_question(
    db: AsyncSession, attempt_id: int, learner_id: int, question_id: int, option_id: int
) -> AttemptState:
    attempt = await _owned_attempt(db, attempt_id, learner_id)
    served = await _served(db, attempt_id)
    if attempt.attempt_status == AttemptStatus.IN_PROGRESS and _is_expired(attempt):
        await _expire(db, attempt, served)
        status = STATUS_WORDS[attempt.attempt_status]
        await db.commit()  # keep the ending even though this answer is refused
        raise ExpiredError(f"The time for attempt {attempt_id} ran out", details={"status": status})
    if attempt.attempt_status != AttemptStatus.IN_PROGRESS or attempt.test_format != "adaptive":
        raise AttemptFinished(
            f"Attempt {attempt_id} is {STATUS_WORDS[attempt.attempt_status]}; start a new test"
        )
    current = next((s for s in served if s.row.answered_at is None), None)
    if current is None or current.row.question_id != question_id:
        raise NotCurrentQuestion(
            f"Question {question_id} is not the question to answer now in attempt {attempt_id}"
        )
    option = await db.get(Option, option_id)
    if option is None or option.question_id != question_id:
        raise BadRequestError(f"Option {option_id} does not belong to question {question_id}")

    current.row.selected_option_id = option_id
    current.row.is_correct = bool(option.is_correct)
    current.row.answered_at = _now()
    db.add(
        LearnerAnswer(
            attempt_id=attempt_id,
            question_id=question_id,
            selected_option_id=option_id,
            is_correct=bool(option.is_correct),
        )
    )
    await db.flush()

    answers = _answers(served)
    config = _config(attempt)
    recommendations = None
    if engine.is_finished(answers, config):
        recommendations = await _finish(db, attempt, served, "finished")
    elif await _serve_next(db, attempt, served, engine.next_level(answers, config)) is None:
        recommendations = await _finish(db, attempt, served, "finished")  # the pool ran out
    return await _state(db, attempt, served, recommendations=recommendations)


async def attempt_result(db: AsyncSession, attempt: TestAttempt) -> AttemptResult | None:
    """The result of a finished adaptive test (None for anything else)."""
    if attempt.attempt_status != AttemptStatus.COMPLETED or attempt.test_format != "adaptive":
        return None
    state = await _state(db, attempt, await _served(db, attempt.attempt_id))
    return state.result
