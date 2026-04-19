import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import Document, ExtractionResult, ReviewAction

compiler_bp = Blueprint("compiler", __name__, url_prefix="/compiler")


def latest_result_for(document):
    return document.extraction_results.order_by(ExtractionResult.created_at.desc()).first()


def review_history_for(document):
    return document.review_actions.order_by(ReviewAction.reviewed_at.desc()).all()


def all_documents_approved(tax_return):
    documents = tax_return.documents.all()
    return bool(documents) and all(document.status == "approved" for document in documents)


def mark_ready_for_prep_if_complete(tax_return):
    if all_documents_approved(tax_return) and not tax_return.is_waiting_on_client:
        tax_return.status = "ready_for_prep"


def create_review_action(document, action_type, latest_result=None, notes=None, field_changes=None):
    review_action = ReviewAction(
        tax_return=document.tax_return,
        document=document,
        extraction_result=latest_result,
        reviewed_by_user=current_user,
        action_type=action_type,
        notes=notes,
        field_changes_json=field_changes,
    )
    db.session.add(review_action)
    return review_action


@compiler_bp.route("/queue")
@login_required
def queue():
    documents = Document.query.filter_by(status="review_pending").order_by(Document.uploaded_at.desc()).all()
    rows = [{"document": document, "latest_result": latest_result_for(document)} for document in documents]
    return render_template("compiler/queue.html", rows=rows)


@compiler_bp.route("/document/<int:document_id>")
@login_required
def document_detail(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)
    extracted_json_text = json.dumps(latest_result.extracted_json, indent=2, sort_keys=True) if latest_result else ""
    return render_template(
        "compiler/document_detail.html",
        document=document,
        latest_result=latest_result,
        extracted_json_text=extracted_json_text,
        review_actions=review_history_for(document),
    )


@compiler_bp.route("/document/<int:document_id>/approve", methods=["POST"])
@login_required
def approve(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)

    create_review_action(document, "approved", latest_result=latest_result)
    document.status = "approved"
    mark_ready_for_prep_if_complete(document.tax_return)
    db.session.commit()

    flash("Document approved.", "success")
    return redirect(url_for("compiler.document_detail", document_id=document.id))


@compiler_bp.route("/document/<int:document_id>/correct", methods=["POST"])
@login_required
def correct(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)
    if not latest_result:
        flash("This document does not have an extraction result to correct.", "danger")
        return redirect(url_for("compiler.document_detail", document_id=document.id))

    raw_json = request.form.get("extracted_json", "").strip()
    try:
        corrected_json = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        flash(f"Corrected extraction JSON is invalid: {exc.msg}.", "danger")
        return redirect(url_for("compiler.document_detail", document_id=document.id))

    latest_result.extracted_json = corrected_json
    create_review_action(
        document,
        "corrected",
        latest_result=latest_result,
        notes="Extraction result manually corrected and approved.",
        field_changes={"summary": "Extraction result manually corrected in Compiler."},
    )
    document.status = "approved"
    mark_ready_for_prep_if_complete(document.tax_return)
    db.session.commit()

    flash("Correction saved and document approved.", "success")
    return redirect(url_for("compiler.document_detail", document_id=document.id))


@compiler_bp.route("/document/<int:document_id>/escalate", methods=["POST"])
@login_required
def escalate(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)
    notes = request.form.get("notes", "").strip()
    if not notes:
        flash("Escalation notes are required.", "danger")
        return redirect(url_for("compiler.document_detail", document_id=document.id))

    create_review_action(document, "escalated", latest_result=latest_result, notes=notes)
    document.status = "exception"
    document.tax_return.status = "on_hold"
    db.session.commit()

    flash("Document escalated for follow-up.", "success")
    return redirect(url_for("compiler.document_detail", document_id=document.id))
