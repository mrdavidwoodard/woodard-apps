from flask import Blueprint, redirect, render_template, url_for
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
    return redirect(url_for("documents.file", document_id=document_id))
