"""The Forge's video worker: converts uploaded videos to 720p, one at a time.

Run (Lightsail, as a systemd service -- see docs/forge-s3-setup.md):
    python scripts/forge_transcode.py            # loop forever, checking every 20 s
    python scripts/forge_transcode.py --once     # process the queue, then exit

Uses a bare Flask app (config + DB only) rather than create_app(), so this
process doesn't build every Dash dashboard and stays small on the 2 GB box.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask  # noqa: E402

from config import Config  # noqa: E402

POLL_SEC = 20


def make_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    from app.extensions import db
    db.init_app(app)
    from app.auth import models  # noqa: F401
    from app.data import forge  # noqa: F401
    with app.app_context():
        db.create_all()
        forge.ensure_columns()
    return app


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if hasattr(os, "nice"):
        os.nice(10)

    from app.data import forge_storage
    if not forge_storage.configured():
        logging.error("FORGE_S3_BUCKET is not set; nothing to do.")
        return 1

    from app.extensions import db
    from app.forge import transcode
    app = make_app()
    with app.app_context():
        requeued = transcode.reset_interrupted()
        if requeued:
            logging.info("requeued %d interrupted video(s)", requeued)
        while True:
            try:
                n = transcode.run_once()
                if n:
                    logging.info("processed %d video(s)", n)
            except Exception:
                logging.exception("forge worker pass failed")
            finally:
                db.session.remove()
            if args.once:
                return 0
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
