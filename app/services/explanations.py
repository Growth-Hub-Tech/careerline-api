"""Explanations of a finished test's answers (Day 11).

- GET /attempts/{id}/review shows each served question with the right answer, the person's
  choice and an explanation, and only once the test is over: nothing about the answers is
  shown while it is running.
- The AI explanation of a question is asked once, in a background job ("answer_explanations"),
  and kept in question_explanations for everyone who gets that question. A kept explanation
  counts only while the question, its options and its right answer are unchanged
  (question_digest).
- Without OPENAI_API_KEY, while the job is still working, or when the AI fails, the item shows
  the standard explanation (plain text built from the right answer and the choice).
- The job is queued when a test ends, and again by the review when questions are missing an
  explanation (e.g. a question was reworded). Its dedupe key names the missing questions, so the
  same gap is asked about once.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.integrations import openai_client
from app.jobs.queue import enqueue
from app.jobs.registry import job
from app.models.explanations import QuestionExplanation
from app.models.models import (
    AttemptQuestion,
    AttemptStatus,
    Option,
    Question,
    Skill,
    Subskill,
    TestAttempt,
)
from app.repositories.attempt_repo import get_options_for_question
from app.schemas.attempts import AttemptReview, ReviewItem, ReviewOption

logger = get_logger(__name__)

JOB_KIND = "answer_explanations"
REVIEW_STATUS = {
    AttemptStatus.COMPLETED: "completed",
    AttemptStatus.EXPIRED: "expired",
    AttemptStatus.CANCELLED: "cancelled",
    AttemptStatus.PASSED: "completed",  # the retired fixed test
    AttemptStatus.FAILED: "completed",
}


class AttemptNotFinished(ConflictError):
    code = "attempt_not_finished"


def ai_enabled() -> bool:
    return bool(settings.OPENAI_API_KEY)


def standard_explanation(
    correct_text: str, chosen_text: str | None, is_correct: bool, subskill_name: str
) -> str:
    if chosen_text is None:
        return f'Not answered before the test ended. The correct answer is "{correct_text}".'
    if is_correct:
        return f'Correct: "{correct_text}" is the right answer.'
    return (
        f'The correct answer is "{correct_text}"; you chose "{chosen_text}". '
        f"Review {subskill_name} to see why."
    )


def question_digest(question_text: str, options: list[tuple[str, bool]]) -> str:
    """A fingerprint of a question, its options and which one is right."""
    canonical = json.dumps([question_text, sorted(options)], ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class _Question:
    position: int
    row: AttemptQuestion
    question: Question
    subskill_name: str
    options: list[Option]  # in the order they were shown
    digest: str

    @property
    def correct(self) -> Option | None:
        return next((o for o in self.options if o.is_correct), None)


async def _questions(db: AsyncSession, attempt_id: int) -> list[_Question]:
    rows = (
        await db.execute(
            select(AttemptQuestion, Question, Subskill.subskill_name)
            .join(Question, Question.question_id == AttemptQuestion.question_id)
            .join(Subskill, Subskill.subskill_id == Question.subskill_id)
            .where(AttemptQuestion.attempt_id == attempt_id)
            .order_by(AttemptQuestion.position)
        )
    ).all()
    ids = [question.question_id for _, question, _ in rows]
    by_question: dict[int, dict[int, Option]] = {}
    if ids:
        for option in (await db.scalars(select(Option).where(Option.question_id.in_(ids)))).all():
            by_question.setdefault(option.question_id, {})[option.option_id] = option
    questions = []
    for row, question, subskill_name in rows:
        options = by_question.get(question.question_id, {})
        # The same order as when the question was served
        shown = await get_options_for_question(db, question.question_id, attempt_id)
        ordered = [options[o["option_id"]] for o in shown if o["option_id"] in options]
        digest = question_digest(
            question.question_text, [(o.option_text, bool(o.is_correct)) for o in ordered]
        )
        questions.append(_Question(row.position, row, question, subskill_name, ordered, digest))
    return questions


async def _kept(db: AsyncSession, questions: list[_Question]) -> dict[int, str]:
    """The kept AI explanations that still match their question."""
    if not questions:
        return {}
    digests = {q.question.question_id: q.digest for q in questions}
    rows = await db.scalars(
        select(QuestionExplanation).where(QuestionExplanation.question_id.in_(digests))
    )
    return {
        row.question_id: row.explanation
        for row in rows.all()
        if digests.get(row.question_id) == row.question_digest
    }


def _dedupe_key(attempt_id: int, missing: list[_Question]) -> str:
    gap = hashlib.sha256(
        ",".join(f"{q.question.question_id}:{q.digest}" for q in missing).encode()
    ).hexdigest()[:16]
    return f"answer-explanations:attempt:{attempt_id}:{gap}"


async def _ai_status(
    db: AsyncSession, attempt_id: int, questions: list[_Question], kept: dict[int, str]
) -> str:
    """ready / generating / unavailable; queues the job when a gap has not been asked about."""
    missing = [q for q in questions if q.question.question_id not in kept and q.correct]
    if not missing:
        return "ready" if questions else "unavailable"
    if not ai_enabled():
        return "unavailable"
    key = _dedupe_key(attempt_id, missing)
    status = await db.scalar(
        text("SELECT status FROM background_jobs WHERE dedupe_key = :key"), {"key": key}
    )
    if status is None:
        await enqueue(db, JOB_KIND, {"attempt_id": attempt_id}, dedupe_key=key)
        return "generating"
    return "generating" if status in ("queued", "running") else "unavailable"


async def queue_explanations(db: AsyncSession, attempt_id: int) -> None:
    """Called when a test ends (same transaction): ask for the missing explanations."""
    if not ai_enabled():
        return
    questions = await _questions(db, attempt_id)
    await _ai_status(db, attempt_id, questions, await _kept(db, questions))


async def attempt_review(db: AsyncSession, attempt_id: int, learner_id: int) -> AttemptReview:
    # Imported here: test_taking_service queues this module's job when a test ends
    from app.services import test_taking_service as test_taking

    attempt = await db.scalar(
        select(TestAttempt).where(TestAttempt.attempt_id == attempt_id).with_for_update()
    )
    if attempt is None:
        raise NotFoundError(f"Attempt {attempt_id} not found")
    if attempt.learner_id != learner_id:
        raise ForbiddenError(f"Attempt {attempt_id} does not belong to you")
    if attempt.attempt_status == AttemptStatus.IN_PROGRESS and test_taking.is_expired(attempt):
        await test_taking.expire(db, attempt)
    if attempt.attempt_status == AttemptStatus.IN_PROGRESS:
        raise AttemptNotFinished(
            f"Attempt {attempt_id} is still in progress: the answers are shown when it ends"
        )

    questions = await _questions(db, attempt_id)
    kept = await _kept(db, questions)
    items = []
    for q in questions:
        correct = q.correct
        chosen = next((o for o in q.options if o.option_id == q.row.selected_option_id), None)
        is_correct = bool(chosen is not None and chosen.is_correct)
        explanation = kept.get(q.question.question_id)
        items.append(
            ReviewItem(
                position=q.position,
                question_id=q.question.question_id,
                question_text=q.question.question_text,
                subskill_id=q.question.subskill_id,
                subskill_name=q.subskill_name,
                level=q.row.level,
                options=[
                    ReviewOption(
                        option_id=o.option_id,
                        option_text=o.option_text,
                        is_correct=bool(o.is_correct),
                        chosen=chosen is not None and o.option_id == chosen.option_id,
                    )
                    for o in q.options
                ],
                selected_option_id=chosen.option_id if chosen else None,
                correct_option_id=correct.option_id if correct else None,
                is_correct=is_correct,
                explanation=explanation
                or standard_explanation(
                    correct.option_text if correct else "",
                    chosen.option_text if chosen else None,
                    is_correct,
                    q.subskill_name,
                ),
                explanation_source="ai" if explanation else "standard",
            )
        )
    return AttemptReview(
        attempt_id=attempt.attempt_id,
        skill_id=attempt.skill_id,
        status=REVIEW_STATUS[attempt.attempt_status],
        result=await test_taking.attempt_result(db, attempt),
        ai_explanations=await _ai_status(db, attempt_id, questions, kept),
        items=items,
    )


@job(JOB_KIND)
async def explain_answers(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Ask the AI about each question of the attempt that has no matching kept explanation.
    Safe to run twice: it checks first and overwrites a stale one."""
    attempt_id = int(payload["attempt_id"])
    attempt = await session.get(TestAttempt, attempt_id)
    if attempt is None:
        return
    skill_name = await session.scalar(
        select(Skill.skill_name).where(Skill.skill_id == attempt.skill_id)
    )
    questions = await _questions(session, attempt_id)
    kept = await _kept(session, questions)
    added = 0
    for q in questions:
        correct = q.correct
        if q.question.question_id in kept or correct is None:
            continue
        explanation = await asyncio.to_thread(
            openai_client.explain_answer,
            skill_name or "",
            q.subskill_name,
            q.question.question_text,
            [o.option_text for o in q.options],
            correct.option_text,
        )
        if not explanation:
            continue  # the standard explanation stays
        values = {
            "explanation": explanation,
            "question_digest": q.digest,
            "model": settings.OPENAI_EXPLANATION_MODEL,
        }
        await session.execute(
            insert(QuestionExplanation)
            .values(question_id=q.question.question_id, **values)
            .on_conflict_do_update(
                index_elements=["question_id"], set_={**values, "created_at": text("now()")}
            )
        )
        kept[q.question.question_id] = explanation
        added += 1
    logger.info("answer_explanations_saved", attempt_id=attempt_id, added=added)
