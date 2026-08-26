"""Back up the RDS warehouse to compressed mysqldump files.

Why this exists: the AWS account holding `lmubaseball` (and the ~600 GB
`lmubsbvideo` S3 bucket) is not one the program demonstrably controls. The
database is cheap to copy, so keep a local copy. See
`docs/deploy-meeting-brief.md` for the ownership story.

No MySQL client is installed on the dev box, so this shells out to `mysqldump`
inside the official `mysql:8` Docker image. Nothing is installed permanently.

Usage:
    python scripts/backup_warehouse.py                     # everything except NCAA (~372 MB raw)
    python scripts/backup_warehouse.py --with-ncaa         # + the 3.4 GB NCAA table
    python scripts/backup_warehouse.py --out D:/paw-backups

Restore (into any MySQL 8, e.g. a new program-owned RDS):
    gunzip -c lmubaseball_2026-08-23.sql.gz | mysql -h <newhost> -u admin -p
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

IMAGE = "mysql:8"
ANALYTICS_DB = "lmubaseball"
APP_DB = "paw_app"
BIG_TABLE = "NCAA"  # 3.4 GB of the 3.7 GB total; national data, likely re-derivable

# mysqldump flags that matter here:
#   --single-transaction  consistent snapshot of InnoDB without locking a LIVE db
#   --no-tablespaces      RDS's `admin` lacks the PROCESS privilege that mysqldump 8
#                         otherwise needs; omitting this is the classic RDS failure
#   --set-gtid-purged=OFF keep GTID statements out so the dump restores anywhere
#   --hex-blob            binary-safe
DUMP_FLAGS = [
    "--single-transaction",
    "--no-tablespaces",
    "--set-gtid-purged=OFF",
    "--hex-blob",
    "--routines",
    "--triggers",
    "--default-character-set=utf8mb4",
]


def load_creds() -> dict[str, str]:
    """Read .env with dotenv, NOT the shell.

    The RDS password contains `$#`. Bash silently expands `$#` to something else
    with no error (this corrupted a GitHub secret in Aug 2026). dotenv parses the
    literal value, and passing it to subprocess as a list element means no shell
    ever touches it.
    """
    from dotenv import dotenv_values

    env = dotenv_values(REPO / ".env")
    missing = [k for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD") if not env.get(k)]
    if missing:
        sys.exit(f"error: .env is missing {', '.join(missing)}")
    return {
        "host": env["MYSQL_HOST"],
        "port": env.get("MYSQL_PORT") or "3306",
        "user": env["MYSQL_USER"],
        "password": env["MYSQL_PASSWORD"],
    }


def ensure_image() -> None:
    have = subprocess.run(
        ["docker", "images", "-q", IMAGE], capture_output=True, text=True
    ).stdout.strip()
    if have:
        return
    print(f"  pulling {IMAGE} (one-time, ~250 MB) ...", flush=True)
    if subprocess.run(["docker", "pull", IMAGE]).returncode != 0:
        sys.exit(f"error: could not pull {IMAGE} — is Docker Desktop running?")


def dump(creds: dict[str, str], out: Path, args: list[str], label: str) -> dict:
    """Stream mysqldump stdout straight into a gzip file on the host.

    Streaming means no giant temp file and no Docker volume mount. The password
    rides in the container env (MYSQL_PWD), which mysqldump reads natively — so it
    never appears in a command line or a process list.
    """
    cmd = [
        "docker", "run", "--rm",
        "-e", f"MYSQL_PWD={creds['password']}",
        IMAGE,
        "mysqldump",
        "-h", creds["host"], "-P", creds["port"], "-u", creds["user"],
        *DUMP_FLAGS, *args,
    ]
    print(f"  {label} -> {out.name} ...", end="", flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with gzip.open(out, "wb", compresslevel=6) as fh:
        shutil.copyfileobj(proc.stdout, fh, length=1 << 20)
    proc.stdout.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    rc = proc.wait()

    # mysqldump chatters harmless notices to stderr; only a nonzero exit is fatal.
    if rc != 0:
        out.unlink(missing_ok=True)
        print(" FAILED")
        sys.exit(f"error: mysqldump exited {rc}\n{err.strip()}")

    mb = out.stat().st_size / 1e6
    print(f" {mb:,.1f} MB gz")
    return {"file": out.name, "mb_gz": round(mb, 1), "stderr": err.strip()}


def verify(path: Path) -> dict:
    """A backup nobody checked is not a backup. Confirm the dump is complete."""
    tables, completed, lines = 0, False, 0
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            lines += 1
            if line.startswith("CREATE TABLE"):
                tables += 1
            elif line.startswith("-- Dump completed"):
                completed = True
    return {"create_tables": tables, "dump_completed": completed, "lines": lines}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO.parent / "backups"),
                    help="destination directory (default: ../backups, outside the repo)")
    ap.add_argument("--with-ncaa", action="store_true",
                    help="also dump the 3.4 GB NCAA table (separate file)")
    a = ap.parse_args()

    creds = load_creds()
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()

    print(f"PAW warehouse backup  {stamp}")
    print(f"  host: {creds['host']}")
    print(f"  out:  {outdir}")
    ensure_image()

    manifest: dict = {"date": stamp, "host": creds["host"], "dumps": []}

    # Row counts at dump time, so a restore can be checked against reality.
    try:
        from app.db import query_df
        counts = query_df(
            "SELECT table_schema AS s, table_name AS t, table_rows AS n "
            "FROM information_schema.tables WHERE table_schema IN (:a, :b)",
            {"a": ANALYTICS_DB, "b": APP_DB},
        )
        manifest["approx_row_counts"] = {
            f"{r.s}.{r.t}": int(r.n or 0) for r in counts.itertuples()
        }
    except Exception as exc:  # non-fatal; the dumps are the point
        manifest["approx_row_counts_error"] = f"{type(exc).__name__}: {exc}"

    jobs = [
        (f"{ANALYTICS_DB} (excl. {BIG_TABLE})",
         outdir / f"{ANALYTICS_DB}_{stamp}.sql.gz",
         ["--databases", ANALYTICS_DB, f"--ignore-table={ANALYTICS_DB}.{BIG_TABLE}"]),
        (f"{APP_DB} (accounts, notes, dev plans)",
         outdir / f"{APP_DB}_{stamp}.sql.gz",
         ["--databases", APP_DB]),
    ]
    if a.with_ncaa:
        jobs.append((f"{ANALYTICS_DB}.{BIG_TABLE} (3.4 GB)",
                     outdir / f"{ANALYTICS_DB}_{BIG_TABLE}_{stamp}.sql.gz",
                     [ANALYTICS_DB, BIG_TABLE]))

    for label, path, args in jobs:
        rec = dump(creds, path, args, label)
        rec.update(verify(path))
        manifest["dumps"].append(rec)

    (outdir / f"manifest_{stamp}.json").write_text(json.dumps(manifest, indent=2))

    print("\nverification")
    ok = True
    for d in manifest["dumps"]:
        mark = "OK " if d["dump_completed"] else "BAD"
        ok &= d["dump_completed"]
        print(f"  [{mark}] {d['file']}: {d['create_tables']} tables, "
              f"{d['mb_gz']} MB gz, completed={d['dump_completed']}")
    if not a.with_ncaa:
        print(f"\n  note: {BIG_TABLE} was skipped (3.4 GB). Re-run with --with-ncaa to include it.")
    print("\nDONE" if ok else "\nINCOMPLETE — a dump did not finish; do not trust it")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
