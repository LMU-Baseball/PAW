"""Custom Flask CLI commands (user management + data ingestion)."""
import click

from app.auth.models import ROLES, User
from app.extensions import db


def register_cli(server):
    from app.ingest.cli import ingest_cli
    server.cli.add_command(ingest_cli)

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

    @server.cli.command("rebuild-precalc")
    @click.option("--module", default="all",
                  type=click.Choice(["all", "hitting", "pitching", "catching"]),
                  help="Which precalc rollup(s) to rebuild from CAPS.")
    def rebuild_precalc(module):
        """Rebuild the precalc rollup tables from CAPS."""
        from app.data import precalc
        from app.db import get_engine
        engine = get_engine()
        fns = {"hitting": precalc.rebuild_hitting,
               "pitching": precalc.rebuild_pitching,
               "catching": precalc.rebuild_catching}
        targets = list(fns) if module == "all" else [module]
        for m in targets:
            click.echo(f"rebuilt {m}: {fns[m](engine)} rows")
