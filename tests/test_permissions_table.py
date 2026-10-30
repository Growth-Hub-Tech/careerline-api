"""Day 7: one place decides who may call what (app/core/permissions.py).

Every route has exactly one access rule in POLICIES, and the role table gives each organisation
role the right permissions. tests/integration/test_route_access.py then calls every route as
every kind of user and checks the answer matches the rule.
"""

from fastapi.routing import APIRoute

from app.core import permissions
from app.core.permissions import POLICIES, ROLE_PERMISSIONS, OrgPermission, Permission, Role
from app.main import app


def route_keys() -> set[str]:
    keys = set()
    for route in app.routes:
        if isinstance(route, APIRoute) and not route.path.startswith("/__test__"):
            for method in route.methods:
                keys.add(permissions.policy_key(method, route.path))
    return keys


def test_every_route_has_an_access_rule():
    missing = route_keys() - set(POLICIES)
    assert not missing, f"routes with no access rule: {sorted(missing)}"


def test_every_access_rule_belongs_to_a_route():
    stale = {key for key in POLICIES if " /__test__" not in key} - route_keys()
    assert not stale, f"access rules for routes that do not exist: {sorted(stale)}"


def test_owners_can_do_everything_an_admin_can_and_more():
    assert ROLE_PERMISSIONS[Role.ADMIN] < ROLE_PERMISSIONS[Role.OWNER]
    assert ROLE_PERMISSIONS[Role.OWNER] == set(Permission)
    assert Permission.OWNERS_MANAGE not in ROLE_PERMISSIONS[Role.ADMIN]


def test_recruiters_only_work_with_candidates_and_invitations():
    assert ROLE_PERMISSIONS[Role.RECRUITER] == {
        Permission.ORGANISATION_READ,
        Permission.CANDIDATES_READ,
        Permission.CANDIDATES_MANAGE,
        Permission.INVITATIONS_READ,
        Permission.INVITATIONS_MANAGE,
    }


def test_organisation_routes_need_an_organisation_permission():
    for key, policy in POLICIES.items():
        if " /organisations/" in key or " /recruiter/" in key:
            assert isinstance(policy, OrgPermission), key
