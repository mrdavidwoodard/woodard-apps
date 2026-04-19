"""add review actions

Revision ID: c3f1a7b9d204
Revises: b7d4e2f6a901
Create Date: 2026-04-18 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3f1a7b9d204"
down_revision = "b7d4e2f6a901"
branch_labels = None
depends_on = None


INDEXES = {
    "ix_review_actions_document_id": ["document_id"],
    "ix_review_actions_extraction_result_id": ["extraction_result_id"],
    "ix_review_actions_reviewed_by_user_id": ["reviewed_by_user_id"],
    "ix_review_actions_tax_return_id": ["tax_return_id"],
}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("review_actions"):
        op.create_table(
            "review_actions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tax_return_id", sa.Integer(), nullable=False),
            sa.Column("document_id", sa.Integer(), nullable=False),
            sa.Column("extraction_result_id", sa.Integer(), nullable=True),
            sa.Column("reviewed_by_user_id", sa.Integer(), nullable=False),
            sa.Column("action_type", sa.String(length=50), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
            sa.ForeignKeyConstraint(["extraction_result_id"], ["extraction_results.id"]),
            sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["tax_return_id"], ["tax_returns.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {index["name"] for index in inspector.get_indexes("review_actions")}
    for index_name, columns in INDEXES.items():
        if index_name not in existing_indexes:
            op.create_index(index_name, "review_actions", columns, unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("review_actions"):
        existing_indexes = {index["name"] for index in inspector.get_indexes("review_actions")}
        for index_name in reversed(tuple(INDEXES)):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="review_actions")

        op.drop_table("review_actions")
