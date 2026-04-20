from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.models import User
from app.services.taxdome import apply_taxdome_organizer_request_event

integrations_bp = Blueprint("integrations", __name__, url_prefix="/integrations")


@integrations_bp.route("/taxdome/organizer-request", methods=["GET", "POST"])
@login_required
def taxdome_organizer_request():
    users = User.query.filter_by(is_active=True).order_by(User.last_name.asc(), User.first_name.asc()).all()

    if request.method == "POST":
        form_data = request.form.to_dict()
        required_values = [
            form_data.get("client_display_name", "").strip(),
            form_data.get("client_type", "").strip(),
            form_data.get("tax_year", "").strip(),
            form_data.get("work_type", "").strip(),
        ]
        if not all(required_values):
            flash("Client display name, client type, tax year, and work type are required.", "danger")
            return render_template("integrations/taxdome_organizer_request.html", users=users, form_data=form_data)

        try:
            int(form_data["tax_year"])
        except ValueError:
            flash("Tax year must be a valid number.", "danger")
            return render_template("integrations/taxdome_organizer_request.html", users=users, form_data=form_data)

        assigned_user = None
        assigned_user_id = form_data.get("assigned_user_id")
        if assigned_user_id:
            assigned_user = db.session.get(User, int(assigned_user_id))

        try:
            result = apply_taxdome_organizer_request_event(form_data, assigned_user=assigned_user)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template("integrations/taxdome_organizer_request.html", users=users, form_data=form_data)

        messages = []
        messages.append("client created" if result["client_created"] else "client reused")
        messages.append("client work created" if result["client_work_created"] else "client work reused")
        messages.append(
            "default organizer requirements created"
            if result["requirements_created"]
            else "existing organizer requirements reused"
        )
        if result.get("expectation_source") == "prior_year" and result.get("prior_package"):
            messages.append(f"expectations seeded from {result['prior_package'].tax_year}")
        elif result.get("expectation_source") == "template":
            messages.append("template expectations used")
        flash(f"Simulated TaxDome organizer request processed: {', '.join(messages)}.", "success")
        return redirect(url_for("packages.detail", package_id=result["client_work"].id))

    return render_template("integrations/taxdome_organizer_request.html", users=users)
