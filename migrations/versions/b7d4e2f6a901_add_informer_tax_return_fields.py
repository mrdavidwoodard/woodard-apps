"""add informer tax return fields

Revision ID: b7d4e2f6a901
Revises: 9f8a1c2d3e4b
Create Date: 2026-04-18 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7d4e2f6a901"
down_revision = "9f8a1c2d3e4b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_waiting_on_client", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("missing_docs_notes", sa.Text(), nullable=True))

    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        batch_op.alter_column("is_waiting_on_client", server_default=None)


def downgrade():
    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        batch_op.drop_column("missing_docs_notes")
        batch_op.drop_column("is_waiting_on_client")
