"""add review action field changes

Revision ID: d8e9f0a1b2c3
Revises: c3f1a7b9d204
Create Date: 2026-04-18 19:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d8e9f0a1b2c3"
down_revision = "c3f1a7b9d204"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("review_actions")}
    if "field_changes_json" not in existing_columns:
        with op.batch_alter_table("review_actions", schema=None) as batch_op:
            batch_op.add_column(sa.Column("field_changes_json", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("review_actions")}
    if "field_changes_json" in existing_columns:
        with op.batch_alter_table("review_actions", schema=None) as batch_op:
            batch_op.drop_column("field_changes_json")
