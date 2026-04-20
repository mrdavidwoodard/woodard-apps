"""add requirement expectation metadata

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-04-19 13:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("package_document_requirements")}

    with op.batch_alter_table("package_document_requirements", schema=None) as batch_op:
        if "expectation_source" not in existing_columns:
            batch_op.add_column(sa.Column("expectation_source", sa.String(length=50), nullable=True))
        if "is_expected_this_year" not in existing_columns:
            batch_op.add_column(
                sa.Column("is_expected_this_year", sa.Boolean(), nullable=False, server_default=sa.true())
            )
        if "is_confirmed_this_year" not in existing_columns:
            batch_op.add_column(
                sa.Column("is_confirmed_this_year", sa.Boolean(), nullable=False, server_default=sa.false())
            )

    bind.execute(
        sa.text(
            "UPDATE package_document_requirements "
            "SET expectation_source = COALESCE(expectation_source, 'template')"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE package_document_requirements "
            "SET is_required = 0 "
            "WHERE lower(document_type) = 'organizer'"
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("package_document_requirements")}

    with op.batch_alter_table("package_document_requirements", schema=None) as batch_op:
        if "is_confirmed_this_year" in existing_columns:
            batch_op.drop_column("is_confirmed_this_year")
        if "is_expected_this_year" in existing_columns:
            batch_op.drop_column("is_expected_this_year")
        if "expectation_source" in existing_columns:
            batch_op.drop_column("expectation_source")
