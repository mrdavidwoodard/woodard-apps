import sys
from pathlib import Path

from flask import Flask, flash, redirect, request, url_for
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import RequestEntityTooLarge

from config import config_by_name

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


def _running_flask_db_command():
    command_name = Path(sys.argv[0]).stem
    return len(sys.argv) > 2 and command_name == "flask" and sys.argv[1] == "db"


def create_app(config_name=None):
    """Create and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name(config_name))

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from app.models import User, seed_default_user
    from app.routes.auth import auth_bp
    from app.routes.compiler import compiler_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.documents import documents_bp
    from app.routes.informer import informer_bp
    from app.routes.ingester import ingester_bp
    from app.routes.returns import returns_bp

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(compiler_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(informer_bp)
    app.register_blueprint(ingester_bp)
    app.register_blueprint(returns_bp)

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.dashboard"))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(error):
        flash("Uploaded files must be 25 MB or smaller.", "danger")
        return redirect(request.referrer or url_for("ingester.upload"))

    if app.config.get("AUTO_CREATE_DATABASE") and not _running_flask_db_command():
        with app.app_context():
            db.create_all()
            if app.config.get("CREATE_DEFAULT_USER"):
                seed_default_user()

    return app
