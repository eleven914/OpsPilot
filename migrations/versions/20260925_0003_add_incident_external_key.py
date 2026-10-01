"""Add idempotency key for externally sourced incidents.

Revision ID: 20260925_0003
Revises: 20260924_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0003"
down_revision: str | None = "20260924_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.add_column(
            sa.Column("external_key", sa.String(length=200), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_incidents_external_key", ["external_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_constraint("uq_incidents_external_key", type_="unique")
        batch_op.drop_column("external_key")
