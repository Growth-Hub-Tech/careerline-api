"""Day 7: every route, called by every kind of user, answers as its access rule says.

Kinds of user: anonymous, a learner (no organisation), the recruiter, admin and owner of the
organisation in the path, and the owner of ANOTHER organisation. "Allowed" means the request
got past the access check (any answer but 401/403: e.g. 422 for the empty body this test
sends, 404 for made-up ids); "denied" means 401 (anonymous) or 403, in the error envelope, and
404 for an organisation in the path that is not the caller's.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text

from app.core import permissions
from app.core.permissions import POLICIES, Policy
from app.core.security import create_access_token
from app.main import app
from app.sample.routes.organisations import ORG_ID

USERS = ("anonymous", "learner", "recruiter", "admin", "owner", "other_org_owner")
ROUTES = sorted(
    (method, route.path)
    for route in app.routes
    if isinstance(route, APIRoute) and not route.path.startswith("/__test__")
    for method in route.methods
)


@pytest.fixture
def people(db) -> dict[str, int]:
    ids: dict[str, int] = {}
    for name in USERS[1:]:
        ids[name] = db.execute(
            text(
                "INSERT INTO learner (full_name, email, phone_number, learner_status) "
                "VALUES (:name, :email, '0800', 'ACTIVE') RETURNING learner_id"
            ),
            {"name": name, "email": f"{name}@example.com"},
        ).scalar_one()
    db.execute(text("INSERT INTO organisations (id, name) VALUES (:id, 'Acme')"), {"id": ORG_ID})
    other_org = db.execute(
        text("INSERT INTO organisations (name) VALUES ('Other Ltd') RETURNING id")
    ).scalar_one()
    for name, org, role in (
        ("recruiter", ORG_ID, "recruiter"),
        ("admin", ORG_ID, "admin"),
        ("owner", ORG_ID, "owner"),
        ("other_org_owner", other_org, "owner"),
    ):
        db.execute(
            text(
                "INSERT INTO organisation_members (organisation_id, learner_id, role) "
                "VALUES (:org, :learner, :role)"
            ),
            {"org": org, "learner": ids[name], "role": role},
        )
    db.commit()
    return ids


def token_for(db, learner_id: int) -> str:
    session_id = str(uuid.uuid4())
    db.execute(
        text("INSERT INTO auth_sessions (id, learner_id, expires_at) VALUES (:id, :learner, :exp)"),
        {"id": session_id, "learner": learner_id, "exp": datetime.now(UTC) + timedelta(hours=1)},
    )
    db.commit()
    return create_access_token(learner_id, session_id=session_id)


def fill(path: str, learner_id: int) -> str:
    values = {
        "organisation_id": str(ORG_ID),
        "learner_id": str(learner_id),
        "token": "made-up-token",
        "reference": "made-up-reference",
    }
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            path = path.replace(part, values.get(name, "999999"))
    return path


def expected(policy: Policy, user: str, path: str) -> str:
    """allowed, or the status the rule must answer with."""
    if policy.kind == "public":
        return "allowed"
    if user == "anonymous":
        return "401"
    if policy.kind in ("signed_in", "self"):
        return "allowed"
    # An organisation permission: a member whose role grants it; when the path names an
    # organisation, only a member of THAT one (404 for the others, so ids are not confirmed)
    role = {"recruiter": "recruiter", "admin": "admin", "owner": "owner"}.get(user)
    if user == "other_org_owner":
        return "404" if "{organisation_id}" in path else "allowed"
    if role is None:
        return "403"
    return "allowed" if policy.allows_role(role) else "403"


@pytest.mark.parametrize(("method", "path"), ROUTES, ids=[f"{m} {p}" for m, p in ROUTES])
async def test_every_route_against_every_kind_of_user(client, db, people, method, path):
    policy = POLICIES[permissions.policy_key(method, path)]
    problems = []
    for user in USERS:
        learner_id = people.get(user, people["learner"])
        headers = (
            {"Authorization": f"Bearer {token_for(db, learner_id)}"} if user != "anonymous" else {}
        )
        response = await client.request(method, fill(path, learner_id), headers=headers)
        want = expected(policy, user, path)
        got = response.status_code
        if want == "allowed" and got in (401, 403):
            problems.append(f"{user}: expected access, got {got} {response.text[:120]}")
        elif want != "allowed":
            if str(got) != want:
                problems.append(f"{user}: expected {want}, got {got}")
            elif response.json()["success"] is not False:
                problems.append(f"{user}: denial is not in the error envelope")
    assert not problems, f"{method} {path} ({policy}):\n" + "\n".join(problems)


SELF_ROUTES = [(m, p) for m, p in ROUTES if POLICIES[permissions.policy_key(m, p)].kind == "self"]


@pytest.mark.parametrize(("method", "path"), SELF_ROUTES, ids=[f"{m} {p}" for m, p in SELF_ROUTES])
async def test_nobody_reads_another_learners_data_through_the_path(
    client, db, people, method, path
):
    for user in ("learner", "recruiter", "admin", "owner"):
        headers = {"Authorization": f"Bearer {token_for(db, people[user])}"}
        someone_else = people["learner"] if user != "learner" else people["owner"]
        response = await client.request(method, fill(path, someone_else), headers=headers)
        assert response.status_code == 403, (user, response.text)


async def test_another_organisation_is_out_of_reach_even_for_its_owner(client, db, people):
    headers = {"Authorization": f"Bearer {token_for(db, people['other_org_owner'])}"}
    for path in ("audits", "heatmap", "targets", "members", "users"):
        response = await client.get(f"/api/v1/organisations/{ORG_ID}/{path}", headers=headers)
        assert response.status_code == 404, (path, response.text)
