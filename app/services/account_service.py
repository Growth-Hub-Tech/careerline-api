import asyncio
import hmac
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.exceptions import BadRequestError, RateLimitedError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import (
    burn_password_check,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.models import Learner, LearnerStatus
from app.schemas.auth import RegisterRequest
from app.schemas.common import PASSWORD_MAX_LENGTH
from app.services.session_service import revoke_all_sessions, start_session

logger = get_logger(__name__)

# CareerLine sends no email, so every account resets its password with this PIN
RESET_PIN = "1234"
PASSWORD_CHECK_FAILURES = 5
# Failed sign-ins (and PIN resets) allowed per email and per IP address within the window, then 429
LOGIN_MAX_FAILURES_PER_EMAIL = 5
LOGIN_MAX_FAILURES_PER_IP = 20
LOGIN_WINDOW_MINUTES = 15
SIGNUPS_PER_IP_PER_HOUR = 20

INVALID_LOGIN = "Invalid email or password"
INVALID_RESET = "That email and PIN don't match an account"


class EmailTakenError(BadRequestError):
    code = "email_taken"


class WrongPasswordError(BadRequestError):
    code = "wrong_password"


class InvalidResetPinError(BadRequestError):
    code = "invalid_reset_pin"


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def find_learner_by_email(db: AsyncSession, email: str) -> Learner | None:
    """Case-insensitive. Older accounts may have capitals in their email."""
    email = normalise_email(email)
    return (
        await db.scalars(
            select(Learner)
            .where(func.lower(Learner.email) == email)
            .order_by(case((Learner.email == email, 0), else_=1), Learner.learner_id)
            .limit(1)
        )
    ).first()


def _limited(result: rate_limit.RateLimitResult, message: str) -> RateLimitedError:
    return RateLimitedError(message, headers={"Retry-After": str(result.retry_after)})


async def _refuse_if_limited(
    db: AsyncSession, limits: list[tuple[str, int]], window: int, message: str
) -> None:
    """Refuse when any bucket already holds its limit of failures.

    The first bucket is locked until this request's transaction ends, so parallel guesses for
    one account are counted one after another and can't slip past the limit together.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:b))"), {"b": limits[0][0]})
    for key, limit in limits:
        used, wait = await rate_limit.count(db, key, window)
        if used >= limit:
            retry = rate_limit.RateLimitResult(allowed=False, retry_after=max(1, int(wait) + 1))
            raise _limited(retry, message)


async def _record_failures(db: AsyncSession, buckets: list[str]) -> None:
    """Count a failed attempt and commit at once, before the error is answered.

    The error would roll the request's transaction back. Committing here, on the same
    connection, also releases the lock taken in _refuse_if_limited: a second connection would
    deadlock when parallel attempts already hold every connection in the pool.
    """
    for key in buckets:
        await rate_limit.record(db, key)
    await db.commit()


def _attempt_limits(kind: str, email: str, client_ip: str | None) -> list[tuple[str, int]]:
    limits = [(rate_limit.bucket(f"{kind}:email", email), LOGIN_MAX_FAILURES_PER_EMAIL)]
    if client_ip:
        limits.append((rate_limit.bucket(f"{kind}:ip", client_ip), LOGIN_MAX_FAILURES_PER_IP))
    return limits


async def check_current_password(db: AsyncSession, learner: Learner, password: str) -> None:
    """For actions a signed-in person confirms with their password: 5 wrong tries, then 429."""
    key = rate_limit.bucket("password:learner", str(learner.learner_id))
    limits = [(key, PASSWORD_CHECK_FAILURES)]
    window = LOGIN_WINDOW_MINUTES * 60
    await _refuse_if_limited(db, limits, window, "Too many wrong passwords. Try again later.")
    if len(password) > PASSWORD_MAX_LENGTH or not await asyncio.to_thread(
        verify_password, password, learner.hashed_password
    ):
        await _record_failures(db, [key])
        raise WrongPasswordError("Your current password is not correct")
    await rate_limit.clear(db, key)


# --- Sign-up ---


async def register(
    db: AsyncSession, data: RegisterRequest, client_ip: str | None, user_agent: str | None
) -> dict[str, Any]:
    if client_ip:
        result = await rate_limit.hit(
            db,
            rate_limit.bucket("signup:ip", client_ip),
            limit=SIGNUPS_PER_IP_PER_HOUR,
            window_seconds=3600,
        )
        if not result.allowed:
            raise _limited(result, "Too many sign-ups from this network. Try again later.")
    email = normalise_email(str(data.email))
    if await find_learner_by_email(db, email) is not None:
        # Sign-up is the one place that has to say so: it signs the new account in straight away
        raise EmailTakenError("An account with this email already exists")
    learner = Learner(
        full_name=data.full_name,
        email=email,
        phone_number=data.phone,
        hashed_password=await asyncio.to_thread(hash_password, data.password),
    )
    db.add(learner)
    await db.flush()
    _, token = await start_session(db, learner, user_agent)
    logger.info("learner_registered", learner_id=learner.learner_id)
    return {"access_token": token, "token_type": "bearer", "learner_id": learner.learner_id}


# --- Sign-in ---


async def login(
    db: AsyncSession, email: str, password: str, client_ip: str | None, user_agent: str | None
) -> dict[str, Any]:
    limits = _attempt_limits("login", email, client_ip)
    window = LOGIN_WINDOW_MINUTES * 60
    await _refuse_if_limited(db, limits, window, "Too many sign-in attempts. Try again later.")

    learner = await find_learner_by_email(db, email)
    if len(password) > PASSWORD_MAX_LENGTH:
        valid = False  # refused before hashing, so a huge password cannot tie up the server
    elif learner is None or not learner.hashed_password:
        await asyncio.to_thread(burn_password_check, password)
        valid = False
    else:
        valid = await asyncio.to_thread(verify_password, password, learner.hashed_password)
    if not valid or learner is None or learner.learner_status == LearnerStatus.INACTIVE:
        await _record_failures(db, [key for key, _ in limits])
        raise UnauthorizedError(INVALID_LOGIN)

    await rate_limit.clear(db, limits[0][0])
    if needs_rehash(learner.hashed_password):
        learner.hashed_password = await asyncio.to_thread(hash_password, password)
        logger.info("password_rehashed", learner_id=learner.learner_id)
    _, token = await start_session(db, learner, user_agent)
    return {
        "access_token": token,
        "token_type": "bearer",
        "learner_id": learner.learner_id,
        "full_name": learner.full_name,
    }


# --- Password change and reset ---


async def change_password(
    db: AsyncSession, learner: Learner, session_id: Any, current: str, new: str
) -> None:
    await check_current_password(db, learner, current)
    learner.hashed_password = await asyncio.to_thread(hash_password, new)
    await revoke_all_sessions(db, learner.learner_id, "password_changed", keep=session_id)


async def reset_password(
    db: AsyncSession, email: str, pin: str, new_password: str, client_ip: str | None
) -> None:
    """Reset with the fixed PIN. An unknown email and a wrong PIN get the same answer."""
    limits = _attempt_limits("reset", email, client_ip)
    window = LOGIN_WINDOW_MINUTES * 60
    await _refuse_if_limited(db, limits, window, "Too many reset attempts. Try again later.")

    learner = await find_learner_by_email(db, email)
    pin_ok = hmac.compare_digest(pin.strip().encode(), RESET_PIN.encode())
    if not pin_ok or learner is None or learner.learner_status == LearnerStatus.INACTIVE:
        await _record_failures(db, [key for key, _ in limits])
        raise InvalidResetPinError(INVALID_RESET)

    learner.hashed_password = await asyncio.to_thread(hash_password, new_password)
    await revoke_all_sessions(db, learner.learner_id, "password_reset")
    await rate_limit.clear(db, limits[0][0])
    await rate_limit.clear(db, rate_limit.bucket("login:email", learner.email))
    await rate_limit.clear(db, rate_limit.bucket("password:learner", str(learner.learner_id)))
    logger.info("password_reset", learner_id=learner.learner_id)
