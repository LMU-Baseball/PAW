"""Login / logout / registration / password change, plus the email-driven
verify-address, forgot-password and periodic sign-in-code flows."""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlparse

from flask import (Blueprint, current_app, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length, ValidationError

from app.auth import tokens
from app.auth.access import role_required
from app.auth.mail import mail_enabled, send_mail
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


def _matches_coach_code(entered: str | None) -> bool:
    """True if `entered` is the configured PAW_COACH_CODE (case-insensitive).
    Read live, not at import time, same reasoning as `_team_code` below."""
    coach_code = (os.getenv("PAW_COACH_CODE") or "").strip()
    return bool(coach_code) and (entered or "").strip().lower() == coach_code.lower()


def _team_code(form, field):
    # PAW_TEAM_CODE unset/blank = gate disabled (today's domain-only behavior).
    # Read live rather than at import time so a deployed env-var change takes
    # effect without a restart-triggering code change.
    #
    # PAW_COACH_CODE (2026-09-18, Brad: "add a team code so I can share that
    # one with coaches and their account will register as a coach / the team
    # code is for player accounts") -- a second, separate code shared only
    # with coaches. It's always accepted here regardless of PAW_TEAM_CODE's
    # own state (even if the team-code gate is currently open/unset, a coach
    # entering the coach code must never be rejected) -- which of the two
    # codes was actually entered is what decides coach vs. player role, in
    # register() below, not this validator.
    if _matches_coach_code(field.data):
        return
    required = (os.getenv("PAW_TEAM_CODE") or "").strip()
    if not required:
        return
    if (field.data or "").strip().lower() != required.lower():
        raise ValidationError("Incorrect team code.")


class RegisterForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), _lmu_email])
    team_code = StringField("Team code", validators=[_team_code])
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


class EmailForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    submit = SubmitField("Send link")


class ResetPasswordForm(FlaskForm):
    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=8, message="Use at least 8 characters.")])
    confirm = PasswordField("Confirm new password", validators=[
        DataRequired(), EqualTo("new_password", message="Passwords must match.")])
    submit = SubmitField("Set new password")


_SIGNATURE = "\n\n-- LMU Baseball PAW"


def _send_verify_email(user: User) -> bool:
    link = url_for("auth.verify_email", token=tokens.make_verify_token(user), _external=True)
    return send_mail(user.email, "Confirm your PAW account",
                     f"Hi {user.name},\n\nConfirm your email to finish setting up your PAW "
                     f"account:\n\n{link}\n\nThis link expires in 3 days. If you didn't "
                     f"create a PAW account, you can ignore this email.{_SIGNATURE}")


def _send_reset_email(user: User) -> bool:
    link = url_for("auth.reset_password", token=tokens.make_reset_token(user), _external=True)
    return send_mail(user.email, "Reset your PAW password",
                     f"Hi {user.name},\n\nSomeone (hopefully you) asked to reset your PAW "
                     f"password. Choose a new one here:\n\n{link}\n\nThis link expires in "
                     f"1 hour and works once. If you didn't ask for this, ignore this email -- "
                     f"your password hasn't changed.{_SIGNATURE}")


class CodeForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired()])
    submit = SubmitField("Sign in")


_CODE_TTL_SECONDS = 15 * 60
_CODE_MAX_TRIES = 5
_PENDING_KEY = "pending_code_login"


def _code_digest(uid: int, code: str) -> str:
    # The Flask session cookie is signed but NOT encrypted -- the browser can
    # read it -- so the code itself must never be stored there, only a keyed
    # hash the browser can't reverse without SECRET_KEY.
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{uid}:{code}".encode(), hashlib.sha256).hexdigest()


def _start_code_check(user: User, next_url: str | None):
    code = f"{secrets.randbelow(1_000_000):06d}"
    sent = send_mail(user.email, f"Your PAW sign-in code: {code}",
                     f"Hi {user.name},\n\nYour PAW sign-in code is:\n\n    {code}\n\n"
                     f"It expires in 15 minutes. PAW asks for this about once a month to "
                     f"confirm you're still on the team. If you didn't just try to sign in, "
                     f"change your password.{_SIGNATURE}")
    if not sent:
        flash("We couldn't send your sign-in code. Try again in a few minutes.", "error")
        return redirect(url_for("auth.login"))
    session[_PENDING_KEY] = {"uid": user.id, "epoch": user.session_epoch or 0,
                             "digest": _code_digest(user.id, code),
                             "exp": time.time() + _CODE_TTL_SECONDS, "tries": 0,
                             "next": next_url}
    return redirect(url_for("auth.login_code"))


