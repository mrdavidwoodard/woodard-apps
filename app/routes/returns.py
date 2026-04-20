from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import Client, Document, TaxReturn
from app import db
from app.services.package_readiness import (
    initialize_requirements_for_package,
    package_document_stats,
    recalculate_package_readiness,
    requirements_for,
)

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


@returns_bp.route("/tax-return/new", methods=["GET", "POST"])
@login_required
def create_tax_return():
    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        tax_year = request.form.get("tax_year", "").strip()
        work_type = request.form.get("work_type", "").strip()

        if not client_name or not tax_year or not work_type:
            flash("Client name, tax year, and work type are required.", "danger")
            return render_template("create_tax_return.html", form_data=request.form)

        try:
            tax_year_int = int(tax_year)
        except ValueError:
            flash("Tax year must be a valid number.", "danger")
            return render_template("create_tax_return.html", form_data=request.form)

        client = Client.query.filter(Client.display_name.ilike(client_name)).first()
        if not client:
            client = Client(display_name=client_name, client_type="individual")
            db.session.add(client)
            db.session.flush()

        tax_return = TaxReturn(
            client=client,
            tax_year=tax_year_int,
            return_type=work_type,
            work_type=work_type,
            status="waiting_on_client",
            assigned_user=current_user,
        )

        db.session.add(tax_return)
        db.session.flush()

        initialize_requirements_for_package(tax_return)
        recalculate_package_readiness(tax_return)
        db.session.commit()

        flash("Client work created with default organizer requirements.", "success")
        return redirect(url_for("packages.detail", package_id=tax_return.id))

    return render_template("create_tax_return.html")


@returns_bp.route("/returns/<int:tax_return_id>")
@login_required
def returns_detail(tax_return_id):
    tax_return = TaxReturn.query.get_or_404(tax_return_id)
    recalculate_package_readiness(tax_return)
    db.session.commit()
    documents = tax_return.documents.order_by(Document.uploaded_at.desc()).all()
    return render_template(
        "returns/detail.html",
        tax_return=tax_return,
        documents=documents,
        package_stats=package_document_stats(tax_return),
        requirements=requirements_for(tax_return),
    )


@returns_bp.route("/documents/<int:document_id>/file")
@login_required
def document_file(document_id):
    return redirect(url_for("documents.file", document_id=document_id))
