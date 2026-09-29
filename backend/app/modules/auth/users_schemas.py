from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

# Any role code this tenant can actually assign — the six built-ins plus
# whatever roles it has defined for itself. Only the *shape* is checked
# here; `_resolve_assignable_role` is what refuses `super_admin` (a platform
# role, and handing it out would be an escalation straight out of the
# tenancy — 07_RBAC_MATRIX.md §1) and anything that does not exist for this
# company, and `_assert_no_escalation` is what refuses a role that grants
# more than the caller holds.
_ASSIGNABLE_ROLES = "^[a-z][a-z0-9_]{1,39}$"
_GODOWN_SCOPE = "^(all|specific)$"


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    phone: Optional[str]
    role_id: UUID
    role_code: Optional[str]
    status: str
    has_all_godowns: bool
    godown_scope: str
    godown_ids: list[str]
    last_login_at: Optional[datetime]
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    phone: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|inactive|suspended)$")
    role_code: Optional[str] = Field(default=None, pattern=_ASSIGNABLE_ROLES)
    godown_scope: Optional[str] = Field(default=None, pattern=_GODOWN_SCOPE)
    godown_ids: Optional[list[UUID]] = None


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=1, max_length=300)
    role_code: str = Field(pattern=_ASSIGNABLE_ROLES)
    godown_scope: str = Field(default="all", pattern=_GODOWN_SCOPE)
    godown_ids: Optional[list[UUID]] = None


class InvitationCreatedOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role_code: str
    expires_at: datetime
    invitation_token: Optional[str] = Field(
        default=None,
        description=(
            "Single-use token for the invite link. Populated only in development, where "
            "there may be no mail server; in every other environment the emailed link is "
            "the only way to get it, and the database stores just its hash."
        ),
    )


class InvitationOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role_code: str
    godown_scope: str
    status: str
    invited_at: datetime
    expires_at: datetime
    resend_count: int


class AcceptInvitationRequest(BaseModel):
    invitation_token: str = Field(min_length=10)
    password: str = Field(min_length=8, max_length=200, description="At least 8 characters")
    full_name: Optional[str] = Field(
        default=None, description="Optional — overrides the name the inviter entered"
    )


# ------------------------------------------------------------ roles


class RoleOut(BaseModel):
    """A role and what it may do.

    The seven built-ins (`is_system`) are read-only for everyone; a tenant
    may define roles of its own alongside them, within the limits of what
    the person defining it already holds (BR-AUTH-09).
    """

    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    is_system: bool = True
    permissions: list[str] = Field(default_factory=list)
    user_count: int = 0


class PermissionOut(BaseModel):
    code: str
    module: str
    description: Optional[str] = None


class RoleCreate(BaseModel):
    """A role of this tenant's own.

    `code` is optional: it is a stable machine handle, so it is derived from
    the name when the caller doesn't care. `permissions` may never exceed
    what the caller themselves holds — BR-AUTH-09 applies to *defining* a
    role, not only to assigning one, or the rule would be one API call away
    from meaningless.
    """

    name: str = Field(min_length=2, max_length=100)
    code: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$")
    description: Optional[str] = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=200)
    #: Start from an existing role's permission set. The caller's own limits
    #: still apply, so cloning Owner as a Purchase Manager is refused.
    clone_from_role_id: Optional[UUID] = None


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    #: Omit to leave the permission set alone; send a list to replace it.
    permissions: Optional[list[str]] = Field(default=None, max_length=200)


class RoleUsageOut(BaseModel):
    role_id: UUID
    user_count: int
    invitation_count: int
    in_use: bool
    reason: Optional[str] = None
