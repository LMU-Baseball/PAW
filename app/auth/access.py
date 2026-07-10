"""Role-based access helpers."""
from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(*roles):
    """Restrict a view to the given role(s). 401 if anonymous, 403 if wrong role."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def can_view_player(user, trackman_id) -> bool:
    """Standalone check usable outside a view (e.g. inside Dash callbacks)."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.can_view_player(trackman_id)


def can_view_pitcher_report(user, pitcher_id) -> bool:
    """Coaches see all; a player sees only their own pitcher report."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.role == "coach":
        return True
    from app.data.pitching import pitcher_tm_id_for
    tm_id = pitcher_tm_id_for(pitcher_id)
    return tm_id is not None and str(user.trackman_id) == str(tm_id)
