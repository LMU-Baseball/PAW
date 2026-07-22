"""Home / landing page (the app shell that links to the dashboards)."""
from flask import Blueprint, render_template
from flask_login import current_user, login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    return render_template("main/index.html", user=current_user)


@main_bp.route("/pitching")
@login_required
def pitching():
    return render_template("main/pitching_hub.html", user=current_user)


@main_bp.route("/hitting")
@login_required
def hitting():
    return render_template("main/hitting_hub.html", user=current_user)


@main_bp.route("/catching")
@login_required
def catching():
    return render_template("main/catching_hub.html", user=current_user)
