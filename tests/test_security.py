"""Day 6: password hashing (Argon2id, old bcrypt hashes still accepted) and session tokens."""

import bcrypt
from jose import jwt

from app.core import security
from app.core.config import settings


def _legacy_bcrypt(password: str) -> str:
    # Exactly what the old code stored: passlib bcrypt (12 rounds) of the first 72 characters
    return bcrypt.hashpw(password[:72].encode(), bcrypt.gensalt(rounds=4)).decode()


def test_new_passwords_are_hashed_with_argon2id():
    hashed = security.hash_password("correct-horse-battery")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password("correct-horse-battery", hashed)
    assert not security.verify_password("wrong-password", hashed)
    assert not security.needs_rehash(hashed)


def test_old_bcrypt_hashes_still_work_and_are_marked_for_rehash():
    hashed = _legacy_bcrypt("correct-horse-battery")
    assert hashed.startswith("$2b$")
    assert security.verify_password("correct-horse-battery", hashed)
    assert not security.verify_password("wrong-password", hashed)
    assert security.needs_rehash(hashed)


def test_old_long_passwords_still_work():
    # The old code cut passwords to 72 characters before hashing; those accounts must still log in
    long_password = "x" * 80 + "-tail"
    hashed = _legacy_bcrypt(long_password)
    assert security.verify_password(long_password, hashed)


def test_garbage_hashes_never_verify():
    for stored in ("", "plain-text-password", "$2b$12$short", "$argon2id$broken"):
        assert not security.verify_password("plain-text-password", stored)


def test_a_session_token_carries_the_session_and_expires():
    token = security.create_access_token(7, session_id="5b0f5c2e-0000-4000-8000-000000000001")
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    assert claims["sub"] == "7"
    assert claims["sid"] == "5b0f5c2e-0000-4000-8000-000000000001"
    assert claims["exp"] > claims["iat"]
    assert security.decode_token(token) == (7, "5b0f5c2e-0000-4000-8000-000000000001")
    assert security.decode_access_token(token) == 7


def test_a_token_without_a_session_has_no_session_id():
    assert security.decode_token(security.create_access_token(7)) == (7, None)
    assert security.decode_token("not.a.token") is None


def test_one_time_tokens_are_random_and_stored_hashed():
    token, digest = security.new_one_time_token()
    other, _ = security.new_one_time_token()
    assert token != other and len(token) >= 32
    assert digest == security.hash_one_time_token(token)
    assert token not in digest
