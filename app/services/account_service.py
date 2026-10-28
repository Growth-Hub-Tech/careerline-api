"""Real accounts (Day 6): sign-up, email confirmation, sign-in, password change and reset.

Never tells whether an email has an account: sign-in answers the same 401 (after the same
password-hash work) for an unknown email and a wrong password, the sign-in limit is per email
address whether or not it exists, and "forgot password" always answers 202 and does the lookup
in a background job.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ExpiredError,
    RateLimitedError,
    UnauthorizedError,
)
from app.core.logging import get_logger
from app.core.security import (
    burn_password_check,
    hash_one_time_token,
    hash_password,
    needs_rehash,
    new_one_time_token,
    verify_password,
)
from app.db.session import AsyncSessionLocal
from app.email.outbox import send_email
from app.jobs.queue import enqueue
from app.jobs.registry import job
from app.models.accounts import AccountToken
from app.models.models import Learner, LearnerStatus
from app.schemas.auth import RegisterRequest
from app.services.session_service import revoke_all_sessions, start_session

logger = get_logger(__name__)

VERIFY_EMAIL = "verify_email"
PASSWORD_RESET = "password_reset"
RESET_JOB = "password_reset_request"
RESETS_PER_EMAIL_PER_HOUR = 3
RESETS_PER_IP_PER_HOUR = 10
RESENDS_PER_HOUR = 3

INVALID_LOGIN = "Invalid email or password"
EXPIRED_LINK = "This link has expired or was already used. Ask for a new one."


class EmailTakenError(BadRequestError):
    pass


class WrongPasswordError(BadRequestError):
    code = "wrong_password"


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def find_learner_by_email(db: AsyncSession, email: str) -> Learner | None:
    """Case-insensitive. Accounts from before Day 6 may have capitals in their email."""
    email = normalise_email(email)
    return (
        await db.scalars(
            select(Learner)
            .where(func.lower(Learner.email) == email)
            .order_by(case((Learner.email == email, 0), else_=1), Learner.learner_id)
            .limit(1)
        )
    ).first()


def _link(path: str, token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}?token={token}"


async def issue_token(db: AsyncSession, learner: Learner, purpose: str, lifetime: timedelta) -> str:
    """A new single-use token; any older unused token for the same purpose stops working."""
    now = datetime.now(UTC)
    await db.execute(
        update(AccountToken)
        .where(
            AccountToken.learner_id == learner.learner_id,
            AccountToken.purpose == purpose,
            AccountToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    token, token_hash = new_one_time_token()
    db.add(
        AccountToken(
            learner_id=learner.learner_id,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=now + lifetime,
        )
    )
    return token


async def use_token(db: AsyncSession, token: str, purpose: str) -> AccountToken:
    """Spend a token: it must exist, have this purpose, be unused and unexpired (else 410)."""
    row = await db.scalar(
        select(AccountToken)
        .where(
            AccountToken.token_hash == hash_one_time_token(token),
            AccountToken.purpose == purpose,
            AccountToken.used_at.is_(None),
            AccountToken.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if row is None:
        raise ExpiredError(EXPIRED_LINK)
    row.used_at = datetime.now(UTC)
    return row


async def send_verification_email(db: AsyncSession, learner: Learner) -> None:
    hours = settings.VERIFY_EMAIL_TOKEN_HOURS
    token = await issue_token(db, learner, VERIFY_EMAIL, timedelta(hours=hours))
    await send_email(
        db,
        to=learner.email,
        template="verify_email",
        context={
            "full_name": learner.full_name,
            "link": _link("/verify-email", token),
            "hours": hours,
        },
    )


async def _send_password_changed(db: AsyncSession, learner: Learner) -> None:
    await send_email(
        db,
        to=learner.email,
        template="password_changed",
        context={
            "full_name": learner.full_name,
            "changed_at": f"{datetime.now(UTC):%d %b %Y, %H:%M} UTC",
            "reset_link": f"{settings.FRONTEND_URL.rstrip('/')}/forgot-password",
        },
    )


def _limited(result: rate_limit.RateLimitResult, message: str) -> RateLimitedError:
    return RateLimitedError(message, headers={"Retry-After": str(result.retry_after)})


# --- Sign-up ---


async def register(
    db: AsyncSession, data: RegisterRequest, client_ip: str | None, user_agent: str | None
) -> dict[str, Any]:
    if client_ip:
        result = await rate_limit.hit(
            db,
            rate_limit.bucket("signup:ip", client_ip),
            limit=settings.SIGNUPS_PER_IP_PER_HOUR,
            window_seconds=3600,
        )
        if not result.allowed:
            raise _limited(result, "Too many sign-ups from this network. Try again later.")
    email = normalise_email(str(data.email))
    if await find_learner_by_email(db, email) is not None:
        # Sign-up is the one place that has to say so: the published answer logs the new
        # account in straight away, so it can't look the same for a taken email.
        raise EmailTakenError("Email already registered")
    learner = Learner(
        full_name=data.full_name,
        email=email,
        phone_number=data.phone,
        hashed_password=await asyncio.to_thread(hash_password, data.password),
    )
    db.add(learner)
    await db.flush()
    _, token = await start_session(db, learner, user_agent)
    await send_verification_email(db, learner)
    logger.info("learner_registered", learner_id=learner.learner_id)
    return {"access_token": token, "token_type": "bearer", "learner_id": learner.learner_id}


# --- Sign-in ---


async def _record_failed_login(buckets: list[str]) -> None:
    # Its own transaction: the request's transaction is rolled back by the 401
    async with AsyncSessionLocal() as session:
        for key in buckets:
            await rate_limit.record(session, key)
        await session.commit()


async def login(
    db: AsyncSession, email: str, password: str, client_ip: str | None, user_agent: str | None
) -> dict[str, Any]:
    window = settings.LOGIN_WINDOW_MINUTES * 60
    limits = [(rate_limit.bucket("login:email", email), settings.LOGIN_MAX_FAILURES_PER_EMAIL)]
    if client_ip:
        limits.append(
            (rate_limit.bucket("login:ip", client_ip), settings.LOGIN_MAX_FAILURES_PER_IP)
        )
    for key, limit in limits:
        used, wait = await rate_limit.count(db, key, window)
        if used >= limit:
            retry = rate_limit.RateLimitResult(allowed=False, retry_after=max(1, int(wait) + 1))
            raise _limited(retry, "Too many sign-in attempts. Try again later.")

    learner = await find_learner_by_email(db, email)
    if learner is None or not learner.hashed_password:
        await asyncio.to_thread(burn_password_check, password)
        valid = False
    else:
        valid = await asyncio.to_thread(verify_password, password, learner.hashed_password)
    if not valid or learner is None or learner.learner_status == LearnerStatus.INACTIVE:
        await _record_failed_login([key for key, _ in limits])
        raise UnauthorizedError(INVALID_LOGIN)

    await rate_limit.clear(db, limits[0][0])
    if needs_rehash(learner.hashed_password):
        # Accounts from before Day 6 move from bcrypt to Argon2id here
        learner.hashed_password = await asyncio.to_thread(hash_password, password)
        logger.info("password_rehashed", learner_id=learner.learner_id)
    _, token = await start_session(db, learner, user_agent)
    return {
        "access_token": token,
        "token_type": "bearer",
        "learner_id": learner.learner_id,
        "full_name": learner.full_name,
    }


# --- Email confirmation ---


async def verify_email(db: AsyncSession, token: str) -> None:
    row = await use_token(db, token, VERIFY_EMAIL)
    learner = await db.get(Learner, row.learner_id)
    if learner is not None and learner.email_verified_at is None:
        learner.email_verified_at = datetime.now(UTC)


async def resend_verification(db: AsyncSession, learner: Learner) -> None:
    if learner.email_verified_at is not None:
        return
    result = await rate_limit.hit(
        db,
        rate_limit.bucket("verify:resend", str(learner.learner_id)),
        limit=RESENDS_PER_HOUR,
        window_seconds=3600,
    )
    if not result.allowed:
        raise _limited(result, "Too many confirmation emails. Try again later.")
    await send_verification_email(db, learner)


# --- Password change and reset ---


async def change_password(
    db: AsyncSession, learner: Learner, session_id: Any, current: str, new: str
) -> None:
    if not await asyncio.to_thread(verify_password, current, learner.hashed_password):
        raise WrongPasswordError("Your current password is not correct")
    learner.hashed_password = await asyncio.to_thread(hash_password, new)
    await revoke_all_sessions(db, learner.learner_id, "password_changed", keep=session_id)
    await _send_password_changed(db, learner)


async def request_password_reset(db: AsyncSession, email: str, client_ip: str | None) -> None:
    """Always the same work and the same answer: the account lookup happens in a job."""
    if client_ip:
        result = await rate_limit.hit(
            db,
            rate_limit.bucket("reset:ip", client_ip),
            limit=RESETS_PER_IP_PER_HOUR,
            window_seconds=3600,
        )
        if not result.allowed:
            logger.info("password_reset_rate_limited")
            return
    await enqueue(db, RESET_JOB, {"email": normalise_email(email)})


@job(RESET_JOB)
async def send_reset_email(session: AsyncSession, payload: dict[str, Any]) -> None:
    learner = await find_learner_by_email(session, str(payload["email"]))
    if learner is None or learner.learner_status == LearnerStatus.INACTIVE:
        return  # no account: nothing to send, and the request already answered 202
    result = await rate_limit.hit(
        session,
        rate_limit.bucket("reset:email", learner.email),
        limit=RESETS_PER_EMAIL_PER_HOUR,
        window_seconds=3600,
    )
    if not result.allowed:
        return
    minutes = settings.PASSWORD_RESET_TOKEN_MINUTES
    token = await issue_token(session, learner, PASSWORD_RESET, timedelta(minutes=minutes))
    await send_email(
        session,
        to=learner.email,
        template="password_reset",
        context={
            "full_name": learner.full_name,
            "link": _link("/reset-password", token),
            "minutes": minutes,
        },
    )


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    row = await use_token(db, token, PASSWORD_RESET)
    learner = await db.get(Learner, row.learner_id)
    if learner is None:
        raise ExpiredError(EXPIRED_LINK)
    learner.hashed_password = await asyncio.to_thread(hash_password, new_password)
    # Every other reset link dies too, and every signed-in device is signed out
    await db.execute(
        update(AccountToken)
        .where(
            AccountToken.learner_id == learner.learner_id,
            AccountToken.purpose == PASSWORD_RESET,
            AccountToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
    )
    await revoke_all_sessions(db, learner.learner_id, "password_reset")
    # A reset proves the email: it also unlocks sign-in for it
    await rate_limit.clear(db, rate_limit.bucket("login:email", learner.email))
    await _send_password_changed(db, learner)
