"""add work type to client work

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-04-19 13:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}

    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        if "work_type" not in existing_columns:
            batch_op.add_column(sa.Column("work_type", sa.String(length=50), nullable=True))

    if "work_type" not in existing_columns:
        bind.execute(
            sa.text(
                "UPDATE tax_returns "
                "SET work_type = return_type "
                "WHERE work_type IS NULL AND return_type IS NOT NULL"
            )
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("tax_returns")}

    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        if "work_type" in existing_columns:
            batch_op.drop_column("work_type")
