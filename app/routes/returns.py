from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, send_from_directory
from flask_login import login_required

from app.models import Document, TaxReturn

returns_bp = Blueprint("returns", __name__)


@returns_bp.route("/returns")
@login_required
def returns_index():
    returns = (
        TaxReturn.query.join(TaxReturn.client)
        .order_by(TaxReturn.tax_year.desc(), TaxReturn.created_at.desc())
        .all()
    )
    return render_template("returns/index.html", returns=returns)


@returns_bp.route("/returns/<int:tax_return_id>")
@login_required
def returns_detail(tax_return_id):
    tax_return = TaxReturn.query.get_or_404(tax_return_id)
    documents = tax_return.documents.order_by(Document.uploaded_at.desc()).all()
    return render_template("returns/detail.html", tax_return=tax_return, documents=documents)


@returns_bp.route("/documents/<int:document_id>/file")
@login_required
def document_file(document_id):
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
