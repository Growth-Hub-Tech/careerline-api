"""Day 6: existing learners keep their passwords. Old accounts have bcrypt hashes (passlib);
they still sign in, and their hash is upgraded to Argon2id at that sign-in."""

import bcrypt
from sqlalchemy import text

from tests.integration.conftest import login


def _old_account(db, email: str, password: str) -> None:
    hashed = bcrypt.hashpw(password[:72].encode(), bcrypt.gensalt(rounds=12)).decode()
    db.execute(
        text(
            "INSERT INTO learner (full_name, email, phone_number, hashed_password, learner_status) "
            "VALUES ('Old Learner', :email, '08000000000', :hashed, 'ACTIVE')"
        ),
        {"email": email, "hashed": hashed},
    )
    db.commit()


def _stored(db, email: str) -> str:
    return db.execute(
        text("SELECT hashed_password FROM learner WHERE email = :email"), {"email": email}
    ).scalar_one()


async def test_an_old_bcrypt_password_still_signs_in_and_is_upgraded(client, db):
    _old_account(db, "old@example.com", "my-old-password")
    assert _stored(db, "old@example.com").startswith("$2b$")

    response = await login(client, "old@example.com", "my-old-password")
    assert response.status_code == 200, response.text
    assert _stored(db, "old@example.com").startswith("$argon2id$")

    # And it keeps working with the new hash
    assert (await login(client, "old@example.com", "my-old-password")).status_code == 200
    assert (await login(client, "old@example.com", "wrong-password")).status_code == 401


async def test_an_old_account_with_mixed_case_email_signs_in(client, db):
    _old_account(db, "Mixed.Case@Example.com", "my-old-password")
    assert (await login(client, "mixed.case@example.com", "my-old-password")).status_code == 200


async def test_a_wrong_password_does_not_touch_the_old_hash(client, db):
    _old_account(db, "old@example.com", "my-old-password")
    before = _stored(db, "old@example.com")
    assert (await login(client, "old@example.com", "wrong-password")).status_code == 401
    assert _stored(db, "old@example.com") == before
