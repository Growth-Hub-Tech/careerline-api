"""Privacy (Day 18, NDPR / GDPR): consents, a copy of my data, and deleting my account.

Consents
- Five keys (marketing_emails, share_profile_with_recruiters, product_research, and since Day 31
  aux_hr_sharing and incubate_sharing), all off until the person turns them on. Every change is stored in consent_events with its time; setting a
  consent to what it already is records nothing.

A copy of my data
- POST queues a background job (one export at a time: asking again while one is queued, or
  while a ready one has not expired, gives that one). The job writes one JSON file with
  everything held about the person (account, profile, consents and their history, behavioural answers,
  every test with its answers and result, skill history, beginner-path intakes, payments,
  subscriptions, credits, programme clicks, organisations, sign-in sessions, contact messages) and emails them
  that it is ready (the email points at the website, never at the file).
- GET gives a download link that works DATA_EXPORT_LINK_MINUTES without a login (the signed
  token is the proof); a fresh one on every GET. After DATA_EXPORT_DAYS the file is emptied and
  the export and its links answer 410.

Deleting my account
- Needs the password. Scheduled ACCOUNT_DELETION_GRACE_DAYS ahead (a background job waits for
  that moment) and can be cancelled until then; the account keeps working meanwhile.
- When it is carried out: the person's name, email, phone and password are replaced, the
  account is switched off, every session ends, and their profile, consents, intakes, behavioural
  answers, exports, programme clicks, organisation memberships, PDF reports, contact messages,
  emails and test-mailbox messages are deleted, and Paystack's copies of their payment events
  are emptied; a subscription is cancelled at once and its saved card forgotten, so it is never
  charged again. What stays, with no way back to the person: test attempts and their scores (so
  everyone else's percentiles do not move) and payments and credit records (kept for the
  accounts, as the law requires).
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ExpiredError, NotFoundError
from app.core.logging import get_logger
from app.core.security import ALGORITHM, verify_password
from app.email.outbox import send_email
from app.jobs.queue import enqueue
from app.jobs.registry import job
from app.models.accounts import AccountToken, AuthSession
from app.models.beginner import BeginnerIntake
from app.models.contact import ContactMessage
from app.models.email import EmailOutbox, TestMailboxMessage
from app.models.history import SkillHistory
from app.models.models import (
    AttemptQuestion,
    Learner,
    LearnerProfile,
    LearnerStatus,
    Option,
    Question,
    Skill,
    TestAttempt,
)
from app.models.organisations import Organisation, OrganisationMember
from app.models.payments import CreditTransaction, Payment, PaystackEvent
from app.models.privacy import (
    CONSENT_KEYS,
    AccountDeletion,
    ConsentEvent,
    DataExport,
    LearnerConsent,
)
from app.models.profiles import PersonProfile
from app.models.programmes import ProgrammeClick
from app.models.reports import ResultReport
from app.models.subscriptions import Subscription, SubscriptionPlan
from app.schemas.privacy import AccountDeletion as AccountDeletionOut
from app.schemas.privacy import (
    AccountDeletionRequest,
    Consent,
    Consents,
    ConsentUpdate,
)
from app.schemas.privacy import DataExport as DataExportOut
from app.services.account_service import WrongPasswordError
from app.services.session_service import revoke_all_sessions

logger = get_logger(__name__)

EXPORT_JOB = "privacy.data_export"
ERASE_JOB = "privacy.erase_account"
TOKEN_TYPE = "data_export"
DELETED_NAME = "Deleted account"
PRIVACY_PAGE = "/settings/privacy"


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return _now()


def _iso(value: Any) -> str | None:
    return _aware(value).isoformat() if isinstance(value, datetime) else None


# ---------- consents ----------


async def my_consents(db: AsyncSession, learner: Learner) -> Consents:
    rows = {
        c.key: c
        for c in await db.scalars(
            select(LearnerConsent).where(LearnerConsent.learner_id == learner.learner_id)
        )
    }
    since = _aware(learner.created_at)
    return Consents(
        items=[
            Consent(
                key=key,
                granted=rows[key].granted if key in rows else False,
                updated_at=_aware(rows[key].updated_at) if key in rows else since,
            )
            for key in CONSENT_KEYS
        ]
    )


async def update_consents(db: AsyncSession, learner: Learner, data: ConsentUpdate) -> Consents:
    changes = {item.key: item.granted for item in data.items}  # the last one for a key wins
    for key, granted in changes.items():
        row = await db.get(LearnerConsent, (learner.learner_id, key), with_for_update=True)
        current = row.granted if row is not None else False
        if row is not None and current == granted:
            continue
        if row is None and not granted:
            continue  # off is the default: nothing changes
        now = _now()
        if row is None:
            db.add(
                LearnerConsent(
                    learner_id=learner.learner_id, key=key, granted=granted, updated_at=now
                )
            )
        else:
            row.granted, row.updated_at = granted, now
        db.add(
            ConsentEvent(learner_id=learner.learner_id, key=key, granted=granted, created_at=now)
        )
    await db.flush()
    return await my_consents(db, learner)


async def has_consent(db: AsyncSession, learner_id: int, key: str) -> bool:
    row = await db.get(LearnerConsent, (learner_id, key))
    return bool(row and row.granted)


# ---------- a copy of my data ----------


def export_token(export_id: int) -> tuple[str, datetime]:
    expires_at = (_now() + timedelta(minutes=settings.DATA_EXPORT_LINK_MINUTES)).replace(
        microsecond=0
    )
    claims = {"typ": TOKEN_TYPE, "eid": export_id, "exp": int(expires_at.timestamp())}
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=ALGORITHM), expires_at


def _expired(row: DataExport) -> bool:
    return row.status == "ready" and row.expires_at is not None and _aware(row.expires_at) <= _now()


def _export_out(row: DataExport, link_for: Any) -> DataExportOut:
    if row.status == "ready":
        token, _ = export_token(row.id)
        return DataExportOut(
            export_id=row.id,
            status="ready",
            requested_at=_aware(row.requested_at),
            download_url=link_for(token),
            expires_at=_aware(row.expires_at),
        )
    return DataExportOut(
        export_id=row.id,
        status="queued",
        requested_at=_aware(row.requested_at),
        download_url=None,
        expires_at=None,
    )


async def request_export(db: AsyncSession, learner_id: int, link_for: Any) -> DataExportOut:
    # one at a time per person
    await db.execute(
        select(Learner.learner_id).where(Learner.learner_id == learner_id).with_for_update()
    )
    current = await db.scalar(
        select(DataExport)
        .where(DataExport.learner_id == learner_id, DataExport.status.in_(("queued", "ready")))
        .order_by(DataExport.requested_at.desc(), DataExport.id.desc())
        .limit(1)
    )
    if current is not None and not _expired(current):
        return _export_out(current, link_for)
    row = DataExport(learner_id=learner_id, status="queued", requested_at=_now())
    db.add(row)
    await db.flush()
    await enqueue(db, EXPORT_JOB, {"export_id": row.id}, dedupe_key=f"data-export:{row.id}")
    logger.info("data_export_requested", export_id=row.id, learner_id=learner_id)
    return _export_out(row, link_for)


async def _own_export(db: AsyncSession, export_id: int, learner_id: int) -> DataExport:
    row = await db.get(DataExport, export_id)
    if row is None or row.learner_id != learner_id:
        raise NotFoundError(f"Data export {export_id} not found")
    if _expired(row):
        row.content = None
        raise ExpiredError("This copy of your data has expired: ask for a new one")
    return row


async def get_export(
    db: AsyncSession, export_id: int, learner_id: int, link_for: Any
) -> DataExportOut:
    return _export_out(await _own_export(db, export_id, learner_id), link_for)


async def export_download(db: AsyncSession, token: str) -> tuple[bytes, str]:
    gone = ExpiredError("This download link has expired: open your privacy page for a new one")
    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if claims.get("typ") != TOKEN_TYPE:
            raise gone
        export_id = int(claims["eid"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise gone from None
    row = await db.get(DataExport, export_id)
    if row is None or row.status != "ready" or row.content is None or _expired(row):
        raise gone
    return row.content, f"careerline-my-data-{export_id}.json"


async def build_export(db: AsyncSession, learner_id: int) -> dict[str, Any]:
    """Everything held about one person, as plain JSON (never a password hash)."""
    learner = await db.get(Learner, learner_id)
    assert learner is not None
    out: dict[str, Any] = {
        "generated_at": _now().isoformat(),
        "account": {
            "learner_id": learner.learner_id,
            "full_name": learner.full_name,
            "email": learner.email,
            "phone_number": learner.phone_number,
            "email_verified_at": _iso(learner.email_verified_at),
            "registered_at": _iso(learner.created_at),
            "status": learner.learner_status.value if learner.learner_status else None,
        },
    }
    out["consents"] = [c.model_dump(mode="json") for c in (await my_consents(db, learner)).items]
    out["consent_history"] = [
        {"key": e.key, "granted": e.granted, "at": _iso(e.created_at)}
        for e in await db.scalars(
            select(ConsentEvent)
            .where(ConsentEvent.learner_id == learner_id)
            .order_by(ConsentEvent.id)
        )
    ]
    out["behavioural_answers"] = [
        {"question_id": p.question_id, "answer": p.answer_text, "at": _iso(p.created_at)}
        for p in await db.scalars(
            select(LearnerProfile)
            .where(LearnerProfile.learner_id == learner_id)
            .order_by(LearnerProfile.profile_id)
        )
    ]
    skills: dict[int, str] = {
        sid: name
        for sid, name in (await db.execute(select(Skill.skill_id, Skill.skill_name))).all()
    }
    history = {
        h.attempt_id: h
        for h in await db.scalars(select(SkillHistory).where(SkillHistory.learner_id == learner_id))
    }
    tests = []
    for attempt in await db.scalars(
        select(TestAttempt)
        .where(TestAttempt.learner_id == learner_id)
        .order_by(TestAttempt.attempt_id)
    ):
        answers = []
        for served, question_text, option_text in (
            await db.execute(
                select(AttemptQuestion, Question.question_text, Option.option_text)
                .join(Question, Question.question_id == AttemptQuestion.question_id)
                .outerjoin(Option, Option.option_id == AttemptQuestion.selected_option_id)
                .where(AttemptQuestion.attempt_id == attempt.attempt_id)
                .order_by(AttemptQuestion.position)
            )
        ).all():
            answers.append(
                {
                    "position": served.position,
                    "question": question_text,
                    "your_answer": option_text,
                    "correct": served.is_correct,
                    "answered_at": _iso(served.answered_at),
                }
            )
        h = history.get(attempt.attempt_id)
        tests.append(
            {
                "attempt_id": attempt.attempt_id,
                "skill": skills.get(attempt.skill_id),
                "status": attempt.attempt_status.value if attempt.attempt_status else None,
                "started_at": _iso(attempt.start_time),
                "ended_at": _iso(attempt.end_time),
                "answers": answers,
                "result": {"level": h.level.value, "score": h.score} if h else None,
            }
        )
    out["tests"] = tests
    out["skill_history"] = [
        {
            "skill": skills.get(h.skill_id),
            "level": h.level.value,
            "score": h.score,
            "at": _iso(h.recorded_at),
        }
        for h in sorted(history.values(), key=lambda h: h.id)
    ]
    out["beginner_intakes"] = [
        {
            "submitted_at": _iso(i.submitted_at),
            "answers": i.answers,
            "career_paths": i.recommendations,
        }
        for i in await db.scalars(
            select(BeginnerIntake)
            .where(BeginnerIntake.learner_id == learner_id)
            .order_by(BeginnerIntake.id)
        )
    ]
    out["payments"] = [
        {
            "reference": p.reference,
            "description": p.description,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "created_at": _iso(p.created_at),
            "paid_at": _iso(p.paid_at),
        }
        for p in await db.scalars(
            select(Payment).where(Payment.learner_id == learner_id).order_by(Payment.id)
        )
    ]
    person = await db.get(PersonProfile, learner_id)
    out["profile"] = (
        {
            "headline": person.headline,
            "location": person.location,
            "current_role": person.current_role,
            "years_experience": person.years_experience,
            "goals": list(person.goals or []),
            "weekly_hours": person.weekly_hours,
            "budget": person.budget,
            "linkedin_url": person.linkedin_url,
            "updated_at": _iso(person.updated_at),
        }
        if person
        else None
    )
    out["subscriptions"] = [
        {
            "plan_name": plan_name,
            "status": sub.status,
            "current_period_start": _iso(sub.current_period_start),
            "current_period_end": _iso(sub.current_period_end),
            "cancel_at_period_end": sub.cancel_at_period_end,
            "created_at": _iso(sub.created_at),
        }
        for sub, plan_name in (
            await db.execute(
                select(Subscription, SubscriptionPlan.name)
                .join(SubscriptionPlan, SubscriptionPlan.plan_id == Subscription.plan_id)
                .where(Subscription.learner_id == learner_id)
                .order_by(Subscription.id)
            )
        ).all()
    ]
    out["credit_transactions"] = [
        {
            "change": t.change,
            "reason": t.reason,
            "balance_after": t.balance_after,
            "at": _iso(t.created_at),
        }
        for t in await db.scalars(
            select(CreditTransaction)
            .where(CreditTransaction.learner_id == learner_id)
            .order_by(CreditTransaction.id)
        )
    ]
    out["programme_clicks"] = [
        {"programme_id": c.programme_id, "source": c.source, "at": _iso(c.clicked_at)}
        for c in await db.scalars(
            select(ProgrammeClick)
            .where(ProgrammeClick.learner_id == learner_id)
            .order_by(ProgrammeClick.id)
        )
    ]
    out["organisations"] = [
        {"organisation": name, "role": member.role, "since": _iso(member.created_at)}
        for member, name in (
            await db.execute(
                select(OrganisationMember, Organisation.name)
                .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
                .where(OrganisationMember.learner_id == learner_id)
            )
        ).all()
    ]
    out["sign_in_sessions"] = [
        {
            "started_at": _iso(s.created_at),
            "ended_at": _iso(s.revoked_at),
            "device": s.user_agent,
        }
        for s in await db.scalars(
            select(AuthSession)
            .where(AuthSession.learner_id == learner_id)
            .order_by(AuthSession.created_at)
        )
    ]
    out["contact_messages"] = [
        {"ticket_id": m.ticket_id, "topic": m.topic, "message": m.message, "at": _iso(m.created_at)}
        for m in await db.scalars(
            select(ContactMessage)
            .where(ContactMessage.email == learner.email)
            .order_by(ContactMessage.id)
        )
    ]
    return out


@job(EXPORT_JOB)
async def make_data_export(session: AsyncSession, payload: dict[str, Any]) -> None:
    row = await session.scalar(
        select(DataExport).where(DataExport.id == int(payload["export_id"])).with_for_update()
    )
    if row is None or row.status != "queued":
        return
    data = await build_export(session, row.learner_id)
    row.content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    row.status = "ready"
    row.ready_at = _now()
    row.expires_at = row.ready_at + timedelta(days=settings.DATA_EXPORT_DAYS)
    learner = await session.get(Learner, row.learner_id)
    if learner is not None:
        await send_email(
            session,
            to=learner.email,
            template="data_export_ready",
            context={
                "full_name": learner.full_name,
                "link": settings.FRONTEND_URL.rstrip("/") + PRIVACY_PAGE,
                "days": settings.DATA_EXPORT_DAYS,
            },
            dedupe_key=f"data-export:{row.id}:ready",
        )
    logger.info("data_export_ready", export_id=row.id)


# ---------- deleting my account ----------


def _deletion_out(row: AccountDeletion) -> AccountDeletionOut:
    return AccountDeletionOut(
        status="scheduled" if row.status == "scheduled" else "cancelled",
        requested_at=_aware(row.requested_at),
        scheduled_for=_aware(row.scheduled_for) if row.status == "scheduled" else None,
    )


async def request_deletion(
    db: AsyncSession, learner: Learner, data: AccountDeletionRequest
) -> AccountDeletionOut:
    # Argon2 takes a while: in a thread, so the server keeps answering other requests meanwhile
    if not await asyncio.to_thread(verify_password, data.password, learner.hashed_password):
        raise WrongPasswordError("The password is not right")
    row = await db.get(AccountDeletion, learner.learner_id, with_for_update=True)
    if row is not None and row.status == "scheduled":
        return _deletion_out(row)
    now = _now().replace(microsecond=0)
    when = now + timedelta(days=settings.ACCOUNT_DELETION_GRACE_DAYS)
    if row is None:
        row = AccountDeletion(
            learner_id=learner.learner_id, status="scheduled", requested_at=now, scheduled_for=when
        )
        db.add(row)
    else:
        row.status, row.requested_at, row.scheduled_for = "scheduled", now, when
        row.cancelled_at = None
    row.reason = data.reason
    await db.flush()
    await enqueue(
        db,
        ERASE_JOB,
        {"learner_id": learner.learner_id, "requested_at": now.isoformat()},
        dedupe_key=f"erase:{learner.learner_id}:{int(now.timestamp())}",
        run_after=when,
    )
    await send_email(
        db,
        to=learner.email,
        template="account_deletion_scheduled",
        context={
            "full_name": learner.full_name,
            "deletion_date": when.strftime("%d %b %Y"),
            "link": settings.FRONTEND_URL.rstrip("/") + PRIVACY_PAGE,
        },
        dedupe_key=f"erase:{learner.learner_id}:{int(now.timestamp())}:email",
    )
    logger.info("account_deletion_scheduled", learner_id=learner.learner_id)
    return _deletion_out(row)


async def deletion_status(db: AsyncSession, learner_id: int) -> AccountDeletionOut:
    row = await db.get(AccountDeletion, learner_id)
    if row is None or row.status == "completed":
        raise NotFoundError("You have not asked to delete your account")
    return _deletion_out(row)


async def cancel_deletion(db: AsyncSession, learner_id: int) -> AccountDeletionOut:
    row = await db.get(AccountDeletion, learner_id, with_for_update=True)
    if row is None or row.status != "scheduled":
        raise NotFoundError("There is no account deletion to cancel")
    row.status, row.cancelled_at = "cancelled", _now()
    await db.flush()
    logger.info("account_deletion_cancelled", learner_id=learner_id)
    return _deletion_out(row)


async def erase_learner(db: AsyncSession, learner_id: int) -> None:
    learner = await db.get(Learner, learner_id, with_for_update=True)
    if learner is None:
        return
    email = learner.email
    references = list(
        await db.scalars(select(Payment.reference).where(Payment.learner_id == learner_id))
    )
    attempt_ids = select(TestAttempt.attempt_id).where(TestAttempt.learner_id == learner_id)
    await revoke_all_sessions(db, learner_id, "account_deleted")
    for model in (
        AuthSession,
        AccountToken,
        LearnerConsent,
        ConsentEvent,
        BeginnerIntake,
        DataExport,
        ProgrammeClick,
        OrganisationMember,
        LearnerProfile,
        PersonProfile,
    ):
        await db.execute(delete(model).where(model.learner_id == learner_id))
    await db.execute(delete(ResultReport).where(ResultReport.attempt_id.in_(attempt_ids)))
    await db.execute(delete(ContactMessage).where(ContactMessage.email == email))
    await db.execute(delete(EmailOutbox).where(EmailOutbox.to_email == email))
    await db.execute(delete(TestMailboxMessage).where(TestMailboxMessage.to_email == email))
    if references:
        await db.execute(
            update(PaystackEvent)
            .where(or_(PaystackEvent.reference.in_(references)))
            .values(payload={"erased": True})
        )
    # a plan is never charged again: cancelled now, the saved card forgotten
    await db.execute(
        update(Subscription)
        .where(Subscription.learner_id == learner_id)
        .values(
            status="cancelled",
            cancel_at_period_end=True,
            authorization_code=None,
            cancelled_at=func.coalesce(Subscription.cancelled_at, func.now()),
            updated_at=func.now(),
        )
    )
    learner.full_name = DELETED_NAME
    learner.email = f"deleted-{learner_id}-{uuid.uuid4().hex[:8]}@deleted.invalid"
    learner.phone_number = None  # type: ignore[assignment]
    learner.hashed_password = None  # type: ignore[assignment]
    learner.email_verified_at = None
    learner.learner_status = LearnerStatus.INACTIVE
    await db.flush()


@job(ERASE_JOB)
async def erase_account(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Carry out a deletion that is due. A cancelled or newer request makes this job do nothing."""
    learner_id = int(payload["learner_id"])
    row = await session.get(AccountDeletion, learner_id, with_for_update=True)
    if row is None or row.status != "scheduled" or _aware(row.scheduled_for) > _now():
        return
    if _aware(row.requested_at).isoformat() != payload.get("requested_at"):
        return  # an older request that was cancelled and asked again: its own job will run
    await erase_learner(session, learner_id)
    row.status, row.completed_at, row.reason = "completed", _now(), None
    logger.info("account_erased", learner_id=learner_id)
