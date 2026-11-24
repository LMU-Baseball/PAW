# The Forge — S3 video storage setup

The Forge (`/forge/`) works for messaging as soon as it deploys. Video uploads
switch on once `FORGE_S3_BUCKET` is set. Until then, players see "Video uploads
are being set up".

## Why S3 and not the database

The video already in the database is about 53 GB of LONGBLOBs, out of a 57 GB
database. RDS storage costs about $0.115/GB-month, and every snapshot and
backup carries the same bytes again. S3 Standard costs about $0.023/GB-month,
roughly 5x cheaper, and keeps the database small and fast.

Forge video is stored once, as a 720p H.264 copy of about 25–40 MB per minute
of bullpen. The original phone file is deleted after conversion. A 15-minute
session comes to about 0.5 GB, or about a penny a month. Viewing costs S3
egress (about $0.09/GB beyond the free 100 GB/month), which is small at
team scale.

## 1. Bucket (private)

Do **not** reuse `lmubsbvideo`. That bucket is public, and players' training
video should not be.

- Name: `lmubsb-forge`, region `us-east-2`. (Created 2026-11-24 with the settings below.)
- Block **all** public access: leave all four boxes checked.
- Object Ownership: bucket owner enforced (ACLs disabled).
- Default encryption: SSE-S3.

### CORS (Permissions → CORS)

Browsers upload straight to S3, so the bucket must allow PUTs from the PAW
origin. It must also expose `ETag`, or multipart uploads can't be finished.

```json
[
  {
    "AllowedOrigins": ["https://paw.lmubaseball.com", "http://127.0.0.1:8050", "http://localhost:8050"],
    "AllowedMethods": ["PUT", "GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

### Lifecycle rule (Management → Lifecycle)

- Rule "abort-incomplete-uploads": prefix `forge/`, **Delete expired object delete
  markers or incomplete multipart uploads → Incomplete multipart uploads:
  2 days**.

This is the safety net for uploads abandoned in a closed tab. The worker also
cleans these up after 24 h.

## 2. IAM user scoped to that bucket

IAM user `paw-forge` has no console access and no groups, and one inline
policy, `paw-forge-s3`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject",
               "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
    "Resource": "arn:aws:s3:::lmubsb-forge/forge/*"
  }]
}
```

## 3. Environment (`.env` locally and on Lightsail)

```
FORGE_S3_BUCKET=lmubsb-forge
FORGE_S3_REGION=us-east-2
FORGE_AWS_ACCESS_KEY_ID=...        # the paw-forge user's key
FORGE_AWS_SECRET_ACCESS_KEY=...
```

Never commit these values. The repo is public.

## 4. Video worker on Lightsail

The worker converts each upload to 720p, one video at a time. It shares the
same encode lock as the bullpen-video download, so the 2 GB box never runs two
encodes at once. Run it as a systemd service next to gunicorn:

```ini
# /etc/systemd/system/paw-forge.service
[Unit]
Description=PAW Forge video worker
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/paw
ExecStart=/opt/paw/.venv/bin/python scripts/forge_transcode.py
Restart=always
RestartSec=30
MemoryMax=700M

[Install]
WantedBy=multi-user.target
```

The worker reads `/opt/paw/.env` itself (via `config.py`), the same as the
`paw` service, so it needs no `EnvironmentFile`. The deploy workflow restarts
only `paw`, so after a deploy that changes Forge code, also run
`sudo systemctl restart paw-forge`.

```
sudo systemctl daemon-reload && sudo systemctl enable --now paw-forge
journalctl -u paw-forge -f
```

A 15-minute 1080p60 iPhone video takes roughly 10–20 minutes to convert on the
Lightsail CPU. Meanwhile the post shows "Processing video…" and updates by
itself when it's ready.

## Limits

- Up to 20 minutes and 4 GB per video. That fits a full bullpen on an iPhone at
  1080p. Players can trim longer video in Photos first.
- Coaches and players mark moments by typing a timestamp like `2:31` in a
  comment. It becomes a link that seeks the video, and the **+ Comment at
  current time** button fills it in.
