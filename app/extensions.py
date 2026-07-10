"""Flask extension singletons, initialized in the app factory."""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()          # user/account store (app DB)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "error"
