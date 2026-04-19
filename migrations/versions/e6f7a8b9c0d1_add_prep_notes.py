"""add prep notes

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-04-19 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    if "prep_notes" not in existing_columns:
        with op.batch_alter_table("tax_returns", schema=None) as batch_op:
            batch_op.add_column(sa.Column("prep_notes", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    if "prep_notes" in existing_columns:
        with op.batch_alter_table("tax_returns", schema=None) as batch_op:
            batch_op.drop_column("prep_notes")
