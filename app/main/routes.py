"""Home / landing page (the app shell that links to the dashboards)."""
from flask import Blueprint, render_template
from flask_login import current_user, login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    return render_template("main/index.html", user=current_user)
