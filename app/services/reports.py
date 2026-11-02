"""Results and their PDF skill reports (Day 12).

- A result is a finished adaptive test: result_id is its attempt_id. Someone else's result, a
  test still running and an expired test without a result are all 404 (an id is never
  confirmed to someone it does not belong to).
- GET /results/{id}/report makes the report the first time it is asked for: a row in
  result_reports (status "generating") and a "result_report" background job in the same
  transaction. The job draws the PDF (app/services/report_pdf.py) and stores it: "ready", or
  "failed" if it could not be drawn. POST makes it again with a new version.
- A ready report carries a download link that works without a login token for
  REPORT_LINK_MINUTES (a signed token in the path, so a browser can open it directly). A link
  of an older version stops working as soon as the report is made again.
"""

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ExpiredError, NotFoundError
from app.core.logging import get_logger
from app.jobs.queue import enqueue
from app.jobs.registry import job
from app.models.history import SkillHistory
from app.models.models import (
    AttemptStatus,
    Learner,
    Skill,
    Subskill,
    SubskillRecommendation,
    TestAttempt,
)
from app.models.reports import ResultReport
from app.schemas.attempts import AttemptResult
from app.schemas.common import LevelName, Page
from app.schemas.results import (
    Report,
    ResultDetail,
    ResultRecommendation,
    ResultSummary,
    SubskillScore,
)
from app.services.report_pdf import HistoryLine, ReportData, SubskillLine, build_report_pdf
from app.services.test_taking_service import attempt_result

logger = get_logger(__name__)

JOB_KIND = "result_report"
TOKEN_TYPE = "result_report"
ALGORITHM = "HS256"
# A percentile needs something to compare with
PERCENTILE_MIN_RESULTS = 5


def catalogue_test_id(skill_id: int) -> int:
    """The test id of a skill in the catalogue (GET /roles test_ids, /tests)."""
    return 200 + skill_id


async def _owned_result(db: AsyncSession, result_id: int, learner_id: int) -> TestAttempt:
    attempt = await db.get(TestAttempt, result_id)
    if (
        attempt is None
        or attempt.learner_id != learner_id
        or attempt.test_format != "adaptive"
        or attempt.attempt_status != AttemptStatus.COMPLETED
    ):
        raise NotFoundError(f"Result {result_id} not found")
    return attempt


