"""Private S3 storage for Forge video.

Uploads go browser -> S3 directly as a multipart upload through presigned
part URLs, so a multi-GB phone video never streams through the 2 GB Lightsail
box. Playback and thumbnails are short-lived presigned GETs; nothing in the
bucket is public. Setup (bucket, CORS, IAM policy, env vars):
docs/forge-s3-setup.md.

Credentials come from FORGE_AWS_ACCESS_KEY_ID / FORGE_AWS_SECRET_ACCESS_KEY
(the bucket-scoped `paw-forge` IAM user), kept separate from any other AWS key
in .env so the two can never be swapped. Also FORGE_S3_BUCKET and optionally
FORGE_S3_REGION. With no bucket set, configured() is False and the
Forge runs messaging-only.
"""
from __future__ import annotations

import math
import os

PART_SIZE = 16 * 1024 ** 2
UPLOAD_URL_TTL = 6 * 3600
VIEW_URL_TTL = 3600

_client = None


def bucket() -> str:
    return os.getenv("FORGE_S3_BUCKET", "").strip()


def configured() -> bool:
    return bool(bucket())


def _s3():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config
        region = os.getenv("FORGE_S3_REGION", "us-east-2")
        # Regional virtual-hosted URLs: a presigned URL for a bucket outside
        # us-east-1 otherwise redirects, which a browser PUT can't follow.
        _client = boto3.client(
            "s3", region_name=region,
            aws_access_key_id=os.getenv("FORGE_AWS_ACCESS_KEY_ID") or None,
            aws_secret_access_key=os.getenv("FORGE_AWS_SECRET_ACCESS_KEY") or None,
            endpoint_url=f"https://s3.{region}.amazonaws.com",
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
    return _client


def original_key(channel_id: int, video_id: int, filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    ext = ext if ext in {".mov", ".mp4", ".m4v", ".avi", ".webm", ".3gp"} else ".mov"
    return f"forge/{channel_id}/{video_id}/original{ext}"


def playback_key(channel_id: int, video_id: int) -> str:
    return f"forge/{channel_id}/{video_id}/720p.mp4"


def thumb_key(channel_id: int, video_id: int) -> str:
    return f"forge/{channel_id}/{video_id}/thumb.jpg"


def part_count(size: int) -> int:
    return max(1, math.ceil(size / PART_SIZE))


def start_multipart(key: str, content_type: str, size: int) -> tuple[str, list[str]]:
    """Begin a multipart upload; returns (upload_id, presigned PUT url per part)."""
    s3 = _s3()
    upload_id = s3.create_multipart_upload(
        Bucket=bucket(), Key=key, ContentType=content_type or "application/octet-stream")["UploadId"]
    urls = [s3.generate_presigned_url(
        "upload_part",
        Params={"Bucket": bucket(), "Key": key, "UploadId": upload_id, "PartNumber": n},
        ExpiresIn=UPLOAD_URL_TTL) for n in range(1, part_count(size) + 1)]
    return upload_id, urls


def complete_multipart(key: str, upload_id: str, parts: list[dict]) -> None:
    _s3().complete_multipart_upload(
        Bucket=bucket(), Key=key, UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": int(p["n"]), "ETag": p["etag"]}
                                   for p in sorted(parts, key=lambda p: int(p["n"]))]})


def abort_multipart(key: str, upload_id: str) -> None:
    _s3().abort_multipart_upload(Bucket=bucket(), Key=key, UploadId=upload_id)


def view_url(key: str, content_type: str | None = None) -> str:
    params = {"Bucket": bucket(), "Key": key}
    if content_type:
        params["ResponseContentType"] = content_type
    return _s3().generate_presigned_url("get_object", Params=params, ExpiresIn=VIEW_URL_TTL)


def download(key: str, path: str) -> None:
    _s3().download_file(bucket(), key, path)


def upload(path: str, key: str, content_type: str) -> None:
    _s3().upload_file(path, bucket(), key, ExtraArgs={"ContentType": content_type})


def delete(key: str) -> None:
    _s3().delete_object(Bucket=bucket(), Key=key)
