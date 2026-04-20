from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import login_required

from app import db
from app.models import Document, PackageDocumentRequirement, TaxReturn, utc_now
from app.routes.documents import run_mock_extraction_for_document
from app.services.package_readiness import (
    package_document_stats,
    recalculate_package_readiness,
    requirements_for,
)

packages_bp = Blueprint("packages", __name__, url_prefix="/packages")
requirements_bp = Blueprint("requirements", __name__, url_prefix="/requirements")


@packages_bp.route("")
@login_required
def index():
    packages = (
        TaxReturn.query.join(TaxReturn.client)
        .order_by(TaxReturn.tax_year.desc(), TaxReturn.created_at.desc())
        .all()
    )
    for package in packages:
        recalculate_package_readiness(package)
    db.session.commit()
    return render_template("returns/index.html", returns=packages)


@packages_bp.route("/<int:package_id>")
@login_required
def detail(package_id):
    package = TaxReturn.query.get_or_404(package_id)
    recalculate_package_readiness(package)
    db.session.commit()
    documents = package.documents.order_by(Document.uploaded_at.desc()).all()
    return render_template(
        "returns/detail.html",
        tax_return=package,
        documents=documents,
        package_stats=package_document_stats(package),
        requirements=requirements_for(package),
    )


@packages_bp.route("/<int:package_id>/run-extraction", methods=["POST"])
@login_required
def run_extraction(package_id):
    package = TaxReturn.query.get_or_404(package_id)
    completeness = recalculate_package_readiness(package)
    db.session.commit()
    if not package.is_ready_for_extraction:
        flash(
            f"Package not ready for extraction. {completeness['received_required']} of "
            f"{completeness['total_required']} required documents received.",
            "danger",
        )
        return redirect(url_for("packages.detail", package_id=package.id))

    package.status = "extraction_in_progress"
    package.is_ready_for_extraction = False
    package.is_waiting_on_client = False
    package.extraction_started_at = utc_now()
    package.extraction_completed_at = None
    db.session.commit()
    flash("Package extraction started.", "info")

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    documents = package.documents.order_by(Document.uploaded_at.asc()).all()
    for document in documents:
        if document.extraction_results.count():
            skipped_count += 1
            continue

        try:
            run_mock_extraction_for_document(document)
            processed_count += 1
        except Exception as exc:
            failed_count += 1
            current_app.logger.exception("Package extraction failed for document_id=%s", document.id)
            document.status = "exception"
            if document.extraction_jobs.count() == 0:
                current_app.logger.warning("No extraction job was recorded for failed document_id=%s: %s", document.id, exc)

    package.extraction_completed_at = utc_now()
    package.is_waiting_on_client = False
    package.is_ready_for_extraction = False
    if any(document.status == "exception" for document in documents):
        package.status = "exceptions_pending"
        outcome_message = "Package extraction completed with exceptions. Package moved to exceptions pending."
        outcome_category = "warning"
    else:
        package.status = "organizer_review_pending"
        outcome_message = "Package extraction completed. Package moved to organizer review pending."
        outcome_category = "success"

    db.session.commit()

    if skipped_count:
        flash(f"Skipped {skipped_count} document(s) that already had extraction results.", "info")
    flash(f"Processed {processed_count} document(s); {failed_count} exception(s).", "info")
    flash(outcome_message, outcome_category)
    return redirect(url_for("packages.detail", package_id=package.id))


@requirements_bp.route("/<int:requirement_id>/not-expected", methods=["POST"])
@login_required
def mark_not_expected(requirement_id):
    requirement = PackageDocumentRequirement.query.get_or_404(requirement_id)
    package = requirement.tax_return
    requirement.is_expected_this_year = False
    requirement.is_required = False
    requirement.is_confirmed_this_year = True
    recalculate_package_readiness(package)
    db.session.commit()
    flash(f"{requirement.name or requirement.display_name} marked not expected this year.", "success")
    return redirect(url_for("packages.detail", package_id=package.id))


@requirements_bp.route("/<int:requirement_id>/expected", methods=["POST"])
@login_required
def mark_expected(requirement_id):
    requirement = PackageDocumentRequirement.query.get_or_404(requirement_id)
    package = requirement.tax_return
    requirement.is_expected_this_year = True
    requirement.is_required = True
    requirement.is_confirmed_this_year = True
    recalculate_package_readiness(package)
    db.session.commit()
    flash(f"{requirement.name or requirement.display_name} marked expected this year.", "success")
    return redirect(url_for("packages.detail", package_id=package.id))
