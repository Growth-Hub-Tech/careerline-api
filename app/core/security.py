"""Passwords, session tokens and one-time tokens.

Passwords: new hashes are Argon2id. Accounts created before Day 6 have bcrypt hashes (made by
passlib from the first 72 characters of the password); they still verify, and the sign-in
that verifies one replaces it with an Argon2id hash (needs_rehash).

Session tokens: a signed JWT with the learner id (sub) and the server-side session id (sid).
The session row decides whether the token still works, so signing out (or resetting the
password) ends it at once. See app/services/session_service.py.

One-time tokens (email confirmation, password reset): random, sent only in the email link,
stored as a SHA-256 hash.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Argon2id with the library's defaults (RFC 9106 "low memory" profile: 64 MiB, 3 passes)
_hasher = PasswordHasher()
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")
# A well-formed bcrypt hash (the bcrypt library panics on malformed ones instead of failing)
_BCRYPT_HASH = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    if not hashed_password:
        return False
    if hashed_password.startswith("$argon2"):
        try:
            return _hasher.verify(hashed_password, plain_password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    if hashed_password.startswith(_BCRYPT_PREFIXES):
        # The old scheme: bcrypt of the first 72 characters (bcrypt itself reads at most 72 bytes)
        if not _BCRYPT_HASH.match(hashed_password):
            return False
        secret = plain_password[:72].encode("utf-8")[:72]
        try:
            return bcrypt.checkpw(secret, hashed_password.encode("ascii"))
        except ValueError:
            return False
    return False


def needs_rehash(hashed_password: str) -> bool:
    """True for old bcrypt hashes and for Argon2 hashes made with older parameters."""
    if not hashed_password.startswith("$argon2"):
        return True
    try:
        return _hasher.check_needs_rehash(hashed_password)
    except InvalidHashError:
        return True


def burn_password_check(plain_password: str) -> None:
    """Spend the time of a real password check, for an email that has no account (so both take
    as long and the answer time does not tell whether the account exists)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(16))
    verify_password(plain_password, _dummy_hash)


def create_access_token(learner_id: int, session_id: str | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(learner_id),  # who the token belongs to
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if session_id is not None:
        payload["sid"] = session_id  # the server-side session (revocable)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> tuple[int, str | None] | None:
    """(learner_id, session_id) of a valid, unexpired token; None otherwise."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        session_id = payload.get("sid")
        return int(payload["sub"]), str(session_id) if session_id else None
    except (JWTError, KeyError, TypeError, ValueError):
        return None


def decode_access_token(token: str) -> int | None:
    """The learner id of a valid token (signature and expiry only; no session check)."""
    decoded = decode_token(token)
    return decoded[0] if decoded else None


def hash_one_time_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_one_time_token() -> tuple[str, str]:
    """A token for an email link, and the hash to store."""
    token = secrets.token_urlsafe(32)
    return token, hash_one_time_token(token)
