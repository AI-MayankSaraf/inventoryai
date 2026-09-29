"""allow tenant sessions to revoke their own users' refresh tokens

Revision ID: 8ba3759b0926
Revises: d613c7aa375a
Create Date: 2026-09-17

BR-AUTH-11 requires that "changing a user's role or godown scope revokes
their refresh tokens, forcing a permission reload" — without which a
demoted user keeps their old permissions until their refresh token expires,
because permissions are baked into the access token at issue time.

That revocation ran from the ordinary tenant session and silently did
nothing: `refresh_tokens` was given RLS with **no** policies in
746390963b46, and Postgres treats row security with no matching policy as
deny-all. The UPDATE matched zero rows, raised no error, and the demoted
user kept their tokens. It only surfaced because the test asserted the
token stopped working rather than asserting the endpoint returned 200.

The original deny-all was justified by the login path: a refresh token is
looked up before any tenant is known, so no tenant-scoped policy could
serve it, and the lookup runs on the BYPASSRLS platform role instead. That
reasoning still holds, and this policy does not weaken it — with no
`app.current_company_id` set, the subquery matches nothing and the table
stays deny-all exactly as before. What it adds is the one genuinely
tenant-scoped operation on this table: an administrator revoking tokens
belonging to a user *in their own company*.

Deliberately not a blanket policy: it is scoped through `users.company_id`,
so a tenant can neither see nor touch another tenant's tokens, and the
token values themselves are stored only as hashes regardless.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '8ba3759b0926'
down_revision: Union[str, Sequence[str], None] = 'd613c7aa375a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE POLICY tenant_own_users ON refresh_tokens "
        "USING (EXISTS (SELECT 1 FROM users u WHERE u.id = refresh_tokens.user_id "
        "               AND u.company_id = current_setting('app.current_company_id', true)::uuid)) "
        "WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = refresh_tokens.user_id "
        "               AND u.company_id = current_setting('app.current_company_id', true)::uuid))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_own_users ON refresh_tokens")
