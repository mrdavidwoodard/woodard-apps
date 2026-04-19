import json

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app import db
from app.models import Document, ExtractionResult, TaxReturn, utc_now

prep_bp = Blueprint("prep", __name__, url_prefix="/prep")


def approved_documents_for(tax_return):
    return tax_return.documents.filter(Document.status == "approved").order_by(Document.uploaded_at.desc()).all()


def latest_result_for(document):
    return document.extraction_results.order_by(ExtractionResult.created_at.desc()).first()


def format_other_json(value):
    return json.dumps(value or {}, indent=2, sort_keys=True)


def extracted_value(extracted, field_name):
    fields = extracted.get("fields") if isinstance(extracted, dict) else None
    if isinstance(fields, dict) and isinstance(fields.get(field_name), dict):
        return fields[field_name].get("value")
    return extracted.get(field_name) if isinstance(extracted, dict) else None


def prep_summary_for(documents):
    summary = []
    for document in documents:
        latest_result = latest_result_for(document)
        if not latest_result:
            summary.append({"document": document, "result": None, "kind": "missing", "fields": {}, "json_text": ""})
            continue

        extracted = latest_result.extracted_json or {}
        detected_type = (latest_result.document_type_detected or document.document_type or "").lower()
        if detected_type == "w2":
            fields = {
                "Employer": extracted_value(extracted, "employer_name"),
                "EIN": extracted_value(extracted, "ein"),
                "Wages": extracted_value(extracted, "wages"),
                "Federal Withholding": extracted_value(extracted, "federal_withholding"),
                "State Wages": extracted_value(extracted, "state_wages"),
            }
            summary.append({"document": document, "result": latest_result, "kind": "w2", "fields": fields, "json_text": ""})
        elif detected_type in {"1099_int", "1099-int"}:
            fields = {
                "Payer": extracted_value(extracted, "payer_name"),
                "Interest Income": extracted_value(extracted, "interest_income"),
                "Federal Withholding": extracted_value(extracted, "federal_withholding"),
            }
            summary.append({"document": document, "result": latest_result, "kind": "1099_int", "fields": fields, "json_text": ""})
        else:
            summary.append({
                "document": document,
                "result": latest_result,
                "kind": "other",
                "fields": {},
                "json_text": format_other_json(extracted),
            })
    return summary


@prep_bp.route("/queue")
@login_required
def queue():
    tax_returns = (
        TaxReturn.query.filter_by(status="ready_for_prep")
        .order_by(TaxReturn.tax_year.desc(), TaxReturn.created_at.desc())
        .all()
    )
    rows = [
        {
            "tax_return": tax_return,
            "approved_document_count": tax_return.documents.filter(Document.status == "approved").count(),
        }
        for tax_return in tax_returns
    ]
    return render_template("prep/queue.html", rows=rows)


@prep_bp.route("/tax-return/<int:tax_return_id>")
@login_required
def detail(tax_return_id):
    tax_return = TaxReturn.query.get_or_404(tax_return_id)
    approved_documents = approved_documents_for(tax_return)
    document_rows = [
        {"document": document, "latest_result": latest_result_for(document)}
        for document in approved_documents
    ]
    return render_template(
        "prep/detail.html",
        tax_return=tax_return,
        approved_documents=approved_documents,
        document_rows=document_rows,
        prep_summary=prep_summary_for(approved_documents),
    )


@prep_bp.route("/tax-return/<int:tax_return_id>/start", methods=["POST"])
@login_required
def start(tax_return_id):
    tax_return = TaxReturn.query.get_or_404(tax_return_id)
    tax_return.status = "in_prep"
    if not tax_return.prep_started_at:
        tax_return.prep_started_at = utc_now()
    db.session.commit()
    flash("Prep started.", "success")
    return redirect(url_for("prep.detail", tax_return_id=tax_return.id))


@prep_bp.route("/tax-return/<int:tax_return_id>/complete", methods=["POST"])
@login_required
def complete(tax_return_id):
    tax_return = TaxReturn.query.get_or_404(tax_return_id)
    tax_return.status = "in_review"
    tax_return.prep_completed_at = utc_now()
    db.session.commit()
    flash("Prep completed and moved to review.", "success")
    return redirect(url_for("prep.detail", tax_return_id=tax_return.id))
