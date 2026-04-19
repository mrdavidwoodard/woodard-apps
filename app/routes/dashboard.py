from flask import Blueprint, render_template
from flask_login import login_required

from app.models import Client, Document, TaxReturn

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    counts = {
        "clients": Client.query.count(),
        "tax_returns": TaxReturn.query.count(),
        "documents": Document.query.count(),
    }
    recent_documents = Document.query.order_by(Document.uploaded_at.desc()).limit(5).all()
    return render_template("dashboard.html", counts=counts, recent_documents=recent_documents)
