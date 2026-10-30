"""Who may call what: the ONE place access is decided (Day 7).

Every route has exactly one rule in POLICIES (tests/test_permissions_table.py fails otherwise,
and a route with no rule is refused). `authorize`, a global dependency of the app, applies the
rule before the route runs:

- public: anyone
- signed_in: any signed-in account (401 otherwise)
- self: signed in, and the {learner_id} in the path is the caller's own (403 otherwise)
- an organisation permission: signed in, member of an organisation whose role grants the
  permission, and when the path names an organisation, it is the caller's (403 otherwise)

What each organisation role may do is ROLE_PERMISSIONS. Ownership of single records (an attempt,
a payment) is still checked by the route that loads the record.
"""

from dataclasses import dataclass
from enum import StrEnum

from fastapi import Depends, Request

from app.api.deps import credentials_error, current_membership, optional_current_session
from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.models.organisations import OrganisationMember
from app.services.session_service import CurrentSession

logger = get_logger(__name__)


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    RECRUITER = "recruiter"


class Permission(StrEnum):
    ORGANISATION_READ = "organisation.read"
    USERS_READ = "organisation.users.read"
    USERS_MANAGE = "organisation.users.manage"  # add, change and remove admins and recruiters
    OWNERS_MANAGE = "organisation.owners.manage"  # make, demote and remove owners
    TEAM_READ = "organisation.team.read"  # the audit roster (people being tested)
    TEAM_MANAGE = "organisation.team.manage"
    AUDITS_READ = "organisation.audits.read"  # audits, benchmarks, heatmap, targets
    AUDITS_MANAGE = "organisation.audits.manage"
    CANDIDATES_READ = "recruiter.candidates.read"
    CANDIDATES_MANAGE = "recruiter.candidates.manage"
    INVITATIONS_READ = "invitations.read"
    INVITATIONS_MANAGE = "invitations.manage"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.OWNER: set(Permission),
    Role.ADMIN: set(Permission) - {Permission.OWNERS_MANAGE},
    Role.RECRUITER: {
        Permission.ORGANISATION_READ,
        Permission.CANDIDATES_READ,
        Permission.CANDIDATES_MANAGE,
        Permission.INVITATIONS_READ,
        Permission.INVITATIONS_MANAGE,
    },
}


def role_can(role: str | None, permission: Permission) -> bool:
    try:
        return role is not None and permission in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False


@dataclass(frozen=True)
class Policy:
    kind: str  # public | signed_in | self | organisation

    def allows_role(self, role: str | None) -> bool:
        return self.kind != "organisation"

    def __str__(self) -> str:
        return self.kind


@dataclass(frozen=True)
class OrgPermission(Policy):
    permission: Permission = Permission.ORGANISATION_READ

    def allows_role(self, role: str | None) -> bool:
        return role_can(role, self.permission)

    def __str__(self) -> str:
        return f"organisation permission {self.permission.value}"


PUBLIC = Policy("public")
SIGNED_IN = Policy("signed_in")
SELF = Policy("self")


def org(permission: Permission) -> OrgPermission:
    return OrgPermission("organisation", permission)


P = Permission