async def list_results(
    db: AsyncSession, learner_id: int, limit: int, offset: int
) -> Page[ResultSummary]:
    mine = SkillHistory.learner_id == learner_id
    total = await db.scalar(select(func.count()).select_from(SkillHistory).where(mine)) or 0
    rows = await db.execute(
        select(SkillHistory, Skill.skill_name)
        .join(Skill, Skill.skill_id == SkillHistory.skill_id)
        .where(mine)
        .order_by(SkillHistory.recorded_at.desc(), SkillHistory.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        ResultSummary(
            result_id=entry.attempt_id,
            attempt_id=entry.attempt_id,
            test_id=catalogue_test_id(entry.skill_id),
            skill_id=entry.skill_id,
            skill_name=skill_name,
            level=LevelName(entry.level.value),
            percentage_score=float(entry.score),
            completed_at=entry.recorded_at,
        )
        for entry, skill_name in rows.all()
    ]
    return Page[ResultSummary](items=items, total=total, limit=limit, offset=offset)


async def _percentile(db: AsyncSession, skill_id: int, score: int) -> int | None:
    same_skill = SkillHistory.skill_id == skill_id
    total = await db.scalar(select(func.count()).select_from(SkillHistory).where(same_skill)) or 0
    if total < PERCENTILE_MIN_RESULTS:
        return None
    lower = (
        await db.scalar(
            select(func.count())
            .select_from(SkillHistory)
            .where(same_skill, SkillHistory.score < score)
        )
        or 0
    )
    return round(100 * lower / total)


async def _advice(db: AsyncSession, attempt_id: int) -> list[tuple[str, str]]:
    rows = await db.execute(
        select(Subskill.subskill_name, SubskillRecommendation.recommendation_text)
        .join(Subskill, Subskill.subskill_id == SubskillRecommendation.subskill_id)
        .where(SubskillRecommendation.attempt_id == attempt_id)
        .order_by(SubskillRecommendation.priority)
    )
    return [(name, advice) for name, advice in rows.tuples().all()]


async def _result(db: AsyncSession, attempt: TestAttempt) -> AttemptResult:
    result = await attempt_result(db, attempt)
    if result is None:  # a completed adaptive test always has one
        raise NotFoundError(f"Result {attempt.attempt_id} not found")
    return result


async def result_detail(db: AsyncSession, result_id: int, learner_id: int) -> ResultDetail:
    attempt = await _owned_result(db, result_id, learner_id)
    result = await _result(db, attempt)
    skill_name = await db.scalar(select(Skill.skill_name).where(Skill.skill_id == attempt.skill_id))
    return ResultDetail(
        result_id=attempt.attempt_id,
        attempt_id=attempt.attempt_id,
        test_id=catalogue_test_id(attempt.skill_id),
        skill_id=attempt.skill_id,
        skill_name=skill_name or "",
        level=result.level,
        percentage_score=float(result.score),
        completed_at=result.completed_at,
        confidence=result.confidence,
        confidence_label=result.confidence_label,
        percentile=await _percentile(db, attempt.skill_id, result.score),
        subskills=[
            SubskillScore(
                subskill_id=s.subskill_id,
                subskill_name=s.subskill_name,
                percentage_score=s.percentage_score,
                band=s.band,
            )
            for s in result.subskills
        ],
        strengths=[s.subskill_name for s in result.strengths],
        gaps=[s.subskill_name for s in result.weaknesses],
        recommendations=[
            ResultRecommendation(subskill_name=name, text=advice, programme_id=None)
            for name, advice in await _advice(db, attempt.attempt_id)
        ],
    )


# The PDF report


def report_token(attempt_id: int, version: int) -> tuple[str, datetime]:
    expires_at = (datetime.now(UTC) + timedelta(minutes=settings.REPORT_LINK_MINUTES)).replace(
        microsecond=0
    )
    claims = {
        "typ": TOKEN_TYPE,
        "rid": attempt_id,
        "ver": version,
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=ALGORITHM), expires_at


def _report_payload(row: ResultReport, link_for: Callable[[str], str]) -> Report:
    if row.status == "ready":
        token, expires_at = report_token(row.attempt_id, row.version)
        return Report(
            result_id=row.attempt_id,
            status="ready",
            download_url=link_for(token),
            expires_at=expires_at,
            generated_at=row.generated_at,
        )
    status = "failed" if row.status == "failed" else "generating"
    return Report(
        result_id=row.attempt_id,
        status=status,
        download_url=None,
        expires_at=None,
        generated_at=None,
    )


async def _queue(db: AsyncSession, row: ResultReport) -> None:
    await enqueue(
        db,
        JOB_KIND,
        {"attempt_id": row.attempt_id, "version": row.version},
        dedupe_key=f"result-report:{row.attempt_id}:{row.version}",
    )


async def _report_row(db: AsyncSession, attempt_id: int) -> tuple[ResultReport, bool]:
    """The report row, locked; made (and its job queued) if this is the first ask."""
    created = await db.scalar(
        insert(ResultReport)
        .values(attempt_id=attempt_id)
        .on_conflict_do_nothing(index_elements=["attempt_id"])
        .returning(ResultReport.attempt_id)
    )
    row = await db.scalar(
        select(ResultReport)
        .where(ResultReport.attempt_id == attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    if created is not None:
        await _queue(db, row)
    return row, created is not None


async def report_status(
    db: AsyncSession, result_id: int, learner_id: int, link_for: Callable[[str], str]
) -> Report:
    await _owned_result(db, result_id, learner_id)
    row, _ = await _report_row(db, result_id)
    return _report_payload(row, link_for)


async def make_report_again(
    db: AsyncSession, result_id: int, learner_id: int, link_for: Callable[[str], str]
) -> Report:
    await _owned_result(db, result_id, learner_id)
    row, created = await _report_row(db, result_id)
    if not created and row.status != "generating":
        row.version += 1
        row.status = "generating"
        row.pdf = None
        row.error = None
        row.generated_at = None
        row.requested_at = datetime.now(UTC)
        await db.flush()
        await _queue(db, row)
    return _report_payload(row, link_for)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "skill"


async def report_download(db: AsyncSession, token: str) -> tuple[bytes, str]:
    """The PDF and its file name for a valid download link; 410 for any other link."""
    gone = ExpiredError("This report link has expired: ask for the report again")
    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if claims.get("typ") != TOKEN_TYPE:
            raise gone
        attempt_id, version = int(claims["rid"]), int(claims["ver"])
    except (JWTError, KeyError, TypeError, ValueError):
        raise gone from None
    row = await db.get(ResultReport, attempt_id)
    if row is None or row.version != version or row.status != "ready" or row.pdf is None:
        raise gone
    skill_name = await db.scalar(
        select(Skill.skill_name)
        .join(TestAttempt, TestAttempt.skill_id == Skill.skill_id)
        .where(TestAttempt.attempt_id == attempt_id)
    )
    return row.pdf, f"careerline-{_slug(skill_name or '')}-result-{attempt_id}.pdf"


async def report_data(db: AsyncSession, attempt: TestAttempt) -> ReportData:
    result = await _result(db, attempt)
    person = await db.scalar(
        select(Learner.full_name).where(Learner.learner_id == attempt.learner_id)
    )
    skill_name = await db.scalar(select(Skill.skill_name).where(Skill.skill_id == attempt.skill_id))
    history = await db.execute(
        select(SkillHistory.recorded_at, SkillHistory.level, SkillHistory.score)
        .where(
            SkillHistory.learner_id == attempt.learner_id,
            SkillHistory.skill_id == attempt.skill_id,
            SkillHistory.recorded_at <= result.completed_at,
        )
        .order_by(SkillHistory.recorded_at, SkillHistory.id)
    )
    return ReportData(
        result_id=attempt.attempt_id,
        person=person or "",
        skill_name=skill_name or "",
        level=result.level.value,
        score=result.score,
        confidence_label=result.confidence_label,
        answered=result.answered,
        correct=result.correct,
        completed_at=result.completed_at,
        subskills=[
            SubskillLine(s.subskill_name, s.answered, s.correct, s.percentage_score, s.band)
            for s in result.subskills
        ],
        strengths=[s.subskill_name for s in result.strengths],
        weaknesses=[s.subskill_name for s in result.weaknesses],
        advice=await _advice(db, attempt.attempt_id),
        history=[HistoryLine(at, level.value, score) for at, level, score in history.all()],
    )


@job(JOB_KIND)
async def make_result_report(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Draw and store one version of a report. A job for an older version does nothing."""
    attempt_id, version = int(payload["attempt_id"]), int(payload["version"])
    row = await session.scalar(
        select(ResultReport).where(ResultReport.attempt_id == attempt_id).with_for_update()
    )
    if row is None or row.version != version or row.status != "generating":
        return
    attempt = await session.get(TestAttempt, attempt_id)
    if attempt is None:
        return
    data = await report_data(session, attempt)
    try:
        pdf = await asyncio.to_thread(build_report_pdf, data)
    except Exception as exc:
        # Drawing again would fail the same way: the person sees "failed" and can ask again
        row.status = "failed"
        row.error = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning("result_report_failed", attempt_id=attempt_id, error=type(exc).__name__)
        return
    row.pdf = pdf
    row.status = "ready"
    row.generated_at = datetime.now(UTC)
    logger.info("result_report_ready", attempt_id=attempt_id, version=version, bytes=len(pdf))
