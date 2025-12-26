"""add user access token

Revision ID: 7a1e6eebf2a2
Revises: 8852d8c4e962
Create Date: 2025-12-25 23:47:24.562527

"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a1e6eebf2a2'
down_revision: Union[str, Sequence[str], None] = '8852d8c4e962'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add fingerprint index if not exists (from previous migration that may have partially run)
    try:
        op.create_index(op.f('ix_jobs_fingerprint'), 'jobs', ['fingerprint'], unique=False)
    except Exception:
        pass  # Index may already exist

    # Add access_token column as nullable first
    op.add_column('users', sa.Column('access_token', sa.String(length=64), nullable=True))

    # Backfill tokens for existing users
    connection = op.get_bind()
    users = connection.execute(sa.text("SELECT id FROM users WHERE access_token IS NULL"))
    for row in users:
        token = secrets.token_urlsafe(32)
        connection.execute(
            sa.text("UPDATE users SET access_token = :token WHERE id = :id"),
            {"token": token, "id": row[0]}
        )

    # Now create the unique index
    op.create_index(op.f('ix_users_access_token'), 'users', ['access_token'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_users_access_token'), table_name='users')
    op.drop_column('users', 'access_token')
    try:
        op.drop_index(op.f('ix_jobs_fingerprint'), table_name='jobs')
    except Exception:
        pass
