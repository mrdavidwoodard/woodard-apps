from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, send_from_directory, url_for
from flask_login import login_required

from app import db
from app.models import Document, ExtractionJob, ExtractionResult, utc_now

documents_bp = Blueprint("documents", __name__)


def build_mock_extraction(document):
    """Return deterministic mock extraction data for the current document type."""
    document_type = (document.document_type or "").lower()

    if document_type == "w2":
        extracted_json = {
            "employer_name": "Mock Employer Inc.",
            "ein": "12-3456789",
            "wages": 84500.00,
            "federal_withholding": 12350.00,
            "state_wages": 84500.00,
        }
        detected_type = "w2"
        confidence = 0.95
    elif document_type in {"1099", "1099_int"}:
        extracted_json = {
            "payer_name": "Mock Financial Institution",
            "interest_income": 248.39,
            "federal_withholding": 0.00,
        }
        detected_type = "1099_int"
        confidence = 0.90
    else:
        extracted_json = {
            "detected_document_type": document.document_type,
            "notes": "Generic mock extraction generated for this document type.",
            "placeholder_fields": {
                "client_name": document.client.display_name,
                "tax_year": document.tax_return.tax_year,
                "file_name": document.original_file_name or document.file_name,
            },
        }
        detected_type = document.document_type
        confidence = 0.75

    return {
        "document_type_detected": detected_type,
        "confidence_score": confidence,
        "extracted_json": extracted_json,
        "validation_messages_json": ["Mock extraction completed successfully"],
        "model_name": "mock-extractor-v1",
    }


@documents_bp.route("/documents/<int:document_id>")
@login_required
def detail(document_id):
    document = Document.query.get_or_404(document_id)
    extraction_jobs = document.extraction_jobs.order_by(ExtractionJob.created_at.desc()).all()
    latest_result = document.extraction_results.order_by(ExtractionResult.created_at.desc()).first()
    return render_template(
        "documents/detail.html",
        document=document,
        extraction_jobs=extraction_jobs,
        latest_result=latest_result,
    )


@documents_bp.route("/documents/<int:document_id>/extract", methods=["POST"])
@login_required
def extract(document_id):
    document = Document.query.get_or_404(document_id)
    now = utc_now()
    job = ExtractionJob(
        document=document,
        tax_return=document.tax_return,
        job_type="extract",
        status="running",
        attempt_count=1,
        max_attempts=2,
        started_at=now,
    )

    try:
        db.session.add(job)
        db.session.flush()

        mock_result = build_mock_extraction(document)
        job.status = "completed"
        job.completed_at = utc_now()

        result = ExtractionResult(
            extraction_job=job,
            document=document,
            tax_return=document.tax_return,
            document_type_detected=mock_result["document_type_detected"],
            confidence_score=mock_result["confidence_score"],
            validation_status="passed",
            is_ready_for_review=True,
            extracted_json=mock_result["extracted_json"],
            validation_messages_json=mock_result["validation_messages_json"],
            model_name=mock_result["model_name"],
        )
        db.session.add(result)

        document.status = "review_pending"
        if document.tax_return.status in {"new", "documents_received"}:
            document.tax_return.status = "review_pending"

        db.session.commit()
        flash("Mock extraction completed. Document is ready for review.", "success")
    except Exception as exc:
        db.session.rollback()
        job.status = "failed"
        job.completed_at = utc_now()
        job.error_code = "mock_extractor_error"
        job.error_message = str(exc)
        db.session.add(job)
        db.session.commit()
        current_app.logger.exception("Mock extraction failed for document_id=%s", document.id)
        flash("Mock extraction failed. Please try again.", "danger")

    return redirect(url_for("documents.detail", document_id=document.id))


@documents_bp.route("/documents/<int:document_id>/file")
@login_required
def file(document_id):
    document = Document.query.get_or_404(document_id)
    if not document.stored_file_path:
        abort(404)

    upload_root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    requested_path = (upload_root / document.stored_file_path).resolve()

    # Keep development file serving constrained to the configured upload folder.
    if upload_root not in requested_path.parents and requested_path != upload_root:
        abort(404)

    if not requested_path.exists() or not requested_path.is_file():
        abort(404)

    relative_directory = requested_path.parent.relative_to(upload_root)
    return send_from_directory(upload_root / relative_directory, requested_path.name, as_attachment=False)
