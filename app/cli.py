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

    @server.cli.command("set-password")
    @click.option("--email", required=True)
    @click.option("--password", required=True, help="The new password.")
    def set_password(email, password):
        """Reset an existing user's password (admin recovery path)."""
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            raise click.ClickException(f"No user with email: {email}")
        user.set_password(password)
        db.session.commit()
        click.echo(f"Password updated for {email}.")

    @server.cli.command("set-role")
    @click.option("--email", required=True)
    @click.option("--role", type=click.Choice(ROLES), required=True)
    def set_role(email, role):
        """Change an existing user's role (e.g. fix a mis-assigned self-registration)."""
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            raise click.ClickException(f"No user with email: {email}")
        user.role = role
        db.session.commit()
        click.echo(f"Set {email} role to {role}.")

    @server.cli.command("set-active")
    @click.option("--email", required=True)
    @click.option("--active/--inactive", "active", required=True,
                  help="--inactive blocks login without deleting the account "
                       "(e.g. a graduated player); --active restores it.")
    def set_active(email, active):
        """Activate or deactivate a user account."""
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            raise click.ClickException(f"No user with email: {email}")
        user.is_active = active
        db.session.commit()
        click.echo(f"Account {'activated' if active else 'deactivated'}: {email}.")

    @server.cli.command("set-trackman-id")
    @click.option("--email", required=True)
    @click.option("--trackman-id", type=int, required=True)
    def set_trackman_id(email, trackman_id):
        """Link an existing account to their Trackman id (own-player convenience default)."""
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            raise click.ClickException(f"No user with email: {email}")
        user.trackman_id = trackman_id
        db.session.commit()
        click.echo(f"Linked {email} -> trackman_id {trackman_id}.")

    @server.cli.command("forge-link")
    @click.option("--email", required=True)
    @click.option("--channel", "channel_name", default=None,
                  help="Roster name of the Forge channel to give this account.")
    @click.option("--unlink", is_flag=True,
                  help="Free this account's channel and clear its position answer, "
                       "so the player is asked again.")
    def forge_link(email, channel_name, unlink):
        """Fix which Forge channel an account owns (a pitcher who picked the wrong name)."""
        from app.data import forge
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            raise click.ClickException(f"No user with email: {email}")
        current = forge.channel_of(user)
        if unlink or channel_name:
            if current is not None:
                current.user_id = None
            user.player_type = None
            db.session.commit()
        if channel_name:
            target = forge.ForgeChannel.query.filter_by(name=channel_name).first()
            if target is None:
                raise click.ClickException(f"No Forge channel named: {channel_name}")
            try:
                forge.claim(user, "pitcher", target.id)
            except ValueError as e:
                raise click.ClickException(str(e)) from e
        now = forge.channel_of(user)
        click.echo(f"{email}: {now.name if now else 'no channel'} "
                   f"(player_type={user.player_type}).")

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

    @server.cli.command("roster-reconcile")
    @click.option("--season", default=None,
                  help="Season label, e.g. 2026/2027 (default: today's calendar season).")
    @click.option("--dry-run", is_flag=True, help="Report what would move, change nothing.")
    def roster_reconcile(season, dry_run):
        """Migrate Cauldron/Velo Board/Built on the Bluff rows from placeholder
        roster ids to real Trackman ids, for pitchers who now have real data."""
        from datetime import date
        from app.data import lmu_roster, seasons
        season = season or seasons.season_label_for(date.today().isoformat())
        n = lmu_roster.reconcile_ids(season, dry_run=dry_run)
        verb = "would migrate" if dry_run else "migrated"
        click.echo(f"roster-reconcile ({season}): {verb} {n} row(s)")

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
            f"excluded={r.skipped_excluded} "
            f"span={r.date_min}..{r.date_max} dry_run={r.dry_run} "
            f"rebuilt={out['rebuilt']}")
