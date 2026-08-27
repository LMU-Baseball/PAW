"""Login / logout / change password."""
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length, ValidationError

from app.auth.models import User, is_coach_email
from app.extensions import db, limiter

auth_bp = Blueprint("auth", __name__)

_LMU_DOMAINS = {"lmu.edu", "lion.lmu.edu"}


def _lmu_email(form, field):
    # No wtforms.validators.Email() here -- it requires the extra
    # `email_validator` package, which isn't a project dependency. The domain
    # check below already implies a well-formed local-part@domain shape.
    value = (field.data or "").strip()
    local, sep, domain = value.rpartition("@")
    if not sep or not local:
        raise ValidationError("Enter a valid email address.")
    if domain.lower() not in _LMU_DOMAINS:
        raise ValidationError("Use your LMU email address (@lmu.edu or @lion.lmu.edu).")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Sign in")


class RegisterForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), _lmu_email])
    password = PasswordField(
        "Password", validators=[DataRequired(), Length(min=8, message="Use at least 8 characters.")])
    confirm = PasswordField("Confirm password", validators=[
        DataRequired(), EqualTo("password", message="Passwords must match.")])
    submit = SubmitField("Create account")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=8, message="Use at least 8 characters.")])
    confirm = PasswordField("Confirm new password", validators=[
        DataRequired(), EqualTo("new_password", message="Passwords must match.")])
    submit = SubmitField("Change password")


def _safe_next(target: str | None) -> str | None:
    """Only allow same-site relative redirects (prevents open-redirect)."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.netloc == "" and parsed.scheme == "" and target.startswith("/"):
        return target
    return None


@auth_bp.route("/login", methods=["GET", "POST"])
# deduct_when: only count a POST against the budget when it did NOT redirect.
# A successful login returns 302 (redirect to `next`/home); a failed one
# re-renders the form with 200. Without this, correct passwords burn the same
# budget as wrong ones -- so 10 successful logins from the whole shared-account
# team lock everyone out for an hour. Do not simplify this away: the whole
# point is that only failures should ever cost budget.
@limiter.limit("10 per hour", methods=["POST"],
                deduct_when=lambda resp: resp.status_code != 302)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user)
            return redirect(_safe_next(request.args.get("next")) or url_for("main.index"))
        flash("Invalid email or password.", "error")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
# Same deduct_when shape as /login and for the same reason: only a rejected
# submission (200, re-rendered) should cost budget, not a successful one.
@limiter.limit("10 per hour", methods=["POST"],
                deduct_when=lambda resp: resp.status_code != 302)
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists. Try signing in instead.", "error")
        else:
            role = "coach" if is_coach_email(email) else "player"
            user = User(email=email, name=form.name.data.strip(), role=role)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Account created.", "info")
            return redirect(url_for("main.index"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Let any logged-in account change its own password (verifies the
    current one first). No longer coach-only: accounts are per-person now,
    so there's no shared-login lockout risk."""
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Password changed.", "info")
            return redirect(url_for("main.index"))
    return render_template("auth/change_password.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
