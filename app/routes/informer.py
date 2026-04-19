from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func, or_

from app import db
from app.models import Client, Document, ExtractionJob, ExtractionResult, TaxReturn

informer_bp = Blueprint("informer", __name__, url_prefix="/informer")


def status_counts(model):
    return (
        db.session.query(model.status, func.count(model.id))
        .group_by(model.status)
        .order_by(model.status)
        .all()
    )


def latest_result_for(document):
    return document.extraction_results.order_by(ExtractionResult.created_at.desc()).first()


def is_ready_for_prep(tax_return):
    """Centralize v1 readiness logic so future rules are easy to refine."""
    documents = tax_return.documents.all()
    return bool(documents) and not tax_return.is_waiting_on_client and all(
        document.status == "approved" for document in documents
    )


@informer_bp.route("/overview")
@login_required
def overview():
    counts = {
        "clients": Client.query.count(),
        "tax_returns": TaxReturn.query.count(),
        "documents": Document.query.count(),
        "extraction_jobs": ExtractionJob.query.count(),
        "extraction_results": ExtractionResult.query.count(),
        "documents_pending_review": Document.query.filter_by(status="review_pending").count(),
        "returns_waiting_on_client": TaxReturn.query.filter_by(is_waiting_on_client=True).count(),
    }
    latest_documents = Document.query.order_by(Document.uploaded_at.desc()).limit(10).all()
    return render_template(
        "informer/overview.html",
        counts=counts,
        tax_return_status_counts=status_counts(TaxReturn),
        document_status_counts=status_counts(Document),
        latest_documents=latest_documents,
    )


@informer_bp.route("/review-pending")
@login_required
def review_pending():
    documents = Document.query.filter_by(status="review_pending").order_by(Document.uploaded_at.desc()).all()
    rows = [{"document": document, "latest_result": latest_result_for(document)} for document in documents]
    return render_template("informer/review_pending.html", rows=rows)


@informer_bp.route("/ready-for-prep")
@login_required
def ready_for_prep():
    tax_returns = TaxReturn.query.order_by(TaxReturn.tax_year.desc(), TaxReturn.created_at.desc()).all()
    ready_returns = [
        {"tax_return": tax_return, "document_count": tax_return.documents.count()}
        for tax_return in tax_returns
        if is_ready_for_prep(tax_return)
    ]
    return render_template("informer/ready_for_prep.html", ready_returns=ready_returns)


@informer_bp.route("/missing-docs")
@login_required
def missing_docs():
    tax_returns = (
        TaxReturn.query.filter(
            or_(
                TaxReturn.is_waiting_on_client.is_(True),
                func.trim(func.coalesce(TaxReturn.missing_docs_notes, "")) != "",
            )
        )
        .order_by(TaxReturn.tax_year.desc(), TaxReturn.created_at.desc())
        .all()
    )
    return render_template("informer/missing_docs.html", tax_returns=tax_returns)