# Every route: "METHOD /path" (the path without /api/v1) -> its rule
POLICIES: dict[str, Policy] = {
    # Health checks (outside /api/v1)
    "GET /healthz": PUBLIC,
    "GET /readyz": PUBLIC,
    # Sign-up, sign-in, sign-out
    "POST /auth/register": PUBLIC,
    "POST /auth/login": PUBLIC,
    "POST /auth/logout": SIGNED_IN,
    # My account
    "GET /accounts/me": SIGNED_IN,
    "PATCH /accounts/me": SIGNED_IN,
    "POST /accounts/me/password": SIGNED_IN,
    "POST /accounts/verify-email/resend": SIGNED_IN,
    # Email links: the token in the body is the proof
    "POST /accounts/password-reset": PUBLIC,
    "POST /accounts/password-reset/confirm": PUBLIC,
    "POST /accounts/verify-email": PUBLIC,
    # Learners: only ever the caller
    "GET /learners/me": SIGNED_IN,
    "GET /learners/{learner_id}": SELF,
    "GET /learners/behavioural-questions/{skill_id}": PUBLIC,
    "POST /learners/behavioural-answers": SIGNED_IN,
    "POST /attempts/start": SIGNED_IN,
    "POST /attempts/submit": SIGNED_IN,
    "GET /attempts/me": SIGNED_IN,
    "GET /attempts/learner/{learner_id}": SELF,
    "GET /attempts/{attempt_id}": SIGNED_IN,  # the route checks the attempt is yours
    "PATCH /attempts/{attempt_id}/cancel": SIGNED_IN,  # same
    "GET /recommendations/levels/me": SIGNED_IN,
    "GET /recommendations/levels/{learner_id}": SELF,
    "GET /recommendations/pathway/me/{skill_id}": SIGNED_IN,
    "GET /recommendations/pathway/{learner_id}/{skill_id}": SELF,
    # Catalogue (public)
    "GET /skills/": PUBLIC,
    "GET /skills/{skill_id}/subskills": PUBLIC,
    "GET /roles": PUBLIC,
    "GET /roles/{role_id}": PUBLIC,
    "GET /tests": PUBLIC,
    "GET /tests/{test_id}": PUBLIC,
    "GET /programmes": PUBLIC,
    "GET /programmes/{programme_id}": PUBLIC,
    "GET /beginner-path/intake": PUBLIC,
    "GET /payments/credit-packs": PUBLIC,
    "GET /subscriptions/plans": PUBLIC,
    # Contact form (public) and the test server's mailbox (its own token, never in production)
    "POST /contact": PUBLIC,
    "GET /test-mailbox": PUBLIC,
    "DELETE /test-mailbox": PUBLIC,
    # A learner's own things (sample routes until built: they answer for the caller)
    "GET /tests/{test_id}/access": SIGNED_IN,
    "GET /results": SIGNED_IN,
    "GET /results/{result_id}": SIGNED_IN,
    "GET /results/{result_id}/report": SIGNED_IN,
    "POST /results/{result_id}/report": SIGNED_IN,
    "GET /profile": SIGNED_IN,
    "PATCH /profile": SIGNED_IN,
    "GET /profile/skills": SIGNED_IN,
    "POST /beginner-path/intake": SIGNED_IN,
    "GET /beginner-path/recommendations": SIGNED_IN,
    "POST /programmes/{programme_id}/clicks": SIGNED_IN,
    "GET /privacy/consents": SIGNED_IN,
    "PUT /privacy/consents": SIGNED_IN,
    "POST /privacy/data-exports": SIGNED_IN,
    "GET /privacy/data-exports/{export_id}": SIGNED_IN,
    "POST /privacy/account-deletion": SIGNED_IN,
    "DELETE /privacy/account-deletion": SIGNED_IN,
    "POST /payments/checkout": SIGNED_IN,
    "GET /payments": SIGNED_IN,
    "GET /payments/{reference}": SIGNED_IN,
    "GET /credits": SIGNED_IN,
    "GET /subscriptions/me": SIGNED_IN,
    "POST /subscriptions": SIGNED_IN,
    "POST /subscriptions/me/cancel": SIGNED_IN,
    # Paystack calls this; the real one will check Paystack's signature
    "POST /payments/webhooks/paystack": PUBLIC,
    # Invitations: candidates open and accept them; recruiters and admins send them
    "GET /invitations/token/{token}": PUBLIC,
    "POST /invitations/token/{token}/accept": SIGNED_IN,
    "POST /invitations": org(P.INVITATIONS_MANAGE),
    "GET /invitations": org(P.INVITATIONS_READ),
    "GET /invitations/{invitation_id}": org(P.INVITATIONS_READ),
    "POST /invitations/{invitation_id}/revoke": org(P.INVITATIONS_MANAGE),
    # Recruiters
    "GET /recruiter/candidates": org(P.CANDIDATES_READ),
    "POST /recruiter/candidates": org(P.CANDIDATES_MANAGE),
    "GET /recruiter/candidates/{candidate_id}": org(P.CANDIDATES_READ),
    "GET /recruiter/candidates/{candidate_id}/report": org(P.CANDIDATES_READ),
    # Organisations
    "GET /organisations/me": org(P.ORGANISATION_READ),
    "GET /organisations/{organisation_id}/users": org(P.USERS_READ),
    "POST /organisations/{organisation_id}/users": org(P.USERS_MANAGE),
    "PATCH /organisations/{organisation_id}/users/{learner_id}": org(P.USERS_MANAGE),
    "DELETE /organisations/{organisation_id}/users/{learner_id}": org(P.USERS_MANAGE),
    "GET /organisations/{organisation_id}/members": org(P.TEAM_READ),
    "POST /organisations/{organisation_id}/members": org(P.TEAM_MANAGE),
    "GET /organisations/{organisation_id}/audits": org(P.AUDITS_READ),
    "POST /organisations/{organisation_id}/audits": org(P.AUDITS_MANAGE),
    "GET /organisations/{organisation_id}/audits/{audit_id}": org(P.AUDITS_READ),
    "GET /organisations/{organisation_id}/heatmap": org(P.AUDITS_READ),
    "GET /organisations/{organisation_id}/targets": org(P.AUDITS_READ),
    "PUT /organisations/{organisation_id}/targets": org(P.AUDITS_MANAGE),
    # Sample API helpers (test server only: drive the sample flows)
    "GET /sample/paystack/{reference}": PUBLIC,
    "POST /sample/invitations/{token}/complete": PUBLIC,
    "POST /sample/invitations/{token}/expire": PUBLIC,
    "POST /sample/reset": PUBLIC,
}


def policy_key(method: str, path: str) -> str:
    if path.startswith(settings.API_PREFIX + "/"):
        path = path[len(settings.API_PREFIX) :]
    return f"{method.upper()} {path}"


async def authorize(
    request: Request,
    current: CurrentSession | None = Depends(optional_current_session),
    membership: OrganisationMember | None = Depends(current_membership),
) -> None:
    """Applies the route's rule. A global dependency: it runs before every route."""
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    policy = POLICIES.get(policy_key(request.method, path))
    if policy is None:
        # Fail closed: a route nobody wrote a rule for is refused (and the tests catch it)
        logger.error("route_without_access_rule", method=request.method, path=path)
        raise ForbiddenError("You are not allowed to do this")
    if policy.kind == "public":
        return
    if current is None:
        raise credentials_error()
    if policy.kind == "signed_in":
        return
    if policy.kind == "self":
        if str(request.path_params.get("learner_id")) != str(current.learner.learner_id):
            raise ForbiddenError("You can only access your own data")
        return
    assert isinstance(policy, OrgPermission)
    if membership is None:
        raise ForbiddenError("This needs an organisation account")
    if not role_can(membership.role, policy.permission):
        raise ForbiddenError(f"Your role ({membership.role}) is not allowed to do this")
    path_org = request.path_params.get("organisation_id")
    if path_org is not None and str(path_org) != str(membership.organisation_id):
        # 404 (as the sample contract always answered): never confirm another organisation exists
        raise NotFoundError(f"Organisation {path_org} not found")
