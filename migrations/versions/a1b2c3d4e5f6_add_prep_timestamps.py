"""add prep timestamps

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-04-18 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        if "prep_started_at" not in existing_columns:
            batch_op.add_column(sa.Column("prep_started_at", sa.DateTime(timezone=True), nullable=True))
        if "prep_completed_at" not in existing_columns:
            batch_op.add_column(sa.Column("prep_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        if "prep_completed_at" in existing_columns:
            batch_op.drop_column("prep_completed_at")
        if "prep_started_at" in existing_columns:
            batch_op.drop_column("prep_started_at")
