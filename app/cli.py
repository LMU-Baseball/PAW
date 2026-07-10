"""Custom Flask CLI commands (user management)."""
import click

from app.auth.models import ROLES, User
from app.extensions import db


def register_cli(server):
    @server.cli.command("create-user")
    @click.option("--email", required=True)
    @click.option("--name", required=True)
    @click.option("--role", type=click.Choice(ROLES), required=True)
    @click.option("--password", required=True, help="Initial password.")
    @click.option("--trackman-id", type=int, default=None,
                  help="Required for players; links them to their Trackman data.")
    def create_user(email, name, role, password, trackman_id):
        """Create a user account."""
        email = email.strip().lower()
        if User.query.filter_by(email=email).first():
            raise click.ClickException(f"User already exists: {email}")
        if role == "player" and trackman_id is None:
            raise click.ClickException("Players require --trackman-id.")
        user = User(email=email, name=name, role=role, trackman_id=trackman_id)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created {role} {email} (id={user.id}).")
