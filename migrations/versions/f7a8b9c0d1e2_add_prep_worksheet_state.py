"""add prep worksheet state

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-19 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    if "prep_worksheet_state" not in existing_columns:
        with op.batch_alter_table("tax_returns", schema=None) as batch_op:
            batch_op.add_column(sa.Column("prep_worksheet_state", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    if "prep_worksheet_state" in existing_columns:
        with op.batch_alter_table("tax_returns", schema=None) as batch_op:
            batch_op.drop_column("prep_worksheet_state")