def _lookup(email: str | None) -> User | None:
    return User.query.filter_by(email=(email or "").strip().lower()).first()


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
            if mail_enabled() and not user.email_verified:
                flash("Confirm your email first -- check your inbox for the link, "
                      "or send a new one below.", "error")
                return redirect(url_for("auth.resend_verification", email=user.email))
            if user.reverify_due:
                return _start_code_check(user, _safe_next(request.args.get("next")))
            user.record_login()
            db.session.commit()
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
            # Coach role from EITHER the email allowlist (PAW_COACH_EMAILS,
            # pre-listed individuals) OR the coach code (self-service, no
            # allowlist maintenance needed) -- either one is sufficient.
            role = "coach" if (is_coach_email(email) or _matches_coach_code(form.team_code.data)) \
                else "player"
            user = User(email=email, name=form.name.data.strip(), role=role)
            user.set_password(form.password.data)
            if not mail_enabled():
                user.mark_email_verified()
            db.session.add(user)
            db.session.commit()
            if user.email_verified:
                login_user(user)
                flash("Account created.", "info")
                return redirect(url_for("main.index"))
            if _send_verify_email(user):
                flash(f"Account created. We sent a confirmation link to {email} -- "
                      "click it to sign in.", "info")
                return redirect(url_for("auth.login"))
            else:
                flash("Account created, but the confirmation email didn't send. "
                      "Try sending it again below.", "error")
            return redirect(url_for("auth.resend_verification", email=email))
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
            user = current_user._get_current_object()
            user.set_password(form.new_password.data)
            # Logs out every other device (e.g. someone who learned the old
            # password); re-login keeps this browser signed in under the new epoch.
            user.sign_out_everywhere()
            db.session.commit()
            login_user(user)
            flash("Password changed. Any other devices were signed out.", "info")
            return redirect(url_for("main.index"))
    return render_template("auth/change_password.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    user = tokens.user_from_verify_token(token)
    if user is None:
        flash("That confirmation link is invalid or has expired. Send a new one below.", "error")
        return redirect(url_for("auth.resend_verification"))
    user.mark_email_verified()
    user.record_login()
    db.session.commit()
    if not user.is_active:
        flash("Email confirmed, but this account is turned off. Ask a coach.", "error")
        return redirect(url_for("auth.login"))
    login_user(user)
    flash("Email confirmed -- welcome to the PAW.", "info")
    return redirect(url_for("main.index"))


# Every POST costs budget (no deduct_when): each one can send an email, so this
# limit is what stops the form being used to spam someone's inbox.
@auth_bp.route("/resend-verification", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def resend_verification():
    if not mail_enabled():
        return redirect(url_for("auth.login"))
    form = EmailForm()
    if request.method == "GET" and request.args.get("email"):
        form.email.data = request.args["email"]
    if form.validate_on_submit():
        user = _lookup(form.email.data)
        if user and user.is_active and not user.email_verified:
            _send_verify_email(user)
        # Same answer whether or not the account exists, so this form can't be
        # used to discover who has a PAW account.
        flash("If that account is waiting on confirmation, a new link is on its way.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/email_form.html", form=form, title="Confirm your email",
                           intro="Didn't get the confirmation email? Enter your LMU email "
                                 "and we'll send a new link.",
                           action=url_for("auth.resend_verification"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("auth.change_password"))
    form = EmailForm()
    if mail_enabled() and form.validate_on_submit():
        user = _lookup(form.email.data)
        if user and user.is_active:
            _send_reset_email(user)
        flash("If there's a PAW account for that email, a reset link is on its way. "
              "It expires in 1 hour.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/email_form.html", form=form, title="Forgot password",
                           intro="Enter your LMU email and we'll send you a link to choose "
                                 "a new password.",
                           action=url_for("auth.forgot_password"),
                           disabled=not mail_enabled())


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = tokens.user_from_reset_token(token)
    if user is None:
        flash("That reset link is invalid, expired, or already used. Request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.new_password.data)
        # Receiving the link proves they own the address.
        user.mark_email_verified()
        user.sign_out_everywhere()
        db.session.commit()
        logout_user()
        flash("Password updated -- sign in with your new password.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form, token=token)


class AccountActionForm(FlaskForm):
    """Empty form -- exists only to carry the CSRF token on the per-row
    action buttons of the accounts page."""


_ACCOUNT_ACTIONS = ("deactivate", "activate", "make-coach", "make-player",
                    "sign-out", "send-reset")
_SELF_BLOCKED = {"deactivate", "make-player", "sign-out"}


@auth_bp.route("/accounts")
@login_required
@role_required("coach")
def accounts():
    users = User.query.order_by(User.is_active.desc(), User.role, User.name).all()
    return render_template("auth/accounts.html", users=users, form=AccountActionForm(),
                           mail_on=mail_enabled())


@auth_bp.route("/accounts/<int:user_id>/<action>", methods=["POST"])
@login_required
@role_required("coach")
def account_action(user_id, action):
    form = AccountActionForm()
    user = db.session.get(User, user_id)
    if action not in _ACCOUNT_ACTIONS or user is None or not form.validate_on_submit():
        flash("That action couldn't be completed.", "error")
        return redirect(url_for("auth.accounts"))
    if user.id == current_user.id and action in _SELF_BLOCKED:
        # A coach turning off or demoting their own account would lock them
        # out of this page with no way back in except the server CLI.
        flash("You can't do that to your own account.", "error")
        return redirect(url_for("auth.accounts"))

    if action == "deactivate":
        user.is_active = False
        msg = f"Turned off {user.email}. They're signed out everywhere."
    elif action == "activate":
        user.is_active = True
        msg = f"Turned {user.email} back on."
    elif action == "make-coach":
        user.role = "coach"
        msg = f"{user.email} is now a coach."
    elif action == "make-player":
        user.role = "player"
        msg = f"{user.email} is now a player."
    elif action == "sign-out":
        user.sign_out_everywhere()
        msg = f"Signed {user.email} out of every device."
    else:
        if not (mail_enabled() and user.is_active and _send_reset_email(user)):
            flash(f"Couldn't send a reset email to {user.email}.", "error")
            return redirect(url_for("auth.accounts"))
        msg = f"Sent a password reset link to {user.email}."
    db.session.commit()
    flash(msg, "info")
    return redirect(url_for("auth.accounts"))


# The tries counter lives in the client's cookie, so a replayed cookie could
# reset it -- this per-IP limit is the real brute-force bound (10 guesses an
# hour against a 1-in-a-million code that expires in 15 minutes).
@auth_bp.route("/login/code", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def login_code():
    pending = session.get(_PENDING_KEY)
    if not pending or time.time() > pending.get("exp", 0):
        session.pop(_PENDING_KEY, None)
        flash("That sign-in code expired. Sign in again to get a new one.", "error")
        return redirect(url_for("auth.login"))
    user = db.session.get(User, pending["uid"])
    if user is None or not user.is_active or (user.session_epoch or 0) != pending["epoch"]:
        session.pop(_PENDING_KEY, None)
        return redirect(url_for("auth.login"))
    form = CodeForm()
    if form.validate_on_submit():
        entered = "".join(ch for ch in form.code.data if ch.isdigit())
        if hmac.compare_digest(_code_digest(user.id, entered), pending["digest"]):
            session.pop(_PENDING_KEY, None)
            user.mark_email_checked()
            user.record_login()
            db.session.commit()
            login_user(user)
            return redirect(pending.get("next") or url_for("main.index"))
        pending["tries"] += 1
        if pending["tries"] >= _CODE_MAX_TRIES:
            session.pop(_PENDING_KEY, None)
            flash("Too many wrong codes. Sign in again to get a new one.", "error")
            return redirect(url_for("auth.login"))
        session[_PENDING_KEY] = pending
        flash("That code didn't match. Check the most recent email.", "error")
    return render_template("auth/login_code.html", form=form, email=user.email)
