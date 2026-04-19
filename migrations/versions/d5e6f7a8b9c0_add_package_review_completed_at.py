"""add package review completed at

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    if "review_completed_at" not in existing_columns:
        with op.batch_alter_table("tax_returns", schema=None) as batch_op:
            batch_op.add_column(sa.Column("review_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    if "review_completed_at" in existing_columns:
        with op.batch_alter_table("tax_returns", schema=None) as batch_op:
            batch_op.drop_column("review_completed_at")
