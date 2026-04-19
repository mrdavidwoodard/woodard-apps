"""add package extraction fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-19 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        if "is_ready_for_extraction" not in existing_columns:
            batch_op.add_column(sa.Column("is_ready_for_extraction", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "extraction_started_at" not in existing_columns:
            batch_op.add_column(sa.Column("extraction_started_at", sa.DateTime(timezone=True), nullable=True))
        if "extraction_completed_at" not in existing_columns:
            batch_op.add_column(sa.Column("extraction_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        if "extraction_completed_at" in existing_columns:
            batch_op.drop_column("extraction_completed_at")
        if "extraction_started_at" in existing_columns:
            batch_op.drop_column("extraction_started_at")
        if "is_ready_for_extraction" in existing_columns:
            batch_op.drop_column("is_ready_for_extraction")
