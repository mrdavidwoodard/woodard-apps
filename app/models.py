from datetime import datetime, timezone

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="user")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    assigned_tax_returns = db.relationship(
        "TaxReturn",
        foreign_keys="TaxReturn.assigned_user_id",
        back_populates="assigned_user",
        lazy="dynamic",
    )
    reviewing_tax_returns = db.relationship(
        "TaxReturn",
        foreign_keys="TaxReturn.reviewer_user_id",
        back_populates="reviewer_user",
        lazy="dynamic",
    )
    uploaded_documents = db.relationship(
        "Document",
        foreign_keys="Document.uploaded_by_user_id",
        back_populates="uploaded_by_user",
        lazy="dynamic",
    )
    review_actions = db.relationship(
        "ReviewAction",
        foreign_keys="ReviewAction.reviewed_by_user_id",
        back_populates="reviewed_by_user",
        lazy="dynamic",
    )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(255), nullable=False, index=True)
    client_type = db.Column(db.String(80), nullable=False)
    primary_contact_name = db.Column(db.String(255), nullable=True)
    primary_contact_email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    sharepoint_folder_url = db.Column(db.String(1024), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    tax_returns = db.relationship(
        "TaxReturn",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    documents = db.relationship(
        "Document",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<Client {self.display_name}>"


class TaxReturn(db.Model):
    __tablename__ = "tax_returns"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    tax_year = db.Column(db.Integer, nullable=False)
    return_type = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="new")
    is_waiting_on_client = db.Column(db.Boolean, nullable=False, default=False)
    missing_docs_notes = db.Column(db.Text, nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    reviewer_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    due_date = db.Column(db.Date, nullable=True)
    sharepoint_return_folder_url = db.Column(db.String(1024), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    client = db.relationship("Client", back_populates="tax_returns")
    documents = db.relationship(
        "Document",
        back_populates="tax_return",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    extraction_jobs = db.relationship(
        "ExtractionJob",
        back_populates="tax_return",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    extraction_results = db.relationship(
        "ExtractionResult",
        back_populates="tax_return",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    review_actions = db.relationship(
        "ReviewAction",
        back_populates="tax_return",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    assigned_user = db.relationship(
        "User",
        foreign_keys=[assigned_user_id],
        back_populates="assigned_tax_returns",
    )
    reviewer_user = db.relationship(
        "User",
        foreign_keys=[reviewer_user_id],
        back_populates="reviewing_tax_returns",
    )

    def __repr__(self):
        return f"<TaxReturn client_id={self.client_id} tax_year={self.tax_year} return_type={self.return_type}>"


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    tax_return_id = db.Column(db.Integer, db.ForeignKey("tax_returns.id"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    source = db.Column(db.String(80), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    original_file_name = db.Column(db.String(255), nullable=True)
    stored_file_path = db.Column(db.String(1024), nullable=True)
    original_file_type = db.Column(db.String(50), nullable=True)
    file_size_bytes = db.Column(db.Integer, nullable=True)
    page_count = db.Column(db.Integer, nullable=True)
    document_type = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="uploaded")
    sharepoint_file_url = db.Column(db.String(1024), nullable=True)
    sharepoint_item_id = db.Column(db.String(255), nullable=True)
    sharepoint_drive_id = db.Column(db.String(255), nullable=True)
    sharepoint_upload_status = db.Column(db.String(50), nullable=True)
    sharepoint_folder_path = db.Column(db.String(1024), nullable=True)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    ingested_at = db.Column(db.DateTime(timezone=True), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    tax_return = db.relationship("TaxReturn", back_populates="documents")
    client = db.relationship("Client", back_populates="documents")
    uploaded_by_user = db.relationship(
        "User",
        foreign_keys=[uploaded_by_user_id],
        back_populates="uploaded_documents",
    )
    extraction_jobs = db.relationship(
        "ExtractionJob",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    extraction_results = db.relationship(
        "ExtractionResult",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    review_actions = db.relationship(
        "ReviewAction",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<Document {self.file_name}>"


class ExtractionJob(db.Model):
    __tablename__ = "extraction_jobs"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    tax_return_id = db.Column(db.Integer, db.ForeignKey("tax_returns.id"), nullable=False, index=True)
    job_type = db.Column(db.String(80), nullable=False, default="extract")
    status = db.Column(db.String(50), nullable=False, default="queued")
    attempt_count = db.Column(db.Integer, nullable=False, default=1)
    max_attempts = db.Column(db.Integer, nullable=False, default=2)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_code = db.Column(db.String(80), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    document = db.relationship("Document", back_populates="extraction_jobs")
    tax_return = db.relationship("TaxReturn", back_populates="extraction_jobs")
    extraction_results = db.relationship(
        "ExtractionResult",
        back_populates="extraction_job",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<ExtractionJob document_id={self.document_id} status={self.status}>"


class ExtractionResult(db.Model):
    __tablename__ = "extraction_results"

    id = db.Column(db.Integer, primary_key=True)
    extraction_job_id = db.Column(db.Integer, db.ForeignKey("extraction_jobs.id"), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    tax_return_id = db.Column(db.Integer, db.ForeignKey("tax_returns.id"), nullable=False, index=True)
    document_type_detected = db.Column(db.String(80), nullable=True)
    confidence_score = db.Column(db.Float, nullable=True)
    validation_status = db.Column(db.String(50), nullable=False, default="passed")
    is_ready_for_review = db.Column(db.Boolean, nullable=False, default=True)
    extracted_json = db.Column(db.JSON, nullable=False)
    validation_messages_json = db.Column(db.JSON, nullable=True)
    model_name = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    extraction_job = db.relationship("ExtractionJob", back_populates="extraction_results")
    document = db.relationship("Document", back_populates="extraction_results")
    tax_return = db.relationship("TaxReturn", back_populates="extraction_results")
    review_actions = db.relationship(
        "ReviewAction",
        back_populates="extraction_result",
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<ExtractionResult document_id={self.document_id} confidence={self.confidence_score}>"


class ReviewAction(db.Model):
    __tablename__ = "review_actions"

    id = db.Column(db.Integer, primary_key=True)
    tax_return_id = db.Column(db.Integer, db.ForeignKey("tax_returns.id"), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    extraction_result_id = db.Column(db.Integer, db.ForeignKey("extraction_results.id"), nullable=True, index=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action_type = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    field_changes_json = db.Column(db.JSON, nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    tax_return = db.relationship("TaxReturn", back_populates="review_actions")
    document = db.relationship("Document", back_populates="review_actions")
    extraction_result = db.relationship("ExtractionResult", back_populates="review_actions")
    reviewed_by_user = db.relationship(
        "User",
        foreign_keys=[reviewed_by_user_id],
        back_populates="review_actions",
    )

    def __repr__(self):
        return f"<ReviewAction document_id={self.document_id} action_type={self.action_type}>"


def seed_default_user():
    """Create a local development user when one does not already exist."""
    email = current_app.config["DEFAULT_USER_EMAIL"]
    existing_user = User.query.filter_by(email=email).first()

    if existing_user:
        return

    user = User(
        first_name=current_app.config["DEFAULT_USER_FIRST_NAME"],
        last_name=current_app.config["DEFAULT_USER_LAST_NAME"],
        email=email,
        role=current_app.config["DEFAULT_USER_ROLE"],
    )
    user.set_password(current_app.config["DEFAULT_USER_PASSWORD"])

    db.session.add(user)
    db.session.commit()
