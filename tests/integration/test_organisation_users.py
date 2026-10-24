"""Day 7: organisation roles (owner, admin, recruiter) and who can manage them.

GET/POST /organisations/{id}/users and PATCH/DELETE /organisations/{id}/users/{learner_id}:
owners and admins manage the organisation's accounts, only owners make or remove owners,
and an organisation always keeps at least one owner. /accounts/me shows the account type.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.security import create_access_token
from tests.integration.conftest import assert_error_envelope

API = settings.API_PREFIX


def add_learner(db, name: str) -> int:
    learner_id = db.execute(
        text(
            "INSERT INTO learner (full_name, email, phone_number, learner_status) "
            "VALUES (:name, :email, '0800', 'ACTIVE') RETURNING learner_id"
        ),
        {"name": name.title(), "email": f"{name}@example.com"},
    ).scalar_one()
    db.commit()
    return learner_id


def headers_for(db, learner_id: int) -> dict:
    session_id = str(uuid.uuid4())
    db.execute(
        text("INSERT INTO auth_sessions (id, learner_id, expires_at) VALUES (:id, :l, :e)"),
        {"id": session_id, "l": learner_id, "e": datetime.now(UTC) + timedelta(hours=1)},
    )
    db.commit()
    return {"Authorization": f"Bearer {create_access_token(learner_id, session_id=session_id)}"}


@pytest.fixture
def org(db) -> dict:
    owner = add_learner(db, "olu")
    org_id = db.execute(
        text("INSERT INTO organisations (name) VALUES ('Acme') RETURNING id")
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO organisation_members (organisation_id, learner_id, role) VALUES (:o, :l, 'owner')"
        ),
        {"o": org_id, "l": owner},
    )
    db.commit()
    return {"id": org_id, "owner": owner, "url": f"{API}/organisations/{org_id}/users"}


async def add(client, db, org, as_id: int, email: str, role: str):
    return await client.post(
        org["url"], headers=headers_for(db, as_id), json={"email": email, "role": role}
    )


async def test_the_owner_adds_an_admin_and_a_recruiter(client, db, org):
    ada, bola = add_learner(db, "ada"), add_learner(db, "bola")
    response = await add(client, db, org, org["owner"], "ADA@example.com", "admin")
    assert response.status_code == 201, response.text
    assert response.json()["data"]["role"] == "admin"
    assert (await add(client, db, org, ada, "bola@example.com", "recruiter")).status_code == 201

    listed = await client.get(org["url"], headers=headers_for(db, ada))
    assert listed.status_code == 200, listed.text
    roles = {u["learner_id"]: u["role"] for u in listed.json()["data"]["items"]}
    assert roles == {org["owner"]: "owner", ada: "admin", bola: "recruiter"}

    me = (await client.get(f"{API}/accounts/me", headers=headers_for(db, bola))).json()["data"]
    assert (me["account_type"], me["organisation_id"], me["organisation_role"]) == (
        "recruiter",
        org["id"],
        "recruiter",
    )
    me = (await client.get(f"{API}/accounts/me", headers=headers_for(db, ada))).json()["data"]
    assert me["account_type"] == "organisation_admin"


async def test_a_learner_without_an_organisation_is_a_learner(client, db):
    ada = add_learner(db, "ada")
    me = (await client.get(f"{API}/accounts/me", headers=headers_for(db, ada))).json()["data"]
    assert (me["account_type"], me["organisation_id"], me["organisation_role"]) == (
        "learner",
        None,
        None,
    )


async def test_only_an_owner_makes_owners(client, db, org):
    ada, bola = add_learner(db, "ada"), add_learner(db, "bola")
    await add(client, db, org, org["owner"], "ada@example.com", "admin")
    response = await add(client, db, org, ada, "bola@example.com", "owner")
    assert_error_envelope(response, 403, "forbidden")
    assert (
        await add(client, db, org, org["owner"], "bola@example.com", "owner")
    ).status_code == 201
    # An admin cannot demote or remove an owner either
    response = await client.patch(
        f"{org['url']}/{bola}", headers=headers_for(db, ada), json={"role": "recruiter"}
    )
    assert_error_envelope(response, 403, "forbidden")
    response = await client.delete(f"{org['url']}/{bola}", headers=headers_for(db, ada))
    assert_error_envelope(response, 403, "forbidden")


async def test_recruiters_cannot_manage_accounts(client, db, org):
    rec = add_learner(db, "rec")
    add_learner(db, "ada")
    await add(client, db, org, org["owner"], "rec@example.com", "recruiter")
    assert_error_envelope(
        await client.get(org["url"], headers=headers_for(db, rec)), 403, "forbidden"
    )
    assert_error_envelope(
        await add(client, db, org, rec, "ada@example.com", "recruiter"), 403, "forbidden"
    )


async def test_the_last_owner_cannot_leave_or_be_demoted(client, db, org):
    response = await client.delete(
        f"{org['url']}/{org['owner']}", headers=headers_for(db, org["owner"])
    )
    assert_error_envelope(response, 409, "conflict")
    response = await client.patch(
        f"{org['url']}/{org['owner']}",
        headers=headers_for(db, org["owner"]),
        json={"role": "admin"},
    )
    assert_error_envelope(response, 409, "conflict")


async def test_roles_change_and_accounts_leave(client, db, org):
    ada = add_learner(db, "ada")
    await add(client, db, org, org["owner"], "ada@example.com", "recruiter")
    response = await client.patch(
        f"{org['url']}/{ada}", headers=headers_for(db, org["owner"]), json={"role": "admin"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["role"] == "admin"
    response = await client.delete(f"{org['url']}/{ada}", headers=headers_for(db, org["owner"]))
    assert response.status_code == 200, response.text
    me = (await client.get(f"{API}/accounts/me", headers=headers_for(db, ada))).json()["data"]
    assert me["account_type"] == "learner"


async def test_adding_needs_an_existing_account_in_no_other_organisation(client, db, org):
    response = await add(client, db, org, org["owner"], "nobody@example.com", "admin")
    assert_error_envelope(response, 404, "not_found")
    other_owner = add_learner(db, "zed")
    other = db.execute(
        text("INSERT INTO organisations (name) VALUES ('Other') RETURNING id")
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO organisation_members (organisation_id, learner_id, role) VALUES (:o, :l, 'owner')"
        ),
        {"o": other, "l": other_owner},
    )
    db.commit()
    response = await add(client, db, org, org["owner"], "zed@example.com", "admin")
    assert_error_envelope(response, 409, "conflict")
