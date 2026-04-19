"""add package document requirements

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-04-19 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


INDEXES = {
    "ix_package_document_requirements_document_id": ["document_id"],
    "ix_package_document_requirements_tax_return_id": ["tax_return_id"],
}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("package_document_requirements"):
        op.create_table(
            "package_document_requirements",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tax_return_id", sa.Integer(), nullable=False),
            sa.Column("document_id", sa.Integer(), nullable=True),
            sa.Column("document_type", sa.String(length=80), nullable=False),
            sa.Column("display_name", sa.String(length=120), nullable=False),
            sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_received", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
            sa.ForeignKeyConstraint(["tax_return_id"], ["tax_returns.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {index["name"] for index in inspector.get_indexes("package_document_requirements")}
    for index_name, columns in INDEXES.items():
        if index_name not in existing_indexes:
            op.create_index(index_name, "package_document_requirements", columns, unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("package_document_requirements"):
        existing_indexes = {index["name"] for index in inspector.get_indexes("package_document_requirements")}
        for index_name in reversed(tuple(INDEXES)):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="package_document_requirements")
        op.drop_table("package_document_requirements")
