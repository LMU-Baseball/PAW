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
                  help="Optional: links a personal player account to their own "
                       "Trackman data (used only as a convenience default now). "
                       "A shared team player account can omit it.")
    def create_user(email, name, role, password, trackman_id):
        """Create a user account."""
        email = email.strip().lower()
        if User.query.filter_by(email=email).first():
            raise click.ClickException(f"User already exists: {email}")
        user = User(email=email, name=name, role=role, trackman_id=trackman_id)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created {role} {email} (id={user.id}).")

    @server.cli.command("rebuild-precalc")
    @click.option("--module", default="all",
                  type=click.Choice(["all", "hitting", "pitching"]),
                  help="Which precalc rollup(s) to rebuild from CAPS.")
    def rebuild_precalc(module):
        """Rebuild the precalc rollup tables from CAPS."""
        from app.data import precalc
        from app.db import get_engine
        engine = get_engine()
        fns = {"hitting": precalc.rebuild_hitting,
               "pitching": precalc.rebuild_pitching}
        targets = list(fns) if module == "all" else [module]
        for m in targets:
            click.echo(f"rebuilt {m}: {fns[m](engine)} rows")

    @server.cli.command("pipeline-load")
    @click.option("--dry-run/--no-dry-run", default=True,
                  help="Preview only (default). --no-dry-run writes + rebuilds.")
    @click.option("--since-days", type=int, default=3,
                  help="Only walk upload folders from the last N days.")
    def pipeline_load(dry_run, since_days):
        """Load newly-uploaded LMU games from SFTP, then rebuild precalc."""
        from app.ingest.pipeline import run_pipeline
        from app.db import get_engine
        out = run_pipeline(get_engine(), dry_run=dry_run, since_days=since_days)
        r = out["load"]
        click.echo(
            f"pipeline-load: files={r.files} inserted={r.inserted} "
            f"skipped={r.skipped} non_lmu={r.skipped_non_lmu} "
            f"span={r.date_min}..{r.date_max} dry_run={r.dry_run} "
            f"rebuilt={out['rebuilt']}")
