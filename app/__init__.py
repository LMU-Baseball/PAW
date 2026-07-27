"""PAW — LMU Baseball analytics web app (Flask + Dash).

Application factory. Wires the user store, login, blueprints, the Dash
dashboards, and CLI commands.
"""
import os

from flask import Flask

from config import Config


def create_app(config_object=Config) -> Flask:
    server = Flask(__name__, instance_relative_config=True)
    server.config.from_object(config_object)

    # Ensure the instance folder exists (for the default SQLite app DB).
    os.makedirs(server.instance_path, exist_ok=True)
    default_db_dir = os.path.join(os.path.dirname(server.root_path), "instance")
    os.makedirs(default_db_dir, exist_ok=True)

    from app.extensions import db, login_manager
    db.init_app(server)
    login_manager.init_app(server)

    # Import models so they register with SQLAlchemy + the login user_loader.
    from app.auth import models  # noqa: F401
    from app.data import notes  # noqa: F401  (registers GameNote for create_all)
    from app.data import dev_plans  # noqa: F401  (registers DevPlan for create_all)

    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    server.register_blueprint(auth_bp)
    server.register_blueprint(main_bp)

    from app.reports.routes import report_bp
    server.register_blueprint(report_bp)

    from app.dashboards import register_dashboards
    register_dashboards(server)

    from app.cli import register_cli
    register_cli(server)

    with server.app_context():
        db.create_all()

    return server
